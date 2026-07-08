"""Shares API Router — handles creating templates and cloning them."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_tenant_db
from app.models.client import Client
from app.models.share import AgentTemplate
from app.models.user import User

router = APIRouter(prefix="/shares", tags=["shares"])


class ShareRequest(BaseModel):
    client_id: uuid.UUID
    name: str
    description: str | None = None


class CloneRequest(BaseModel):
    template_id: uuid.UUID
    agency_id: uuid.UUID
    name: str


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_share_template(
    body: ShareRequest,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Publish a client's configuration as a shareable template."""
    client_res = await db.execute(select(Client).where(Client.id == body.client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    template = AgentTemplate(
        id=uuid.uuid4(),
        name=body.name,
        description=body.description,
        brand_voice=client.brand_voice,
        never_say_list=client.never_say_list,
        autonomy_config=client.autonomy_config,
    )

    db.add(template)
    await db.commit()
    await db.refresh(template)

    return {
        "status": "created",
        "template_id": str(template.id),
        "clone_url": f"https://operd.ai/templates/{template.id}/clone",
    }


@router.post("/clone", status_code=status.HTTP_201_CREATED)
async def clone_share_template(
    body: CloneRequest,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Clone an existing template into a new client workspace."""
    tmpl_res = await db.execute(select(AgentTemplate).where(AgentTemplate.id == body.template_id))
    template = tmpl_res.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    new_client = Client(
        id=uuid.uuid4(),
        agency_id=body.agency_id,
        business_name=body.name,
        slug=body.name.lower().replace(" ", "-"),
        brand_voice=template.brand_voice,
        never_say_list=template.never_say_list,
        autonomy_config=template.autonomy_config,
        kill_switch=False,
    )

    db.add(new_client)
    await db.commit()
    await db.refresh(new_client)

    return {
        "status": "cloned",
        "client_id": str(new_client.id),
        "name": new_client.business_name,
    }
