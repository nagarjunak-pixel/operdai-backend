"""AgentRun model — replayable trace of every agent pipeline execution."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id"), nullable=False, index=True
    )
    trigger_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    # running, completed, failed, escalated

    steps: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    # Ordered list of agent steps:
    # [
    #   {
    #     "agent": "classifier",
    #     "input": {...},
    #     "output": {...},
    #     "model": "claude-haiku-4-5",
    #     "tokens_in": 150, "tokens_out": 80,
    #     "cost_cents": 0.02,
    #     "duration_ms": 450,
    #     "timestamp": "2024-..."
    #   },
    #   ...
    # ]

    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # send, escalate, script_fallback, block

    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    policy_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    # ["high_risk_topic:pricing", "never_say_violation:guaranteed"]

    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.id} decision={self.decision} conf={self.confidence_score}>"
