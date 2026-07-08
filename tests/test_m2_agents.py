"""Tests for M2 agents — Qualifier, KB Agent, Scheduler, CRM Logger, Follow-up, Critic."""

import pytest

from app.agents.llm import MockProvider
from app.agents.schemas import ClassifierOutput, KBFact


class TestQualifierAgent:
    """Test the qualifier agent."""

    @pytest.mark.asyncio
    async def test_qualifier_scores_lead(self):
        from app.agents.qualifier import QualifierAgent
        from app.agents.schemas import QualifierInput

        mock = MockProvider(responses={
            "qualification specialist": '{"lead_score": 0.72, "questions_to_ask": ["What is your budget range?", "When are you looking to start?"], "gathered_info": {"intent": "inquiry"}, "status": "in_progress"}'
        })
        agent = QualifierAgent(llm=mock)
        input_data = QualifierInput(
            lead_data={"source_channel": "web_form", "intent": "inquiry"},
            conversation_history=[{"role": "lead", "content": "I need a new website"}],
            qualification_criteria=["Budget", "Timeline", "Decision-maker"],
        )
        output, step = await agent.run(
            input_data,
            context={"client_name": "Acme", "qualification_criteria": ["Budget", "Timeline"]},
        )
        assert output is not None
        assert 0 <= output.lead_score <= 1
        assert step.agent == "qualifier"

    @pytest.mark.asyncio
    async def test_qualifier_generates_questions(self):
        from app.agents.qualifier import QualifierAgent
        from app.agents.schemas import QualifierInput

        mock = MockProvider(responses={
            "qualification specialist": '{"lead_score": 0.45, "questions_to_ask": ["What is your monthly budget?"], "gathered_info": {}, "status": "in_progress"}'
        })
        agent = QualifierAgent(llm=mock)
        input_data = QualifierInput(
            lead_data={}, conversation_history=[], qualification_criteria=[],
        )
        output, step = await agent.run(
            input_data,
            context={"client_name": "Test Co", "qualification_criteria": []},
        )
        assert output is not None
        assert len(output.questions_to_ask) > 0


class TestSchedulerAgent:
    """Test the scheduler agent."""

    @pytest.mark.asyncio
    async def test_scheduler_proposes_slots(self):
        from app.agents.scheduler import SchedulerAgent, SchedulerInput

        mock = MockProvider(responses={
            "scheduling assistant": '{"should_propose_slots": true, "proposed_message": "How about Tuesday at 2pm or Wednesday at 10am?", "selected_slot": null, "booking_confirmed": false, "reasoning": "Lead wants to meet"}'
        })
        agent = SchedulerAgent(llm=mock)
        input_data = SchedulerInput(
            lead_message="I want to book a meeting",
            conversation_history=[],
            available_slots=[],
        )
        output, step = await agent.run(
            input_data,
            context={"client_name": "Acme", "available_slots": [], "meeting_duration_minutes": 30},
        )
        assert output is not None
        assert output.should_propose_slots is True
        assert len(output.proposed_message) > 0


class TestCRMLoggerAgent:
    """Test the CRM logger agent."""

    @pytest.mark.asyncio
    async def test_crm_logger_creates_record(self):
        from app.agents.crm_logger import CRMLoggerAgent, CRMLogInput

        mock = MockProvider(responses={
            "CRM logging": '{"lead_status_update": "contacted", "notes": "Lead inquired about web design services. Agent provided pricing info.", "tags": ["inquiry", "pricing", "first-contact"], "follow_up_needed": true, "next_action": "Send detailed pricing document"}'
        })
        agent = CRMLoggerAgent(llm=mock)
        input_data = CRMLogInput(
            lead_id="lead-1",
            conversation_id="conv-1",
            lead_message="What do you charge for a website?",
            agent_response="Our plans start at $499/mo. Want to learn more?",
            classifier_intent="pricing_question",
            classifier_urgency="medium",
        )
        output, step = await agent.run(input_data)
        assert output is not None
        assert output.lead_status_update == "contacted"
        assert len(output.tags) > 0
        assert step.agent == "crm_logger"


class TestFollowUpAgent:
    """Test the follow-up agent."""

    @pytest.mark.asyncio
    async def test_follow_up_first_attempt(self):
        from app.agents.follow_up import FollowUpAgent, FollowUpInput

        mock = MockProvider(responses={
            "follow-up specialist": '{"should_follow_up": true, "message": "Hey! Just checking in — did you get a chance to look over our pricing? Happy to answer any questions!", "schedule_hours_from_now": 4.0, "is_final_follow_up": false, "reasoning": "First follow-up"}'
        })
        agent = FollowUpAgent(llm=mock)
        input_data = FollowUpInput(
            lead_name="John",
            lead_message="What do you charge?",
            agent_last_response="Our plans start at $499/mo",
            hours_since_last_contact=6.0,
            follow_up_step=1,
            max_follow_ups=3,
            brand_voice={"tone": "friendly"},
            client_name="Acme",
        )
        output, step = await agent.run(
            input_data,
            context={
                "client_name": "Acme",
                "brand_voice": {"tone": "friendly"},
                "follow_up_step": 1,
                "max_follow_ups": 3,
                "lead_message": "What do you charge?",
                "agent_last_response": "Our plans start at $499/mo",
                "hours_since_last_contact": 6.0,
            },
        )
        assert output is not None
        assert output.should_follow_up is True
        assert output.is_final_follow_up is False


