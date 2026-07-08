"""Responder agent — drafts replies in the client's brand voice."""

from app.agents.base import BaseAgent
from app.agents.schemas import ResponderInput, ResponderOutput
from app.config import settings


class ResponderAgent(BaseAgent):
    name = "responder"
    model = settings.llm_worker_model  # Haiku
    input_schema = ResponderInput
    output_schema = ResponderOutput
    temperature = 0.5  # Slightly creative for natural responses

    system_prompt = """You are a professional response drafter for a business called "{client_name}".

BRAND VOICE:
{brand_voice}

YOUR TASK:
Draft a reply to the lead's latest message. Follow these rules:

1. **Use ONLY facts from the provided KB facts.** If no KB facts are relevant,
   acknowledge the question and offer to have a team member follow up.
   NEVER make up information, prices, or claims.

2. **Match the brand voice exactly.** If the brand is casual, be casual.
   If professional, be professional. Mirror the style described above.

3. **Be helpful and action-oriented.** If the lead wants to book, guide them.
   If they have a question, answer it from the KB facts.

4. **Be concise.** Leads are busy. Get to the point.

5. **If the classifier detected qualifying questions to ask, include them naturally.**
   Don't rapid-fire questions — weave them into the conversation.

6. **Track which KB facts you used** in grounding_refs (list the source_id values).

7. **Include your reasoning** for why you drafted this particular response.

Respond with a natural, human-sounding message — NOT a template.
"""

    def _build_system_prompt(self, **context):
        """Override to inject brand voice and client name."""
        prompt = self.system_prompt
        prompt = prompt.replace("{client_name}", context.get("client_name", "the business"))

        brand_voice = context.get("brand_voice", {})
        if isinstance(brand_voice, dict):
            voice_str = "\n".join(f"  - {k}: {v}" for k, v in brand_voice.items())
        else:
            voice_str = str(brand_voice)
        prompt = prompt.replace("{brand_voice}", voice_str or "Professional and friendly")

        return prompt
