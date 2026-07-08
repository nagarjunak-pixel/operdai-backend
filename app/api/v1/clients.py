"""Client API routes — CRUD for client workspaces within an agency."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AgencyAdmin, CurrentUser, TenantDB
from app.models.client import Client
from app.schemas.core import AutonomyUpdate, ClientCreate, ClientResponse, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientResponse])
async def list_clients(token: CurrentUser, db: TenantDB):
    """List clients. Agency admins see all their clients. Client viewers see only their own."""
    if token.role == "client_viewer" and token.client_id:
        result = await db.execute(
            select(Client).where(Client.id == UUID(token.client_id))
        )
    else:
        result = await db.execute(
            select(Client)
            .where(Client.agency_id == UUID(token.agency_id))
            .order_by(Client.created_at.desc())
        )
    return result.scalars().all()


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(data: ClientCreate, token: AgencyAdmin, db: TenantDB):
    """Create a new client workspace. Agency admin only."""
    client = Client(
        agency_id=UUID(token.agency_id),
        business_name=data.business_name,
        slug=data.slug,
        brand_voice=data.brand_voice,
        never_say_list=data.never_say_list,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(client_id: UUID, token: CurrentUser, db: TenantDB):
    """Get client by ID."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(client_id: UUID, data: ClientUpdate, token: AgencyAdmin, db: TenantDB):
    """Update client settings. Agency admin only."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(client, field, value)
    await db.commit()
    await db.refresh(client)
    return client


@router.patch("/{client_id}/autonomy", response_model=ClientResponse)
async def update_autonomy(
    client_id: UUID, data: AutonomyUpdate, token: AgencyAdmin, db: TenantDB
):
    """Update client autonomy settings. Agency admin only."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    client.autonomy_config = {
        **client.autonomy_config,
        **data.model_dump(),
    }
    await db.commit()
    await db.refresh(client)
    return client


@router.post("/{client_id}/kill-switch", status_code=status.HTTP_200_OK)
async def activate_kill_switch(client_id: UUID, token: AgencyAdmin, db: TenantDB):
    """Activate kill switch — immediately stops all autonomous sending."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    client.kill_switch = True
    await db.commit()
    return {"status": "kill_switch_activated", "client_id": str(client_id)}


@router.delete("/{client_id}/kill-switch", status_code=status.HTTP_200_OK)
async def deactivate_kill_switch(client_id: UUID, token: AgencyAdmin, db: TenantDB):
    """Deactivate kill switch — re-enables autonomous sending."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    client.kill_switch = False
    await db.commit()
    return {"status": "kill_switch_deactivated", "client_id": str(client_id)}


@router.patch("/{client_id}/shadow-mode", status_code=status.HTTP_200_OK)
async def toggle_shadow_mode(client_id: UUID, token: AgencyAdmin, db: TenantDB):
    """Toggle shadow mode (draft-only, never sends)."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    client.shadow_mode = not client.shadow_mode
    await db.commit()
    return {"shadow_mode": client.shadow_mode, "client_id": str(client_id)}
