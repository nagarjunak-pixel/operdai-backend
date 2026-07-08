"""Follow-up agent — re-engages non-responsive leads on a configurable cadence."""

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.config import settings


class FollowUpInput(BaseModel):
    lead_name: str | None = None
    lead_message: str = ""  # Their last message
    agent_last_response: str = ""  # Our last response
    hours_since_last_contact: float = 0.0
    follow_up_step: int = 1  # Which follow-up attempt (1st, 2nd, 3rd...)
    max_follow_ups: int = 3
    cadence_delays_hours: list[float] = Field(default_factory=lambda: [4, 24, 72])
    conversation_history: list[dict] = Field(default_factory=list)
    brand_voice: dict = Field(default_factory=dict)
    client_name: str = ""


class FollowUpOutput(BaseModel):
    should_follow_up: bool = False
    message: str = ""
    schedule_hours_from_now: float | None = None  # When to send the follow-up
    is_final_follow_up: bool = False  # Last attempt before giving up
    reasoning: str = ""


class FollowUpAgent(BaseAgent):
    name = "follow_up"
    model = settings.llm_worker_model
    input_schema = FollowUpInput
    output_schema = FollowUpOutput
    temperature = 0.5

    system_prompt = """You are a follow-up specialist for "{client_name}".

A lead has gone silent after a previous interaction. Your job is to draft a
natural, non-pushy follow-up message to re-engage them.

BRAND VOICE:
{brand_voice}

RULES:
1. This is follow-up attempt #{follow_up_step} of {max_follow_ups} maximum.
2. Each follow-up should be DIFFERENT from the last. Don't repeat yourself.
3. Progressively add more value in each follow-up:
   - Follow-up 1: Gentle check-in, reference their original question
   - Follow-up 2: Add value (share a relevant tip, resource, or offer)
   - Follow-up 3: Final attempt — direct ask, offer alternative contact method
4. Keep it SHORT (2-3 sentences max).
5. Never be aggressive, guilt-tripping, or desperate.
6. If follow_up_step > max_follow_ups, set should_follow_up=false.

CONTEXT:
- Lead's last message: {lead_message}
- Our last response: {agent_last_response}
- Hours since last contact: {hours_since_last_contact}
"""

    def _build_system_prompt(self, **context):
        prompt = self.system_prompt
        prompt = prompt.replace("{client_name}", context.get("client_name", "the business"))

        brand_voice = context.get("brand_voice", {})
        if isinstance(brand_voice, dict):
            voice_str = "\n".join(f"  - {k}: {v}" for k, v in brand_voice.items())
        else:
            voice_str = str(brand_voice)
        prompt = prompt.replace("{brand_voice}", voice_str or "Professional and friendly")

        prompt = prompt.replace("{follow_up_step}", str(context.get("follow_up_step", 1)))
        prompt = prompt.replace("{max_follow_ups}", str(context.get("max_follow_ups", 3)))
        prompt = prompt.replace("{lead_message}", context.get("lead_message", "N/A"))
        prompt = prompt.replace("{agent_last_response}", context.get("agent_last_response", "N/A"))
        prompt = prompt.replace("{hours_since_last_contact}", str(context.get("hours_since_last_contact", 0)))
        return prompt
