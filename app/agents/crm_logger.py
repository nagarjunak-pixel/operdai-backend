"""CRM Logger agent — writes structured records of every interaction."""

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.config import settings


class CRMLogInput(BaseModel):
    lead_id: str
    conversation_id: str
    lead_message: str
    agent_response: str
    classifier_intent: str = ""
    classifier_urgency: str = ""
    qualification_score: float | None = None
    decision: str = ""  # send/escalate/draft
    confidence: float = 0.0
    conversation_history: list[dict] = Field(default_factory=list)


class CRMLogOutput(BaseModel):
    lead_status_update: str | None = None  # new/contacted/qualified/meeting_booked/converted/lost
    notes: str = ""  # Human-readable summary of the interaction
    tags: list[str] = Field(default_factory=list)  # Auto-generated tags
    follow_up_needed: bool = False
    next_action: str = ""  # What should happen next


class CRMLoggerAgent(BaseAgent):
    name = "crm_logger"
    model = settings.llm_worker_model
    input_schema = CRMLogInput
    output_schema = CRMLogOutput
    temperature = 0.2

    system_prompt = """You are a CRM logging assistant. Your job is to create structured
records from lead interactions.

For each interaction, you must produce:

1. **lead_status_update**: If the interaction warrants a status change, specify the new status:
   - "new" → first contact
   - "contacted" → we've replied at least once
   - "qualified" → lead has been scored and meets criteria
   - "meeting_booked" → a meeting has been scheduled
   - "converted" → lead became a customer
   - "lost" → lead is no longer interested or unresponsive
   Set to null if no status change is needed.

2. **notes**: A concise, human-readable summary of what happened in this interaction.
   Include: what the lead asked, what the agent said, and any key decisions made.
   Keep it to 2-3 sentences max.

3. **tags**: Auto-generate relevant tags for this interaction. Examples:
   - "pricing-inquiry", "booking-request", "complaint", "follow-up-needed"
   - "high-value", "urgent", "escalated", "first-contact"

4. **follow_up_needed**: true if the lead hasn't been fully served and needs follow-up.

5. **next_action**: What should happen next with this lead (e.g., "Send pricing details",
   "Schedule demo", "Manager review required", "No action needed").
"""
