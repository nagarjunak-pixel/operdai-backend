"""
Critic agent — the safety gate before any message is sent.

Verifies:
1. Brand voice compliance
2. "Never say" list enforcement
3. Factual grounding (did the claim come from the KB?)
4. Policy compliance (no ungrounded claims, no risky content)

This agent uses Opus for maximum quality — it's the trust layer.
"""

from app.agents.base import BaseAgent
from app.agents.schemas import CriticInput, CriticOutput
from app.config import settings


class CriticAgent(BaseAgent):
    name = "critic"
    model = settings.llm_critic_model  # Opus — quality-critical
    input_schema = CriticInput
    output_schema = CriticOutput
    temperature = 0.1  # Very low — we want consistency in safety checks
    max_retries = 1  # Critic failures should fail fast

    system_prompt = """You are the quality and safety verifier for an AI agent system.
A draft message is about to be sent to a lead. Your job is to VERIFY it meets
all quality and safety standards BEFORE it goes out.

BRAND VOICE GUIDELINES:
{brand_voice}

"NEVER SAY" LIST (BLOCKED CONTENT):
{never_say_list}

KNOWN FACTS FROM KNOWLEDGE BASE:
{kb_facts}

VERIFICATION CHECKLIST — check EVERY item:

1. **GROUNDING CHECK** (most critical):
   - Does the draft make ANY claims about pricing, features, timelines, or policies?
   - If YES: Is EVERY claim supported by a fact from the KB above?
   - If a claim is NOT in the KB, mark it as an issue with type="ungrounded_claim"
     and severity="critical".
   - Responding with "I'll have our team get back to you" is ALWAYS safe.

2. **NEVER SAY CHECK**:
   - Does the draft contain any phrase from the never-say list?
   - Does it touch any topic in the never-say list?
   - If YES, mark as type="never_say_violation", severity="critical".

3. **BRAND VOICE CHECK**:
   - Does the tone match the brand voice guidelines?
   - Is it too formal when it should be casual, or vice versa?
   - If mismatch, mark as type="tone_mismatch", severity="medium".

4. **POLICY CHECK**:
   - Does it make any guarantees, promises, or commitments the business can't control?
   - Does it discuss competitors negatively?
   - Does it touch legal, medical, or financial advice?
   - If YES, mark as type="policy_violation", severity="high" or "critical".

DECISION:
- Set approved=true ONLY if there are ZERO critical or high-severity issues.
- Set confidence based on how certain you are in your assessment.
- If in doubt, set approved=false — it's safer to escalate than to send a bad message.

Be thorough. A wrong message sent to a lead damages the agency's client relationship.
"""

    def _build_system_prompt(self, **context):
        import json
        prompt = self.system_prompt

        brand_voice = context.get("brand_voice", {})
        if isinstance(brand_voice, dict):
            voice_str = json.dumps(brand_voice, indent=2)
        else:
            voice_str = str(brand_voice)
        prompt = prompt.replace("{brand_voice}", voice_str or "Professional and friendly")

        never_say = context.get("never_say_list", {})
        if isinstance(never_say, dict):
            never_str = json.dumps(never_say, indent=2)
        else:
            never_str = str(never_say)
        prompt = prompt.replace("{never_say_list}", never_str or "None specified")

        kb_facts = context.get("kb_facts", [])
        if isinstance(kb_facts, list):
            facts_str = json.dumps(kb_facts, indent=2, default=str)
        else:
            facts_str = str(kb_facts)
        prompt = prompt.replace("{kb_facts}", facts_str or "No KB facts available")

        return prompt
