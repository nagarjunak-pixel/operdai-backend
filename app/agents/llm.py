"""
LLM Abstraction Layer — swappable provider for Claude (and future models).

Design:
- LLMProvider protocol defines the interface.
- ClaudeProvider implements it using the Anthropic SDK.
- MockProvider for testing without API calls.
- All providers return a standardized LLMResponse.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.config import settings


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    parsed: BaseModel | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: float = 0.0
    model: str = ""
    latency_ms: int = 0
    raw_response: Any = None


# Cost per 1M tokens (input/output) — updated for Claude pricing
MODEL_COSTS = {
    "claude-opus-4-8": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
}


def _calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate cost in cents."""
    costs = MODEL_COSTS.get(model, {"input": 1.0, "output": 5.0})
    input_cost = (tokens_in / 1_000_000) * costs["input"] * 100  # dollars to cents
    output_cost = (tokens_out / 1_000_000) * costs["output"] * 100
    return round(input_cost + output_cost, 4)


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for LLM providers. Implement this to add new model backends."""

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        output_schema: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> LLMResponse: ...


class ClaudeProvider:
    """Claude API provider using the Anthropic SDK."""

    def __init__(self, api_key: str | None = None, default_model: str | None = None):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.default_model = default_model or settings.llm_worker_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        output_schema: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> LLMResponse:
        model = model or self.default_model
        start = time.monotonic()

        # Build the request
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        # If we want structured output, instruct the model to return JSON
        if output_schema:
            schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
            json_instruction = (
                f"\n\nYou MUST respond with valid JSON matching this schema:\n"
                f"```json\n{schema_json}\n```\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            if system:
                kwargs["system"] = system + json_instruction
            else:
                kwargs["system"] = json_instruction

        response = await self.client.messages.create(**kwargs)

        latency_ms = int((time.monotonic() - start) * 1000)

        content = response.content[0].text if response.content else ""
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        cost = _calculate_cost(model, tokens_in, tokens_out)

        # Try to parse structured output
        parsed = None
        if output_schema and content:
            try:
                # Strip markdown code blocks if present
                clean = content.strip()
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
                parsed = output_schema.model_validate_json(clean)
            except Exception:
                # If parsing fails, return raw content — caller decides what to do
                pass

        return LLMResponse(
            content=content,
            parsed=parsed,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cents=cost,
            model=model,
            latency_ms=latency_ms,
            raw_response=response,
        )


class MockProvider:
    """
    Mock LLM provider for testing.
    Returns configurable canned responses.
    """

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}
        self.call_log: list[dict] = []
        self.default_response = '{"intent": "inquiry", "urgency": "medium", "language": "en", "confidence": 0.92}'

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        output_schema: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> LLMResponse:
        self.call_log.append({
            "messages": messages,
            "system": system,
            "output_schema": output_schema.__name__ if output_schema else None,
            "model": model,
        })

        # Find a matching canned response
        content = self.default_response
        for key, response in self.responses.items():
            if key in system or any(key in m.get("content", "") for m in messages):
                content = response
                break

        parsed = None
        if output_schema and content:
            try:
                parsed = output_schema.model_validate_json(content)
            except Exception:
                pass

        return LLMResponse(
            content=content,
            parsed=parsed,
            tokens_in=100,
            tokens_out=50,
            cost_cents=0.01,
            model=model or "mock",
            latency_ms=5,
        )


# Singleton providers — instantiated lazily
_claude_provider: ClaudeProvider | None = None
_mock_provider: MockProvider | None = None


def get_llm_provider(mock: bool = False) -> LLMProvider:
    """Get the LLM provider (Claude in production, Mock in tests)."""
    global _claude_provider, _mock_provider

    if mock or settings.environment == "test":
        if _mock_provider is None:
            _mock_provider = MockProvider()
        return _mock_provider

    if _claude_provider is None:
        _claude_provider = ClaudeProvider()
    return _claude_provider


def get_mock_provider(responses: dict[str, str] | None = None) -> MockProvider:
    """Get a fresh mock provider with custom responses."""
    return MockProvider(responses=responses)
