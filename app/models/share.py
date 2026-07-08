"""AgentTemplate model for sharing and cloning agent configurations."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentTemplate(Base):
    __tablename__ = "agent_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    brand_voice: Mapped[dict] = mapped_column(JSON, default=dict)
    never_say_list: Mapped[dict] = mapped_column(JSON, default=dict)
    autonomy_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
