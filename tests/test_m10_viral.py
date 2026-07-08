"""Tests for Milestone 10 — Viral Loops & Advanced Agentic Expansion."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from app.api.v1.shares import create_share_template, clone_share_template, ShareRequest, CloneRequest
from app.services.webrtc import initiate_voice_session, handle_verbal_trigger
from app.services.negotiation import run_agent_negotiation
from app.services.rlhf import auto_tune_prompt
from app.api.v1.integrations import toggle_integration, list_integrations, IntegrationToggleRequest
from app.models.client import Client
from app.models.share import AgentTemplate
from app.models.integration import Integration
from app.models.feedback import ToneFeedback
from app.agents.llm import LLMResponse


class TestSharingAndCloning:
    """Test one-click sharing and cloning configurations."""

    @pytest.mark.asyncio
    async def test_create_and_clone_template(self):
        db = AsyncMock()
        client_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        template_id = uuid.uuid4()

        client = Client(
            id=client_id,
            agency_id=agency_id,
            business_name="Original Client",
            slug="original-client",
            brand_voice={"tone": "Professional tone"},
            never_say_list={"phrases": ["never"]},
            autonomy_config={"mode": "auto"},
        )
        template = AgentTemplate(
            id=template_id,
            name="Test Template",
            brand_voice={"tone": "Professional tone"},
            never_say_list={"phrases": ["never"]},
            autonomy_config={"mode": "auto"},
        )

        client_res = MagicMock()
        client_res.scalar_one_or_none.return_value = client

        tmpl_res = MagicMock()
        tmpl_res.scalar_one_or_none.return_value = template

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "agent_templates" in stmt_str:
                return tmpl_res
            return client_res

        db.execute.side_effect = execute_side_effect

        # 1. Create Share Template
        share_body = ShareRequest(client_id=client_id, name="Shared Config", description="For testing")
        res_create = await create_share_template(share_body, db=db, user=MagicMock())
        assert res_create["status"] == "created"
        assert "template_id" in res_create

        # 2. Clone Share Template
        clone_body = CloneRequest(template_id=template_id, agency_id=agency_id, name="Cloned Client")
        res_clone = await clone_share_template(clone_body, db=db, user=MagicMock())
        assert res_clone["status"] == "cloned"
        assert "client_id" in res_clone


class TestWebRTCVoiceGateway:
    """Test WebRTC Voice Gateway session and verbal triggers."""

    @pytest.mark.asyncio
    async def test_initiate_voice_session(self):
        client_id = uuid.uuid4()
        res = await initiate_voice_session(client_id)
        assert res["status"] == "connected"
        assert len(res["ice_servers"]) > 0

    @pytest.mark.asyncio
    @patch("app.database.async_session_factory")
    async def test_handle_verbal_trigger_flow(self, mock_session_factory):
        # We need mock DB session because verbal trigger writes Message to DB
        db = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = db

        # Mock run_full_pipeline output
        pipeline_res = {
            "decision": "send",
            "draft_message": "Hello, how can I help you today?",
        }

        with patch("app.agents.supervisor.run_full_pipeline", return_value=pipeline_res):
            res = await handle_verbal_trigger(
                client_id=uuid.uuid4(),
                agency_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                transcript="Hello",
            )
            assert res["decision"] == "send"
            assert res["tts_output"] == "Hello, how can I help you today?"


class TestAgentNegotiation:
    """Test autonomous agent-to-agent negotiation loop."""

    @pytest.mark.asyncio
    async def test_run_agent_negotiation(self):
        llm = AsyncMock()
        # Mock Negotiator agent response to accept terms on 2nd turn
        from app.services.negotiation import NegotiationTurnOutput
        canned_res = NegotiationTurnOutput(
            reasoning="Terms match",
            counter_proposal="Agreed.",
            agreed=True,
        )
        llm.complete.return_value = LLMResponse(
            content="{}",
            parsed=canned_res,
            tokens_in=10,
            tokens_out=10,
            cost_cents=1.0,
        )

        res = await run_agent_negotiation(
            client_a_id=uuid.uuid4(),
            client_b_id=uuid.uuid4(),
            topic="Pricing terms",
            rounds=1,
            llm=llm,
        )
        assert res["status"] == "agreed"
        assert len(res["history"]) > 0


class TestRLHFPromptTuning:
    """Test RLHF Prompt Tuning from Operator Feedback."""

    @pytest.mark.asyncio
    async def test_auto_tune_prompt_flow(self):
        db = AsyncMock()
        client_id = uuid.uuid4()

        client = Client(
            id=client_id,
            agency_id=uuid.uuid4(),
            business_name="Acme",
            slug="acme",
            brand_voice={"tone": "Professional brand voice."},
        )
        feedback = ToneFeedback(
            client_id=client_id,
            original_draft="We guarantee absolute free support.",
            human_response="We support our products fully.",
            edited=True,
        )

        # Mock DB queries
        client_res = MagicMock()
        client_res.scalar_one_or_none.return_value = client

        feedback_res = MagicMock()
        feedback_res.scalars.return_value.all.return_value = [feedback]

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "clients" in stmt_str:
                return client_res
            return feedback_res

        db.execute.side_effect = execute_side_effect

        # Mock LLM provider tuning response
        llm = AsyncMock()
        llm.complete.return_value = LLMResponse(
            content="Refined Brand Guide: Be concise and factual.",
            tokens_in=10,
            tokens_out=10,
            cost_cents=1.0,
        )

        with patch("app.services.rlhf.get_llm_provider", return_value=llm):
            res_voice = await auto_tune_prompt(db, client_id)
            assert "Refined" in res_voice
            assert client.brand_voice["tone"] == "Refined Brand Guide: Be concise and factual."


class TestIntegrationsStore:
    """Test connections in the plug-and-play integrations store."""

    @pytest.mark.asyncio
    async def test_toggle_and_list_integrations(self):
        db = AsyncMock()
        client_id = uuid.uuid4()

        # Mock DB queries
        empty_res = MagicMock()
        empty_res.scalar_one_or_none.return_value = None

        integration = Integration(
            client_id=client_id,
            platform="shopify",
            is_active=True,
        )
        list_res = MagicMock()
        list_res.scalars.return_value.all.return_value = [integration]

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "toggle" in stmt_str or "where" in stmt_str:
                if "select" in stmt_str:
                    return list_res
            return empty_res

        db.execute.side_effect = execute_side_effect

        # 1. Toggle integration
        body = IntegrationToggleRequest(client_id=client_id, platform="shopify", is_active=True)
        res_toggle = await toggle_integration(body, db=db, user=MagicMock())
        assert res_toggle["status"] == "updated"
        assert res_toggle["is_active"] is True

        # 2. List integrations
        res_list = await list_integrations(client_id=client_id, db=db, user=MagicMock())
        assert len(res_list) == 1
        assert res_list[0].platform == "shopify"