class TestCriticAgent:
    """Test the critic (safety gate) agent."""

    @pytest.mark.asyncio
    async def test_critic_approves_clean_message(self):
        from app.agents.critic import CriticAgent
        from app.agents.schemas import CriticInput

        mock = MockProvider(responses={
            "quality and safety verifier": '{"approved": true, "issues": [], "confidence": 0.95, "reasoning": "Message is grounded in KB facts and matches brand voice"}'
        })
        agent = CriticAgent(llm=mock)
        input_data = CriticInput(
            draft_message="Our Starter plan is $499/mo and includes a 5-page website.",
            brand_voice={"tone": "professional"},
            never_say_list={"phrases": ["guaranteed"]},
            kb_facts=[KBFact(content="Starter plan: $499/mo, 5-page website", source_title="Pricing", source_id="doc-1")],
            conversation_history=[],
            classifier_output=ClassifierOutput(intent="pricing_question", urgency="medium", language="en", confidence=0.9),
        )
        output, step = await agent.run(
            input_data,
            context={
                "brand_voice": {"tone": "professional"},
                "never_say_list": {"phrases": ["guaranteed"]},
                "kb_facts": [{"content": "Starter plan: $499/mo"}],
            },
        )
        assert output is not None
        assert output.approved is True
        assert len(output.issues) == 0

    @pytest.mark.asyncio
    async def test_critic_rejects_ungrounded_claim(self):
        from app.agents.critic import CriticAgent
        from app.agents.schemas import CriticInput

        mock = MockProvider(responses={
            "quality and safety verifier": '{"approved": false, "issues": [{"type": "ungrounded_claim", "description": "Claim about free trial not in KB", "severity": "critical"}], "confidence": 0.88, "reasoning": "Found ungrounded pricing claim"}'
        })
        agent = CriticAgent(llm=mock)
        input_data = CriticInput(
            draft_message="We offer a 30-day free trial on all plans!",
            brand_voice={"tone": "professional"},
            never_say_list={"phrases": ["guaranteed"]},
            kb_facts=[],
            conversation_history=[],
            classifier_output=ClassifierOutput(intent="pricing_question", urgency="medium", language="en", confidence=0.9),
        )
        output, step = await agent.run(
            input_data,
            context={
                "brand_voice": {"tone": "professional"},
                "never_say_list": {"phrases": ["guaranteed"]},
                "kb_facts": [],
            },
        )
        assert output is not None
        assert output.approved is False
        assert len(output.issues) > 0
        assert output.issues[0].type == "ungrounded_claim"
        assert output.issues[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_critic_catches_never_say(self):
        from app.agents.critic import CriticAgent
        from app.agents.schemas import CriticInput

        mock = MockProvider(responses={
            "quality and safety verifier": '{"approved": false, "issues": [{"type": "never_say_violation", "description": "Used blocked phrase guaranteed", "severity": "critical"}], "confidence": 0.92, "reasoning": "Never-say violation"}'
        })
        agent = CriticAgent(llm=mock)
        input_data = CriticInput(
            draft_message="We guaranteed you'll see results in 30 days!",
            brand_voice={},
            never_say_list={"phrases": ["guaranteed", "promise"]},
            kb_facts=[],
            conversation_history=[],
            classifier_output=ClassifierOutput(intent="inquiry", urgency="medium", language="en", confidence=0.9),
        )
        output, step = await agent.run(
            input_data,
            context={
                "brand_voice": {},
                "never_say_list": {"phrases": ["guaranteed", "promise"]},
                "kb_facts": [],
            },
        )
        assert output is not None
        assert output.approved is False
        assert any(i.type == "never_say_violation" for i in output.issues)


class TestSupervisorDecisionMatrix:
    """Test the decision matrix logic used by the Supervisor."""

    def _decide(self, mode, confidence, critic_approved, is_high_risk, shadow, kill_switch):
        """Replicate the Supervisor's decision logic for unit testing."""
        threshold = 0.85

        if kill_switch:
            return "block"
        if shadow:
            return "draft"
        if not critic_approved:
            return "escalate"
        if is_high_risk:
            return "escalate"
        if confidence < threshold:
            if mode == "full_auto":
                return "script_fallback"
            else:
                return "escalate"
        if mode == "suggest_only":
            return "draft"
        if mode == "auto_with_approval":
            return "pending_approval"
        return "send"

    def test_kill_switch_always_blocks(self):
        for mode in ["full_auto", "auto_with_approval", "suggest_only"]:
            assert self._decide(mode, 0.99, True, False, False, True) == "block"

    def test_shadow_always_drafts(self):
        assert self._decide("full_auto", 0.99, True, False, True, False) == "draft"

    def test_critic_reject_always_escalates(self):
        assert self._decide("full_auto", 0.99, False, False, False, False) == "escalate"

    def test_high_risk_always_escalates(self):
        assert self._decide("full_auto", 0.99, True, True, False, False) == "escalate"

    def test_low_confidence_full_auto_uses_fallback(self):
        assert self._decide("full_auto", 0.60, True, False, False, False) == "script_fallback"

    def test_low_confidence_suggest_only_escalates(self):
        assert self._decide("suggest_only", 0.60, True, False, False, False) == "escalate"

    def test_high_confidence_full_auto_sends(self):
        assert self._decide("full_auto", 0.92, True, False, False, False) == "send"

    def test_suggest_only_always_drafts(self):
        assert self._decide("suggest_only", 0.95, True, False, False, False) == "draft"

    def test_auto_with_approval_requires_approval(self):
        assert self._decide("auto_with_approval", 0.95, True, False, False, False) == "pending_approval"

    def test_decision_priority_order(self):
        """Kill switch > shadow > critic > high-risk > confidence > mode"""
        # Kill switch beats everything
        assert self._decide("full_auto", 0.99, True, True, True, True) == "block"
        # Shadow beats critic
        assert self._decide("full_auto", 0.99, False, True, True, False) == "draft"
        # Critic beats high-risk
        assert self._decide("full_auto", 0.99, False, True, False, False) == "escalate"
