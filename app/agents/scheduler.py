"""Scheduler agent — proposes and books calendar slots."""

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.config import settings


class SchedulerInput(BaseModel):
    lead_name: str | None = None
    lead_email: str | None = None
    lead_phone: str | None = None
    conversation_history: list[dict] = Field(default_factory=list)
    lead_message: str = ""
    available_slots: list[dict] = Field(default_factory=list)
    # [{"start": "2024-01-15T10:00:00", "end": "2024-01-15T10:30:00"}, ...]
    timezone: str = "UTC"
    meeting_duration_minutes: int = 30


class SchedulerOutput(BaseModel):
    should_propose_slots: bool = False
    proposed_message: str = ""
    selected_slot: dict | None = None  # If lead confirmed a specific time
    booking_confirmed: bool = False
    reasoning: str = ""


class SchedulerAgent(BaseAgent):
    name = "scheduler"
    model = settings.llm_worker_model
    input_schema = SchedulerInput
    output_schema = SchedulerOutput
    temperature = 0.3

    system_prompt = """You are a scheduling assistant for "{client_name}".

Your job is to help leads book a meeting/consultation.

AVAILABLE SLOTS:
{available_slots}

INSTRUCTIONS:
1. If the lead is asking to book a meeting, propose 2-3 available time slots
   in a friendly, conversational way.
2. If the lead has confirmed a specific time, set booking_confirmed=true and
   select the matching slot.
3. If no slots are available, apologize and ask for their preferred times.
4. Always mention the meeting duration ({duration} minutes).
5. Be considerate of timezone differences.
6. Use natural language — "How about Tuesday at 2pm?" not "Slot: 2024-01-15T14:00:00Z"

If there's no scheduling intent in the conversation, set should_propose_slots=false.
"""

    def _build_system_prompt(self, **context):
        import json
        prompt = self.system_prompt
        prompt = prompt.replace("{client_name}", context.get("client_name", "the business"))
        slots = context.get("available_slots", [])
        prompt = prompt.replace("{available_slots}", json.dumps(slots, indent=2) if slots else "No slots loaded yet")
        prompt = prompt.replace("{duration}", str(context.get("meeting_duration_minutes", 30)))
        return prompt
