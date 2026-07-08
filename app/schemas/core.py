"""Pydantic schemas for agencies, clients, leads, and common responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# === Agency Schemas ===

class AgencyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    branding: dict = Field(default_factory=dict)


class AgencyUpdate(BaseModel):
    name: str | None = None
    branding: dict | None = None
    custom_domain: str | None = None
    is_active: bool | None = None


class AgencyResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    custom_domain: str | None
    branding: dict
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BrandingResponse(BaseModel):
    """Public branding config — no auth required."""
    name: str
    slug: str
    branding: dict

    model_config = {"from_attributes": True}


# === Client Schemas ===

class ClientCreate(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    brand_voice: dict = Field(default_factory=dict)
    never_say_list: dict = Field(default_factory=dict)


class ClientUpdate(BaseModel):
    business_name: str | None = None
    brand_voice: dict | None = None
    never_say_list: dict | None = None
    autonomy_config: dict | None = None
    channel_config: dict | None = None
    safe_scripts: dict | None = None
    is_active: bool | None = None


class ClientResponse(BaseModel):
    id: UUID
    agency_id: UUID
    business_name: str
    slug: str
    brand_voice: dict
    never_say_list: dict
    autonomy_config: dict
    kill_switch: bool
    shadow_mode: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AutonomyUpdate(BaseModel):
    mode: str = Field(..., pattern=r"^(full_auto|auto_with_approval|suggest_only)$")
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    high_risk_topics: list[str] = Field(default_factory=list)
    max_autonomous_messages_per_lead: int = Field(default=10, ge=1)


# === Lead Schemas ===

class LeadResponse(BaseModel):
    id: UUID
    client_id: UUID
    agency_id: UUID
    source_channel: str
    external_id: str
    name: str | None
    email: str | None
    phone: str | None
    qualification_score: float | None
    status: str
    created_at: datetime
    last_activity_at: datetime

    model_config = {"from_attributes": True}


# === Webhook Schemas ===

class WebFormLead(BaseModel):
    """Generic web form submission."""
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    message: str
    source: str = "web_form"
    metadata: dict = Field(default_factory=dict)


# === Common ===

class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    environment: str


# === Knowledge Base Schemas ===

class KBDocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    doc_type: str = Field(default="general", max_length=50)
    source_url: str | None = Field(default=None, max_length=2000)


class KBDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    content: str | None = None
    doc_type: str | None = Field(default=None, max_length=50)
    source_url: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class KBDocumentResponse(BaseModel):
    id: UUID
    client_id: UUID
    agency_id: UUID
    title: str
    content: str
    doc_type: str
    source_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

