"""Integrations API Router — manages third-party platform connections."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_tenant_db
from app.models.integration import Integration
from app.models.user import User

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationToggleRequest(BaseModel):
    client_id: uuid.UUID
    platform: str  # shopify, slack, hubspot
    is_active: bool
    credentials: dict | None = None


@router.get("")
async def list_integrations(
    client_id: uuid.UUID,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Retrieve all active integrations for the client workspace."""
    stmt = select(Integration).where(Integration.client_id == client_id)
    res = await db.execute(stmt)
    integrations = res.scalars().all()
    return integrations


@router.post("/toggle")
async def toggle_integration(
    body: IntegrationToggleRequest,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Connect, disconnect, or configure a platform integration."""
    stmt = select(Integration).where(
        Integration.client_id == body.client_id,
        Integration.platform == body.platform,
    )
    res = await db.execute(stmt)
    integration = res.scalar_one_or_none()

    if not integration:
        # Create new integration entry
        integration = Integration(
            id=uuid.uuid4(),
            client_id=body.client_id,
            platform=body.platform,
            is_active=body.is_active,
            credentials=body.credentials or {},
        )
        db.add(integration)
    else:
        integration.is_active = body.is_active
        if body.credentials is not None:
            integration.credentials = body.credentials
        db.add(integration)

    await db.commit()
    await db.refresh(integration)

    return {
        "status": "updated",
        "platform": integration.platform,
        "is_active": integration.is_active,
    }
