"""Escalation Queue API — manage messages that need human review."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_tenant_db
from app.models.agent_run import AgentRun
from app.models.message import Message
from app.models.user import User

router = APIRouter(prefix="/escalations", tags=["escalations"])


class EscalationAction(BaseModel):
    action: str  # approve, reject, edit_and_send
    edited_message: str | None = None


@router.get("")
async def list_escalations(
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
    client_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """List escalated agent runs — messages awaiting human review."""
    query = (
        select(AgentRun)
        .where(AgentRun.decision.in_(["escalate", "pending_approval"]))
        .order_by(desc(AgentRun.created_at))
    )
    if client_id:
        query = query.where(AgentRun.client_id == client_id)

    # Count
    count_query = select(func.count(AgentRun.id)).where(
        AgentRun.decision.in_(["escalate", "pending_approval"])
    )
    if client_id:
        count_query = count_query.where(AgentRun.client_id == client_id)
    total = (await db.execute(count_query)).scalar()

    result = await db.execute(query.limit(limit).offset(offset))
    runs = result.scalars().all()

    items = []
    for run in runs:
        # Get the draft message
        msg_result = await db.execute(
            select(Message)
            .where(
                Message.conversation_id == run.conversation_id,
                Message.direction == "outbound",
                Message.status == "draft",
            )
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        draft = msg_result.scalar_one_or_none()

        # Get the trigger message
        trigger = None
        if run.trigger_message_id:
            trigger_result = await db.execute(
                select(Message).where(Message.id == run.trigger_message_id)
            )
            trigger = trigger_result.scalar_one_or_none()

        items.append({
            "id": str(run.id),
            "conversation_id": str(run.conversation_id),
            "client_id": str(run.client_id),
            "decision": run.decision,
            "confidence_score": run.confidence_score,
            "policy_flags": run.policy_flags,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "lead_message": trigger.content if trigger else None,
            "draft_response": draft.content if draft else None,
            "draft_message_id": str(draft.id) if draft else None,
        })

    return {"total": total, "limit": limit, "offset": offset, "escalations": items}


@router.post("/{run_id}/resolve")
async def resolve_escalation(
    run_id: uuid.UUID,
    body: EscalationAction,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """
    Resolve an escalation.

    Actions:
    - approve: Send the draft as-is
    - reject: Discard the draft
    - edit_and_send: Replace draft content and send
    """
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    if run.decision not in ("escalate", "pending_approval"):
        raise HTTPException(status_code=400, detail="This run is not escalated")

    # Get the draft message
    msg_result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == run.conversation_id,
            Message.direction == "outbound",
            Message.status == "draft",
        )
        .order_by(desc(Message.created_at))
        .limit(1)
    )
    draft = msg_result.scalar_one_or_none()

    # Get lead_id from conversation
    from app.models.conversation import Conversation
    from app.models.feedback import ToneFeedback
    conv_result = await db.execute(select(Conversation).where(Conversation.id == run.conversation_id))
    conv = conv_result.scalar_one_or_none()
    lead_id = conv.lead_id if conv else None

    original_draft_content = draft.content if draft else ""

    if body.action == "approve":
        if draft:
            draft.status = "sent"
            draft.sender_type = "human_approved"
        run.decision = "send_approved"

        if lead_id and draft:
            feedback = ToneFeedback(
                client_id=run.client_id,
                agency_id=run.agency_id,
                lead_id=lead_id,
                original_draft=original_draft_content,
                human_response=original_draft_content,
                edited=False,
            )
            db.add(feedback)

    elif body.action == "reject":
        if draft:
            draft.status = "rejected"
        run.decision = "rejected"

    elif body.action == "edit_and_send":
        if not body.edited_message:
            raise HTTPException(status_code=400, detail="edited_message required for edit_and_send")
        if draft:
            draft.content = body.edited_message
            draft.status = "sent"
            draft.sender_type = "human_edited"
        run.decision = "send_edited"

        if lead_id and draft:
            feedback = ToneFeedback(
                client_id=run.client_id,
                agency_id=run.agency_id,
                lead_id=lead_id,
                original_draft=original_draft_content,
                human_response=body.edited_message,
                edited=True,
            )
            db.add(feedback)

    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be: approve, reject, edit_and_send")

    await db.commit()

    # Trigger self-correcting RLHF tuning autonomously
    if body.action == "edit_and_send":
        try:
            from app.services.rlhf import auto_tune_prompt
            await auto_tune_prompt(db, run.client_id)
        except Exception:
            pass

    return {
        "run_id": str(run.id),
        "action": body.action,
        "decision": run.decision,
        "message_status": draft.status if draft else None,
    }


@router.get("/stats")
async def escalation_stats(
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
    client_id: uuid.UUID | None = None,
):
    """Get escalation stats — pending, resolved, and reasons."""
    base = select(AgentRun.decision, func.count(AgentRun.id)).group_by(AgentRun.decision)
    if client_id:
        base = base.where(AgentRun.client_id == client_id)

    result = await db.execute(base)
    by_decision = {row[0]: row[1] for row in result.all()}

    pending = by_decision.get("escalate", 0) + by_decision.get("pending_approval", 0)
    resolved = by_decision.get("send_approved", 0) + by_decision.get("send_edited", 0) + by_decision.get("rejected", 0)

    return {
        "pending": pending,
        "resolved": resolved,
        "by_decision": by_decision,
    }
