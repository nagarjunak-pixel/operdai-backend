"""Agent-to-Agent Negotiation Service — allows autonomous client agents to negotiate directly."""

from __future__ import annotations

import json
import logging
import uuid
from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.llm import LLMProvider, get_llm_provider
from app.agents.schemas import AgentStepResult

logger = logging.getLogger("operdai.negotiation")


class NegotiationTurnInput(BaseModel):
    opponent_brand_voice: str
    topic: str
    chat_history: list[dict]


class NegotiationTurnOutput(BaseModel):
    reasoning: str = Field(description="Internal decision logic of the negotiator.")
    counter_proposal: str = Field(description="Message response to transmit back to the opponent agent.")
    agreed: bool = Field(description="Set to true if opponent's terms are fully acceptable.")


class NegotiatorAgent(BaseAgent):
    name: str = "negotiator"
    model: str = "claude-3-haiku"
    output_schema: type[BaseModel] | None = NegotiationTurnOutput

    system_prompt: str = (
        "You are an Autonomous Negotiator Agent. Your task is to communicate with another company's agent "
        "and reach a mutually beneficial agreement regarding: {topic}.\n"
        "Be friendly but professional, protecting your business guidelines: {brand_voice}."
    )

    async def run(
        self,
        input_data: NegotiationTurnInput | dict,
        context: dict[str, Any] | None = None,
    ) -> tuple[NegotiationTurnOutput | None, AgentStepResult]:
        if isinstance(input_data, dict):
            input_data = NegotiationTurnInput(**input_data)
        return await super().run(input_data, context)


async def run_agent_negotiation(
    client_a_id: uuid.UUID,
    client_b_id: uuid.UUID,
    topic: str,
    rounds: int = 3,
    llm: LLMProvider | None = None,
) -> dict:
    """Orchestrates an autonomous conversation loop between two business agents."""
    llm = llm or get_llm_provider(mock=True)

    agent_a = NegotiatorAgent(llm=llm)
    agent_b = NegotiatorAgent(llm=llm)

    history = []
    status_state = "negotiating"

    # Simulated brand guide voices
    voice_a = "High quality services, standard turnaround 3 weeks."
    voice_b = "Growth startup, budget constraints, needs delivery in 2 weeks."

    for r in range(rounds):
        # 1. Agent A turn
        inp_a = NegotiationTurnInput(
            opponent_brand_voice=voice_b,
            topic=topic,
            chat_history=history,
        )
        out_a, _ = await agent_a.run(inp_a, context={"topic": topic, "brand_voice": voice_a})
        
        if not out_a:
            out_a = NegotiationTurnOutput(
                reasoning="Fallback",
                counter_proposal="Let us agree on standard terms.",
                agreed=False
            )

        history.append({"role": "Agent A", "content": out_a.counter_proposal})

        if out_a.agreed:
            status_state = "agreed"
            break

        # 2. Agent B turn
        inp_b = NegotiationTurnInput(
            opponent_brand_voice=voice_a,
            topic=topic,
            chat_history=history,
        )
        out_b, _ = await agent_b.run(inp_b, context={"topic": topic, "brand_voice": voice_b})
        
        if not out_b:
            out_b = NegotiationTurnOutput(
                reasoning="Fallback",
                counter_proposal="Agreeing to standard pricing.",
                agreed=True
            )

        history.append({"role": "Agent B", "content": out_b.counter_proposal})

        if out_b.agreed:
            status_state = "agreed"
            break

    return {
        "status": status_state,
        "topic": topic,
        "rounds_completed": len(history) // 2,
        "history": history,
    }
