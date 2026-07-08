"""Qualifier agent — asks qualifying questions and scores leads."""

from app.agents.base import BaseAgent
from app.agents.schemas import QualifierInput, QualifierOutput
from app.config import settings


class QualifierAgent(BaseAgent):
    name = "qualifier"
    model = settings.llm_worker_model  # Haiku
    input_schema = QualifierInput
    output_schema = QualifierOutput
    temperature = 0.3

    system_prompt = """You are a lead qualification specialist for "{client_name}".

Your job is to evaluate inbound leads and determine their quality and readiness to buy.

QUALIFICATION CRITERIA:
{qualification_criteria}

INSTRUCTIONS:
1. Analyze the conversation history and any lead data provided.
2. Identify what information is still MISSING to properly qualify this lead.
3. Generate natural qualifying questions to gather that missing info.
   - Don't ask more than 2 questions at a time.
   - Make questions conversational, not interrogative.
4. Score the lead from 0.0 to 1.0 based on what you know so far:
   - 0.0-0.3: Cold — no clear intent, wrong fit, or unresponsive
   - 0.3-0.6: Warm — some interest but key info missing
   - 0.6-0.8: Hot — clear intent, matches ideal customer profile
   - 0.8-1.0: Ready — qualified, ready for meeting/demo/close
5. Set status:
   - "in_progress" if more info is needed
   - "qualified" if score >= 0.6 and key criteria are met
   - "not_qualified" if clearly not a fit

Return gathered_info as a structured dict of what you've learned about the lead.
"""

    def _build_system_prompt(self, **context):
        prompt = self.system_prompt
        prompt = prompt.replace("{client_name}", context.get("client_name", "the business"))
        criteria = context.get("qualification_criteria", [])
        if isinstance(criteria, list):
            criteria_str = "\n".join(f"  - {c}" for c in criteria) if criteria else "  - Budget, timeline, decision-maker status, specific needs"
        else:
            criteria_str = str(criteria)
        prompt = prompt.replace("{qualification_criteria}", criteria_str)
        return prompt
