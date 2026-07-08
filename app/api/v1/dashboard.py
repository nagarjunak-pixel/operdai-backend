"""Dashboard API — aggregated stats for the frontend dashboard."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_tenant_db
from app.models.agent_run import AgentRun
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
    client_id: uuid.UUID | None = None,
):
    """
    Get aggregated dashboard statistics for the current tenant.
    Returns lead counts, conversation stats, agent run metrics, and costs.
    """
    # Build base filters
    lead_filter = select(Lead)
    conv_filter = select(Conversation)
    run_filter = select(AgentRun)
    msg_filter = select(Message)

    if client_id:
        lead_filter = lead_filter.where(Lead.client_id == client_id)
        conv_filter = conv_filter.where(Conversation.client_id == client_id)
        run_filter = run_filter.where(AgentRun.client_id == client_id)
        msg_filter = msg_filter.where(Message.client_id == client_id)

    # Total leads
    total_leads_result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.client_id == client_id if client_id else True
        )
    )
    total_leads = total_leads_result.scalar() or 0

    # Leads by status
    status_result = await db.execute(
        select(Lead.status, func.count(Lead.id))
        .where(Lead.client_id == client_id if client_id else True)
        .group_by(Lead.status)
    )
    leads_by_status = {row[0]: row[1] for row in status_result.all()}

    # Total conversations
    total_convs_result = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.client_id == client_id if client_id else True
        )
    )
    total_conversations = total_convs_result.scalar() or 0

    # Active conversations
    active_convs_result = await db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.status == "active",
            Conversation.client_id == client_id if client_id else True,
        )
    )
    active_conversations = active_convs_result.scalar() or 0

    # Total agent runs
    runs_result = await db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.client_id == client_id if client_id else True
        )
    )
    total_agent_runs = runs_result.scalar() or 0

    # Agent decisions breakdown
    decisions_result = await db.execute(
        select(AgentRun.decision, func.count(AgentRun.id))
        .where(AgentRun.client_id == client_id if client_id else True)
        .group_by(AgentRun.decision)
    )
    decisions = {row[0] or "unknown": row[1] for row in decisions_result.all()}

    # Escalation count
    escalated_count = decisions.get("escalate", 0) + decisions.get("pending_approval", 0)

    # Autonomy rate (percentage of runs that were sent without escalation)
    sent_count = decisions.get("send", 0) + decisions.get("script_fallback", 0)
    autonomy_rate = (sent_count / total_agent_runs * 100) if total_agent_runs > 0 else 0

    # Average confidence
    avg_confidence_result = await db.execute(
        select(func.avg(AgentRun.confidence_score)).where(
            AgentRun.client_id == client_id if client_id else True,
            AgentRun.confidence_score != None,
        )
    )
    avg_confidence = avg_confidence_result.scalar() or 0.0

    # Average response time (duration_ms)
    avg_duration_result = await db.execute(
        select(func.avg(AgentRun.duration_ms)).where(
            AgentRun.client_id == client_id if client_id else True,
            AgentRun.duration_ms != None,
        )
    )
    avg_duration_ms = avg_duration_result.scalar() or 0

    # Total cost
    total_cost_result = await db.execute(
        select(func.sum(AgentRun.total_cost_cents)).where(
            AgentRun.client_id == client_id if client_id else True
        )
    )
    total_cost_cents = total_cost_result.scalar() or 0

    # Total tokens
    total_tokens_result = await db.execute(
        select(func.sum(AgentRun.total_tokens)).where(
            AgentRun.client_id == client_id if client_id else True
        )
    )
    total_tokens = total_tokens_result.scalar() or 0

    # Messages count
    total_messages_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.client_id == client_id if client_id else True
        )
    )
    total_messages = total_messages_result.scalar() or 0

    # Inbound vs outbound messages
    inbound_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.direction == "inbound",
            Message.client_id == client_id if client_id else True,
        )
    )
    inbound_messages = inbound_result.scalar() or 0

    outbound_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.direction == "outbound",
            Message.client_id == client_id if client_id else True,
        )
    )
    outbound_messages = outbound_result.scalar() or 0

    # Conversion rate
    converted = leads_by_status.get("converted", 0)
    conversion_rate = (converted / total_leads * 100) if total_leads > 0 else 0

    # Response rate (leads that got at least one outbound message)
    response_rate = ((total_leads - leads_by_status.get("new", 0)) / total_leads * 100) if total_leads > 0 else 0

    # Funnel data
    funnel = {
        "total_leads": total_leads,
        "engaged": total_leads - leads_by_status.get("new", 0),
        "qualified": leads_by_status.get("qualified", 0),
        "meeting_booked": leads_by_status.get("meeting_booked", 0),
        "converted": converted,
    }

    # Recent activity (last 7 days) — messages per day
    from datetime import datetime, UTC
    now = datetime.now(UTC)
    daily_activity = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        day_msgs = await db.execute(
            select(func.count(Message.id)).where(
                Message.created_at >= day_start,
                Message.created_at < day_end,
                Message.client_id == client_id if client_id else True,
            )
        )
        day_count = day_msgs.scalar() or 0
        
        daily_activity.append({
            "name": day.strftime("%a"),
            "messages": day_count,
            "day": day.strftime("%Y-%m-%d"),
        })

    return {
        "overview": {
            "total_leads": total_leads,
            "total_conversations": total_conversations,
            "active_conversations": active_conversations,
            "total_agent_runs": total_agent_runs,
            "total_messages": total_messages,
            "inbound_messages": inbound_messages,
            "outbound_messages": outbound_messages,
        },
        "performance": {
            "autonomy_rate": round(autonomy_rate, 1),
            "escalation_rate": round((escalated_count / total_agent_runs * 100) if total_agent_runs > 0 else 0, 1),
            "avg_confidence": round(avg_confidence, 2),
            "avg_response_time_ms": round(avg_duration_ms),
            "conversion_rate": round(conversion_rate, 1),
            "response_rate": round(response_rate, 1),
        },
        "costs": {
            "total_cost_cents": total_cost_cents,
            "total_cost_dollars": round(total_cost_cents / 100, 2),
            "total_tokens": total_tokens,
        },
        "funnel": funnel,
        "leads_by_status": leads_by_status,
        "decisions": decisions,
        "daily_activity": daily_activity,
    }
