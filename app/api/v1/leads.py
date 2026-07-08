"""Leads API — CRUD, search, and status management for leads."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_tenant_db
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.user import User

router = APIRouter(prefix="/leads", tags=["leads"])


class LeadResponse(BaseModel):
    id: str
    client_id: str
    agency_id: str
    external_id: str | None = None
    source_channel: str
    status: str
    score: float | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class LeadStatusUpdate(BaseModel):
    status: str  # new, contacted, qualified, meeting_booked, converted, lost


@router.get("")
async def list_leads(
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
    client_id: uuid.UUID | None = None,
    status: str | None = None,
    min_score: float | None = None,
    search: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """List leads with filtering and search."""
    query = select(Lead).order_by(desc(Lead.created_at))

    if client_id:
        query = query.where(Lead.client_id == client_id)
    if status:
        query = query.where(Lead.status == status)
    if min_score is not None:
        query = query.where(Lead.score >= min_score)
    if search:
        query = query.where(
            or_(
                Lead.external_id.ilike(f"%{search}%"),
                Lead.metadata_.op("->>")("name").ilike(f"%{search}%"),
                Lead.metadata_.op("->>")("email").ilike(f"%{search}%"),
            )
        )

    # Count
    count_query = select(func.count(Lead.id))
    if client_id:
        count_query = count_query.where(Lead.client_id == client_id)
    if status:
        count_query = count_query.where(Lead.status == status)
    total = (await db.execute(count_query)).scalar()

    # Paginate
    result = await db.execute(query.limit(limit).offset(offset))
    leads = result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "leads": [
            {
                "id": str(lead.id),
                "client_id": str(lead.client_id),
                "agency_id": str(lead.agency_id),
                "external_id": lead.external_id,
                "source_channel": lead.source_channel,
                "status": lead.status,
                "score": lead.score,
                "metadata": lead.metadata_ or {},
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
                "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
            }
            for lead in leads
        ],
    }


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Get full lead details with conversations."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Get conversations
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.lead_id == lead_id)
        .order_by(desc(Conversation.updated_at))
    )
    conversations = conv_result.scalars().all()

    return {
        "id": str(lead.id),
        "client_id": str(lead.client_id),
        "agency_id": str(lead.agency_id),
        "external_id": lead.external_id,
        "source_channel": lead.source_channel,
        "status": lead.status,
        "score": lead.score,
        "metadata": lead.metadata_ or {},
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "conversations": [
            {
                "id": str(conv.id),
                "channel": conv.channel,
                "status": conv.status,
                "message_count": conv.message_count,
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            }
            for conv in conversations
        ],
    }


@router.patch("/{lead_id}/status")
async def update_lead_status(
    lead_id: uuid.UUID,
    body: LeadStatusUpdate,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Manually update a lead's status (for human override)."""
    valid_statuses = {"new", "contacted", "qualified", "meeting_booked", "converted", "lost"}
    if body.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    old_status = lead.status
    lead.status = body.status
    await db.commit()

    return {
        "id": str(lead.id),
        "status": lead.status,
        "previous_status": old_status,
    }


@router.get("/stats/summary")
async def lead_stats(
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
    client_id: uuid.UUID | None = None,
):
    """Get lead funnel stats — counts by status."""
    query = select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    if client_id:
        query = query.where(Lead.client_id == client_id)

    result = await db.execute(query)
    stats = {row[0]: row[1] for row in result.all()}

    total = sum(stats.values())
    return {
        "total": total,
        "by_status": stats,
        "conversion_rate": stats.get("converted", 0) / total if total > 0 else 0,
    }
