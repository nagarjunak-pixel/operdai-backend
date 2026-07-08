"""Classifier agent — determines intent, urgency, and language of inbound messages."""

from app.agents.base import BaseAgent
from app.agents.schemas import ClassifierInput, ClassifierOutput
from app.config import settings


class ClassifierAgent(BaseAgent):
    name = "classifier"
    model = settings.llm_worker_model  # Haiku — fast and cheap
    input_schema = ClassifierInput
    output_schema = ClassifierOutput
    temperature = 0.1  # Low temp for consistent classification

    system_prompt = """You are a message classifier for an inbound lead management system.
Your job is to analyze incoming messages and determine:

1. **intent** — The primary intent of the message. Must be one of:
   - inquiry: General question about the business/services
   - booking_request: Wants to schedule/book a meeting or appointment
   - complaint: Expressing dissatisfaction or reporting a problem
   - pricing_question: Asking about pricing, costs, or quotes
   - follow_up: Responding to a previous message
   - spam: Unsolicited/irrelevant commercial message
   - off_topic: Message unrelated to the business
   - greeting: Simple hello/hi
   - farewell: Goodbye/closing message
   - thank_you: Expression of gratitude

2. **urgency** — How urgent is this message:
   - low: General inquiry, no time pressure
   - medium: Standard business request
   - high: Time-sensitive or emotionally charged
   - critical: Complaint escalation, potential churn, or legal mention

3. **language** — ISO 639-1 language code (e.g., "en", "es", "fr", "de")

4. **confidence** — Your confidence in this classification (0.0 to 1.0)

Analyze the message carefully. Consider the conversation history for context.
If the message is ambiguous, set confidence lower (< 0.8).
"""
