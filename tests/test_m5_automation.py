"""Tests for Milestone 5 — Automation, Follow-ups, and Integration Services."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Conversation
from app.models.follow_up import FollowUpSchedule
from app.models.lead import Lead
from app.models.message import Message
from app.services.calendar import process_calendly_webhook
from app.services.notifications import send_escalation_notification
from app.tasks.follow_up import _process_single_follow_up


class TestNotificationService:
    """Test notification sending alerts."""

    @pytest.mark.asyncio
    async def test_escalation_email_logging(self):
        res = await send_escalation_notification(
            client_name="Test Company",
            lead_name="John Doe",
            reason="Low confidence score",
            draft_content="Hello, how can we help?",
            recipient_email="admin@test.com",
        )
        assert res is True


class TestCalendlyIntegration:
    """Test Calendly Webhook processing."""

    @pytest.mark.asyncio
    async def test_calendly_webhook_processing(self):
        db = AsyncMock()
        client_id = uuid.uuid4()
        agency_id = uuid.uuid4()
        lead_id = uuid.uuid4()
        conv_id = uuid.uuid4()

        # Mock Lead lookup
        mock_lead = Lead(
            id=lead_id,
            client_id=client_id,
            agency_id=agency_id,
            email="lead@example.com",
            phone="+15551112222",
            status="new",
        )
        lead_result = MagicMock()
        lead_result.scalar_one_or_none.return_value = mock_lead

        # Mock Conversation lookup
        mock_conv = Conversation(
            id=conv_id,
            lead_id=lead_id,
            client_id=client_id,
            agency_id=agency_id,
            channel="whatsapp",
            status="active",
        )
        conv_result = MagicMock()
        conv_result.scalar_one_or_none.return_value = mock_conv

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            res = MagicMock()
            if "leads" in stmt_str:
                res.scalar_one_or_none.return_value = mock_lead
            elif "conversations" in stmt_str:
                res.scalar_one_or_none.return_value = mock_conv
            return res

        db.execute.side_effect = execute_side_effect

        payload = {
            "payload": {
                "invitee": {
                    "email": "lead@example.com",
                    "phone": "+15551112222",
                    "name": "Jane Lead",
                },
                "scheduled_event": {
                    "start_time": "2026-06-30T10:00:00Z",
                    "end_time": "2026-06-30T10:30:00Z",
                    "uuid": "event-12345",
                },
            }
        }

        result = await process_calendly_webhook(payload, db)

        assert result["status"] == "processed"
        assert result["lead_id"] == str(lead_id)
        assert mock_lead.status == "qualified"
        assert db.add.call_count >= 2  # CalendarBooking + System Message


class TestFollowUpCadence:
    """Test Follow-up scheduler and response checks."""

    @pytest.mark.asyncio
    async def test_follow_up_cancelled_if_lead_responded(self):
        db = AsyncMock()
        lead_id = uuid.uuid4()
        client_id = uuid.uuid4()
        agency_id = uuid.uuid4()

        # Follow up schedule entry
        fu = FollowUpSchedule(
            id=uuid.uuid4(),
            lead_id=lead_id,
            client_id=client_id,
            agency_id=agency_id,
            step_number=1,
            status="pending",
            scheduled_at=datetime.now(UTC),
        )

        mock_lead = Lead(id=lead_id, name="Test Lead", status="contacted")
        mock_conv = Conversation(id=uuid.uuid4(), lead_id=lead_id, status="active")

        # Latest message is inbound -> lead has responded!
        mock_msg = Message(
            id=uuid.uuid4(),
            conversation_id=mock_conv.id,
            direction="inbound",
            sender_type="lead",
            content="Yes, I am interested.",
        )

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            res = MagicMock()
            if "leads" in stmt_str:
                res.scalar_one_or_none.return_value = mock_lead
            elif "conversations" in stmt_str:
                res.scalar_one_or_none.return_value = mock_conv
            elif "messages" in stmt_str:
                res.scalars.return_value.all.return_value = [mock_msg]
            return res

        db.execute.side_effect = execute_side_effect

        await _process_single_follow_up(db, fu, datetime.now(UTC))

        assert fu.status == "responded"
