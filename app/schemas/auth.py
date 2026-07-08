"""Auth Pydantic schemas — request/response models for authentication."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default="agency_member")
    agency_id: UUID | None = None
    client_id: UUID | None = None


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenRefresh(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    agency_id: UUID | None
    client_id: UUID | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenPayload(BaseModel):
    """Internal representation of JWT claims."""
    sub: str  # user_id
    role: str | None = None
    agency_id: str | None = None
    client_id: str | None = None
    exp: int
    type: str  # access or refresh
