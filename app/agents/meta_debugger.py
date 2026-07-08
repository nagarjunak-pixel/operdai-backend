"""
Meta-Debugger Agent — analyzes agent failures/critic rejections and generates self-healing instructions.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.agents.llm import LLMProvider
from app.agents.schemas import AgentStepResult


class DebuggerInput(BaseModel):
    original_prompt: str
    draft_message: str
    critic_feedback: str
    conversation_history: list[dict]


class DebuggerOutput(BaseModel):
    reasoning: str = Field(description="Analysis of why the draft failed the critic or safety check.")
    instruction_override: str = Field(description="Dynamic prompt instruction injection to heal the response.")
    approved_for_retry: bool = Field(description="Whether the self-healing instruction is ready for re-execution.")


class MetaDebuggerAgent(BaseAgent):
    name: str = "meta_debugger"
    model: str = "claude-3-haiku"
    output_schema: type[BaseModel] | None = DebuggerOutput

    system_prompt: str = (
        "You are the Meta-Debugger Agent for OperdAI.\n"
        "Your job is to analyze why a draft response failed a critic or safety check (e.g., grounding violation, never-say word, tone violation).\n"
        "You must output a structured JSON plan detailing why the response failed and a dynamic prompt override "
        "that will guide the Responder Agent to produce a clean, valid response in its retry attempt."
    )

    async def run(
        self,
        input_data: DebuggerInput | dict,
        context: dict[str, Any] | None = None,
    ) -> tuple[DebuggerOutput | None, AgentStepResult]:
        """Runs the Meta-Debugger to analyze safety issues and patch system prompts."""
        if isinstance(input_data, dict):
            input_data = DebuggerInput(**input_data)

        output, step = await super().run(input_data, context)
        return output, step
