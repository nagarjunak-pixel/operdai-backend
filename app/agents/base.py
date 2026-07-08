"""Base agent class — common interface for all specialist agents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.agents.llm import LLMProvider, LLMResponse, get_llm_provider
from app.agents.schemas import AgentStepResult


class BaseAgent:
    """
    Base class for all specialist agents.
    Each agent has a name, system prompt template, model binding,
    and input/output Pydantic schemas.
    """

    name: str = "base"
    system_prompt: str = ""
    model: str = ""  # Override in subclass
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None
    max_retries: int = 2
    temperature: float = 0.3

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm or get_llm_provider()

    def _build_system_prompt(self, **context: Any) -> str:
        """
        Build the system prompt with context substitution.
        Subclasses can override for more complex templating.
        """
        prompt = self.system_prompt
        for key, value in context.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))
        return prompt

    async def run(
        self,
        input_data: BaseModel | dict,
        context: dict[str, Any] | None = None,
    ) -> tuple[BaseModel | None, AgentStepResult]:
        """
        Execute the agent: send prompt to LLM, parse output, return result + trace.

        Returns:
            tuple of (parsed output or None, step result for tracing)
        """
        context = context or {}
        system = self._build_system_prompt(**context)

        # Build messages
        if isinstance(input_data, BaseModel):
            user_message = input_data.model_dump_json(indent=2)
        else:
            import json
            user_message = json.dumps(input_data, indent=2, default=str)

        messages = [{"role": "user", "content": user_message}]

        # Call LLM with retries
        response: LLMResponse | None = None
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.llm.complete(
                    messages=messages,
                    system=system,
                    output_schema=self.output_schema,
                    model=self.model,
                    temperature=self.temperature,
                )
                if response.parsed or not self.output_schema:
                    break  # Success
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    continue
                raise

        if response is None:
            raise RuntimeError(f"Agent {self.name} failed after {self.max_retries + 1} attempts")

        # Build trace step
        step = AgentStepResult(
            agent=self.name,
            input_data=input_data.model_dump() if isinstance(input_data, BaseModel) else input_data,
            output_data=response.parsed.model_dump() if response.parsed else {"raw": response.content},
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_cents=response.cost_cents,
            duration_ms=response.latency_ms,
            timestamp=datetime.now(UTC).isoformat(),
        )

        return response.parsed, step
