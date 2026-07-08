"""Tests for Milestone 8 — Advanced Autonomous Core (Meta-Debugger, Consensus, Feedback)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import json

from app.agents.meta_debugger import MetaDebuggerAgent, DebuggerInput, DebuggerOutput
from app.services.consensus import ConsensusCoordinator
from app.api.v1.escalations import resolve_escalation, EscalationAction
from app.models.agent_run import AgentRun
from app.models.message import Message
from app.models.conversation import Conversation
from app.models.feedback import ToneFeedback
from app.agents.llm import LLMResponse


class TestMetaDebugger:
    """Test Meta-Debugger schemas and outputs."""

    @pytest.mark.asyncio
    async def test_debugger_run(self):
        llm = AsyncMock()
        dbg_output = DebuggerOutput(
            reasoning="Violated never-say list",
            instruction_override="Adhere to professional brand tones.",
            approved_for_retry=True,
        )
        llm.complete.return_value = LLMResponse(
            content="{}",
            parsed=dbg_output,
            tokens_in=10,
            tokens_out=10,
            cost_cents=1.0,
        )

        agent = MetaDebuggerAgent(llm=llm)
        inp = DebuggerInput(
            original_prompt="Brand tone guide",
            draft_message="We guarantee free support.",
            critic_feedback="Critic rejected never-say phrase",
            conversation_history=[],
        )
        output, step = await agent.run(inp)

        assert output.approved_for_retry is True
        assert "Adhere" in output.instruction_override


class TestConsensusCoordinator:
    """Test PBFT-style consensus coordinator engine."""

    @pytest.mark.asyncio
    async def test_consensus_approved(self):
        coord = ConsensusCoordinator(models=["m1", "m2", "m3"])
        res = await coord.evaluate_action(
            action_type="confirm_booking",
            proposed_payload={"start_time": "2026-06-30T10:00:00Z"},
            conversation_history=[],
        )
        assert res["decision"] == "approved"
        assert res["quorum_percentage"] == 100.0

    @pytest.mark.asyncio
    async def test_consensus_escalate_missing_payload(self):
        coord = ConsensusCoordinator(models=["m1", "m2", "m3"])
        res = await coord.evaluate_action(
            action_type="confirm_booking",
            proposed_payload={},  # Missing start_time
            conversation_history=[],
        )
        assert res["decision"] == "escalate"
        assert res["quorum_percentage"] == 0.0


class TestToneFeedback:
    """Test logging operator edits to ToneFeedback database."""

    @pytest.mark.asyncio
    async def test_resolve_escalation_records_feedback(self):
        db = AsyncMock()
        run_id = uuid.uuid4()
        client_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        lead_id = uuid.uuid4()

        run = AgentRun(
            id=run_id,
            conversation_id=conv_id,
            client_id=client_id,
            agency_id=agency_id,
            decision="escalate",
        )
        draft = Message(
            id=uuid.uuid4(),
            conversation_id=conv_id,
            direction="outbound",
            status="draft",
            content="Original draft content.",
        )
        conv = Conversation(
            id=conv_id,
            lead_id=lead_id,
        )

        # Mock DB results
        run_res = MagicMock()
        run_res.scalar_one_or_none.return_value = run

        draft_res = MagicMock()
        draft_res.scalar_one_or_none.return_value = draft

        conv_res = MagicMock()
        conv_res.scalar_one_or_none.return_value = conv

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "agent_runs" in stmt_str:
                return run_res
            elif "conversations" in stmt_str:
                return conv_res
            return draft_res

        db.execute.side_effect = execute_side_effect

        body = EscalationAction(action="edit_and_send", edited_message="New human edited content.")
        response = await resolve_escalation(
            run_id=run_id,
            body=body,
            db=db,
            user=MagicMock(),
        )

        assert response["action"] == "edit_and_send"
        assert run.decision == "send_edited"
        assert draft.content == "New human edited content."
        assert draft.status == "sent"

        # Verify feedback model was inserted
        db.add.assert_called_once()
        feedback_obj = db.add.call_args[0][0]
        assert isinstance(feedback_obj, ToneFeedback)
        assert feedback_obj.original_draft == "Original draft content."
        assert feedback_obj.human_response == "New human edited content."
        assert feedback_obj.edited is True
