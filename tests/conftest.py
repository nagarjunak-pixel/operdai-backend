"""pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_client_config():
    """Standard client config for testing."""
    return {
        "business_name": "Acme Web Design",
        "slug": "acme-web",
        "brand_voice": {
            "tone": "friendly and professional",
            "style": "casual but informative",
            "examples": [
                "Hey! Great to hear from you.",
                "We'd love to help you with that!",
            ],
        },
        "never_say_list": {
            "phrases": ["guaranteed", "100%", "cheapest"],
            "topics": ["competitor pricing", "legal advice"],
        },
        "autonomy_config": {
            "mode": "full_auto",
            "confidence_threshold": 0.85,
            "high_risk_topics": ["pricing_negotiation", "refund", "legal"],
            "max_autonomous_messages_per_lead": 10,
        },
    }


@pytest.fixture
def sample_kb_facts():
    """Sample KB facts for testing."""
    from app.agents.schemas import KBFact
    return [
        KBFact(
            content="We offer three plans: Starter ($499/mo), Growth ($999/mo), and Enterprise (custom pricing).",
            source_title="Pricing FAQ",
            source_id="doc-pricing-001",
            relevance_score=0.95,
        ),
        KBFact(
            content="Our turnaround time is 2-4 weeks for a standard website redesign.",
            source_title="Services FAQ",
            source_id="doc-services-001",
            relevance_score=0.88,
        ),
    ]
