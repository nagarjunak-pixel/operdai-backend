"""Tests for the LLM abstraction layer and agent base class."""

import pytest

from app.agents.classifier import ClassifierAgent
from app.agents.llm import LLMResponse, MockProvider, _calculate_cost
from app.agents.responder import ResponderAgent
from app.agents.schemas import ClassifierInput, ClassifierOutput


class TestMockProvider:
    """Test the mock LLM provider."""

    @pytest.mark.asyncio
    async def test_mock_returns_response(self):
        provider = MockProvider()
        response = await provider.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system="You are a test agent",
        )
        assert isinstance(response, LLMResponse)
        assert response.content != ""
        assert response.model == "mock"

    @pytest.mark.asyncio
    async def test_mock_with_structured_output(self):
        provider = MockProvider(responses={
            "classifier": '{"intent": "greeting", "urgency": "low", "language": "en", "confidence": 0.95}'
        })
        response = await provider.complete(
            messages=[{"role": "user", "content": "Hi there!"}],
            system="You are a classifier",
            output_schema=ClassifierOutput,
        )
        assert response.parsed is not None
        assert response.parsed.intent == "greeting"
        assert response.parsed.confidence == 0.95

    @pytest.mark.asyncio
    async def test_mock_logs_calls(self):
        provider = MockProvider()
        await provider.complete(
            messages=[{"role": "user", "content": "test"}],
            system="test system",
        )
        assert len(provider.call_log) == 1
        assert provider.call_log[0]["system"] == "test system"

    @pytest.mark.asyncio
    async def test_mock_canned_responses(self):
        provider = MockProvider(responses={
            "booking": '{"intent": "booking_request", "urgency": "high", "language": "en", "confidence": 0.88}'
        })
        response = await provider.complete(
            messages=[{"role": "user", "content": "I want to book a meeting"}],
            system="booking classifier",
            output_schema=ClassifierOutput,
        )
        assert response.parsed.intent == "booking_request"


class TestCostCalculation:
    """Test token cost calculation."""

    def test_haiku_cost(self):
        cost = _calculate_cost("claude-haiku-4-5", 1000, 500)
        assert cost > 0
        assert cost < 1  # Should be very cheap

    def test_opus_cost(self):
        cost = _calculate_cost("claude-opus-4-8", 1000, 500)
        assert cost > 0
        # Opus should be more expensive than Haiku
        haiku_cost = _calculate_cost("claude-haiku-4-5", 1000, 500)
        assert cost > haiku_cost

    def test_unknown_model_has_default_cost(self):
        cost = _calculate_cost("unknown-model", 1000, 500)
        assert cost > 0


class TestClassifierAgent:
    """Test the classifier agent."""

    @pytest.mark.asyncio
    async def test_classifier_returns_structured_output(self):
        mock = MockProvider(responses={
            "classifier": '{"intent": "inquiry", "urgency": "medium", "language": "en", "confidence": 0.9}'
        })
        agent = ClassifierAgent(llm=mock)
        input_data = ClassifierInput(
            message="What services do you offer?",
            conversation_history=[],
        )
        output, step = await agent.run(input_data)
        assert output is not None
        assert output.intent == "inquiry"
        assert step.agent == "classifier"
        assert step.tokens_in > 0

    @pytest.mark.asyncio
    async def test_classifier_handles_greeting(self):
        mock = MockProvider(responses={
            "classifier": '{"intent": "greeting", "urgency": "low", "language": "en", "confidence": 0.95}'
        })
        agent = ClassifierAgent(llm=mock)
        input_data = ClassifierInput(message="Hello!", conversation_history=[])
        output, step = await agent.run(input_data)
        assert output.intent == "greeting"
        assert output.confidence == 0.95


class TestResponderAgent:
    """Test the responder agent."""

    @pytest.mark.asyncio
    async def test_responder_drafts_reply(self):
        mock = MockProvider(responses={
            "response drafter": '{"message": "Thanks for reaching out! We offer web design and marketing services.", "tone_match_score": 0.85, "grounding_refs": [], "reasoning": "Answered the inquiry"}'
        })
        agent = ResponderAgent(llm=mock)
        from app.agents.schemas import ClassifierOutput, ResponderInput
        input_data = ResponderInput(
            conversation_history=[],
            lead_message="What do you do?",
            classifier_output=ClassifierOutput(
                intent="inquiry", urgency="medium", language="en", confidence=0.9
            ),
            brand_voice={"tone": "friendly", "style": "casual"},
            client_name="Acme Co",
        )
        output, step = await agent.run(
            input_data,
            context={"client_name": "Acme Co", "brand_voice": {"tone": "friendly"}},
        )
        assert output is not None
        assert len(output.message) > 0
        assert step.agent == "responder"
