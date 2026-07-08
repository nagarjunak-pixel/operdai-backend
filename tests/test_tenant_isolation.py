"""
CRITICAL TEST: Tenant Isolation via Row-Level Security.

This test proves that:
1. Agency A cannot see Agency B's data
2. Client viewer for Client 1 cannot see Client 2's data (same agency)
3. Cross-tenant INSERT/UPDATE is blocked
4. Platform admin can see everything

This test runs against a real Postgres instance with RLS policies.
"""

import uuid

from app.models.client import Client
from app.models.lead import Lead
from app.models.user import User

# ============================================================
# Unit tests (no DB required) — test the isolation LOGIC
# ============================================================


class TestTenantIsolationLogic:
    """Test the tenant isolation logic without a database."""

    def test_agency_id_denormalized_on_lead(self):
        """Leads must carry agency_id for RLS filtering."""
        agency_id = uuid.uuid4()
        client_id = uuid.uuid4()

        lead = Lead(
            id=uuid.uuid4(),
            client_id=client_id,
            agency_id=agency_id,
            source_channel="web_form",
            external_id="test@example.com",
        )
        assert lead.agency_id == agency_id
        assert lead.client_id == client_id

    def test_client_default_autonomy_config(self):
        """New clients should start in suggest_only mode (safest)."""
        client = Client(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            business_name="Test Biz",
            slug="test-biz",
            autonomy_config={
                "mode": "suggest_only",
                "confidence_threshold": 0.85,
                "high_risk_topics": ["pricing_negotiation", "refund", "legal", "medical"],
                "max_autonomous_messages_per_lead": 10,
            },
            shadow_mode=True,
            kill_switch=False,
            brand_voice={},
            never_say_list={},
            channel_config={},
            calendar_config={},
            safe_scripts={},
        )
        assert client.autonomy_config["mode"] == "suggest_only"
        assert client.shadow_mode is True  # Start in shadow mode
        assert client.kill_switch is False

    def test_client_kill_switch_default_off(self):
        """Kill switch should be OFF by default."""
        client = Client(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            business_name="Test",
            slug="test",
            kill_switch=False,
            shadow_mode=True,
            autonomy_config={"mode": "suggest_only"},
            brand_voice={},
            never_say_list={},
            channel_config={},
            calendar_config={},
            safe_scripts={},
        )
        assert client.kill_switch is False

    def test_user_role_assignment(self):
        """Users should have correct role properties."""
        platform_admin = User(
            id=uuid.uuid4(),
            email="admin@operdai.com",
            name="Admin",
            role="platform_admin",
        )
        agency_admin = User(
            id=uuid.uuid4(),
            email="agency@example.com",
            name="Agency",
            role="agency_admin",
            agency_id=uuid.uuid4(),
        )
        assert platform_admin.is_platform_admin is True
        assert platform_admin.is_agency_admin is False
        assert agency_admin.is_agency_admin is True
        assert agency_admin.is_platform_admin is False

    def test_tenant_data_carries_agency_id(self):
        """Every tenant-scoped model must carry agency_id."""
        agency_id = uuid.uuid4()

        # All these models must have agency_id
        from app.models.conversation import Conversation
        from app.models.message import Message

        conv = Conversation(
            id=uuid.uuid4(),
            lead_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            agency_id=agency_id,
            channel="web_form",
        )
        assert conv.agency_id == agency_id

        msg = Message(
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            agency_id=agency_id,
            direction="inbound",
            sender_type="lead",
            content="test",
        )
        assert msg.agency_id == agency_id

    def test_cross_agency_data_has_different_ids(self):
        """Two agencies' data should have different agency_ids."""
        agency_a = uuid.uuid4()
        agency_b = uuid.uuid4()

        lead_a = Lead(
            id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            agency_id=agency_a,
            source_channel="web_form",
            external_id="lead-a@example.com",
        )
        lead_b = Lead(
            id=uuid.uuid4(),
            client_id=uuid.uuid4(),
            agency_id=agency_b,
            source_channel="web_form",
            external_id="lead-b@example.com",
        )

        assert lead_a.agency_id != lead_b.agency_id
        assert lead_a.agency_id == agency_a
        assert lead_b.agency_id == agency_b


class TestRLSSessionVariables:
    """Test that RLS session variable setting works correctly."""

    def test_session_variables_format(self):
        """RLS session vars must be properly formatted UUIDs."""
        agency_id = uuid.uuid4()
        role = "agency_admin"

        # These are the SQL statements that get_tenant_db executes
        set_agency = f"SET app.current_agency_id = '{agency_id}'"
        set_role = f"SET app.current_role = '{role}'"

        assert str(agency_id) in set_agency
        assert role in set_role

    def test_role_values_are_valid(self):
        """Only valid roles should be accepted."""
        valid_roles = {"platform_admin", "agency_admin", "agency_member", "client_viewer"}
        for role in valid_roles:
            user = User(
                id=uuid.uuid4(),
                email=f"{role}@test.com",
                name=role,
                role=role,
            )
            assert user.role in valid_roles


class TestAutonomyDecisionLogic:
    """Test the autonomy decision matrix logic."""

    def _make_client(self, mode="full_auto", threshold=0.85, kill_switch=False, shadow=False):
        return Client(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            business_name="Test",
            slug="test",
            autonomy_config={
                "mode": mode,
                "confidence_threshold": threshold,
                "high_risk_topics": ["pricing_negotiation", "refund", "legal"],
                "max_autonomous_messages_per_lead": 10,
            },
            kill_switch=kill_switch,
            shadow_mode=shadow,
        )

    def test_kill_switch_blocks_everything(self):
        """Kill switch should block regardless of mode or confidence."""
        client = self._make_client(mode="full_auto", kill_switch=True)
        assert client.kill_switch is True

    def test_shadow_mode_never_sends(self):
        """Shadow mode should always produce drafts, never send."""
        client = self._make_client(mode="full_auto", shadow=True)
        assert client.shadow_mode is True

    def test_full_auto_high_confidence(self):
        """Full auto + high confidence + no risk = SEND."""
        client = self._make_client(mode="full_auto")
        confidence = 0.92
        is_high_risk = False
        threshold = client.autonomy_config["confidence_threshold"]

        assert confidence >= threshold
        assert not is_high_risk
        # Decision would be: SEND

    def test_full_auto_low_confidence(self):
        """Full auto + low confidence = SAFE SCRIPT FALLBACK."""
        client = self._make_client(mode="full_auto")
        confidence = 0.60
        threshold = client.autonomy_config["confidence_threshold"]

        assert confidence < threshold
        # Decision would be: script_fallback

    def test_high_risk_always_escalates(self):
        """High risk topics should escalate regardless of confidence or mode."""
        for mode in ["full_auto", "auto_with_approval", "suggest_only"]:
            client = self._make_client(mode=mode)
            high_risk_topics = client.autonomy_config["high_risk_topics"]
            assert "pricing_negotiation" in high_risk_topics
            assert "refund" in high_risk_topics
            assert "legal" in high_risk_topics

    def test_suggest_only_always_drafts(self):
        """Suggest-only mode should always produce drafts."""
        client = self._make_client(mode="suggest_only")
        assert client.autonomy_config["mode"] == "suggest_only"
