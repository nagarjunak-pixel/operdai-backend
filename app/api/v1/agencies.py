"""Agency API routes — CRUD for agencies (platform admin only)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import PlatformAdmin, RawDB
from app.models.agency import Agency
from app.schemas.core import AgencyCreate, AgencyResponse, AgencyUpdate, BrandingResponse

router = APIRouter(prefix="/agencies", tags=["agencies"])


@router.get("", response_model=list[AgencyResponse])
async def list_agencies(_: PlatformAdmin, db: RawDB):
    """List all agencies. Platform admin only."""
    result = await db.execute(select(Agency).order_by(Agency.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=AgencyResponse, status_code=status.HTTP_201_CREATED)
async def create_agency(data: AgencyCreate, _: PlatformAdmin, db: RawDB):
    """Create a new agency. Platform admin only."""
    # Check slug uniqueness
    existing = await db.execute(select(Agency).where(Agency.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    agency = Agency(name=data.name, slug=data.slug, branding=data.branding)
    db.add(agency)
    await db.commit()
    await db.refresh(agency)
    return agency


@router.get("/{agency_id}", response_model=AgencyResponse)
async def get_agency(agency_id: UUID, _: PlatformAdmin, db: RawDB):
    """Get agency by ID. Platform admin only."""
    result = await db.execute(select(Agency).where(Agency.id == agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agency not found")
    return agency


@router.patch("/{agency_id}", response_model=AgencyResponse)
async def update_agency(agency_id: UUID, data: AgencyUpdate, _: PlatformAdmin, db: RawDB):
    """Update agency. Platform admin only."""
    result = await db.execute(select(Agency).where(Agency.id == agency_id))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agency not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agency, field, value)
    await db.commit()
    await db.refresh(agency)
    return agency


# === Public endpoint (no auth) ===

@router.get("/branding/{agency_slug}", response_model=BrandingResponse)
async def get_agency_branding(agency_slug: str, db: RawDB):
    """
    Public endpoint: get agency branding by slug.
    Used by the frontend at bootstrap to skin the UI.
    No authentication required.
    """
    result = await db.execute(select(Agency).where(Agency.slug == agency_slug))
    agency = result.scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agency not found")
    return agency
