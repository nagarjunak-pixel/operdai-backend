"""Client model — the agency's customer (the business that receives leads)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id"), nullable=False, index=True
    )
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Agent behavior config
    brand_voice: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {tone: "friendly", style: "professional", examples: [...]}

    never_say_list: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {phrases: ["guaranteed", "100%"], topics: ["competitor X pricing"]}

    autonomy_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "mode": "suggest_only",  # Start safe: suggest_only
            "confidence_threshold": 0.85,
            "high_risk_topics": ["pricing_negotiation", "refund", "legal", "medical"],
            "max_autonomous_messages_per_lead": 10,
            "follow_up_cadence": {"delays_hours": [4, 24, 72], "max_follow_ups": 3},
        },
    )

    # Safety controls
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False, insert_default=False)
    shadow_mode: Mapped[bool] = mapped_column(Boolean, default=True, insert_default=True)  # Start in shadow

    # Channel config
    channel_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    calendar_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Safe script fallback messages
    safe_scripts: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "greeting_fallback": "Hi! Thanks for reaching out. Let me connect you with someone from our team who can help you right away.",
            "pricing_fallback": "Great question about pricing! I want to make sure you get the most accurate information. Let me have our team get back to you with details.",
            "off_topic_fallback": "Thanks for your message! That's outside what I can help with, but I'll pass this along to our team.",
        },
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agency = relationship("Agency", back_populates="clients")
    leads = relationship("Lead", back_populates="client", lazy="selectin")
    kb_documents = relationship("KBDocument", back_populates="client", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Client {self.business_name} (agency={self.agency_id})>"
