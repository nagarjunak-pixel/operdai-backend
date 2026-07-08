"""Agency model — our direct customer (the agency that resells to their clients)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Agency(Base):
    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # branding schema: {logo_url, favicon_url, primary_color, secondary_color,
    #   accent_color, font_family, email_from_name, email_from_address}

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    clients = relationship("Client", back_populates="agency", lazy="selectin")
    users = relationship("User", back_populates="agency", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Agency {self.name} ({self.slug})>"
