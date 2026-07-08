"""Tests for Milestone 6 — Billing, Metering, and Cost Caps."""

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.billing import BillingConfig, UsageRecord
from app.services.billing import (
    is_agency_capped,
    log_usage,
    process_stripe_webhook,
)


class TestUsageMetering:
    """Test usage metering logs and summary calculation."""

    @pytest.mark.asyncio
    async def test_log_usage_new_record(self):
        db = AsyncMock()
        agency_id = uuid.uuid4()
        client_id = uuid.uuid4()

        # Mock query: no record exists
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        record = await log_usage(
            db=db,
            agency_id=agency_id,
            client_id=client_id,
            tokens=5000,
            cost_cents=10,
            message_sent=True,
            is_new_lead=True,
        )

        assert record.tokens_used == 5000
        assert record.cost_cents == 10
        assert record.messages_sent == 1
        assert record.leads_handled == 1
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_usage_increment(self):
        db = AsyncMock()
        agency_id = uuid.uuid4()
        client_id = uuid.uuid4()

        existing = UsageRecord(
            agency_id=agency_id,
            client_id=client_id,
            period_start=date.today(),
            period_end=date.today(),
            leads_handled=5,
            messages_sent=10,
            tokens_used=10000,
            cost_cents=50,
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        db.execute.return_value = result

        record = await log_usage(
            db=db,
            agency_id=agency_id,
            client_id=client_id,
            tokens=2000,
            cost_cents=15,
            message_sent=True,
            is_new_lead=False,
        )

        assert record.tokens_used == 12000
        assert record.cost_cents == 65
        assert record.messages_sent == 11
        assert record.leads_handled == 5


class TestCostCaps:
    """Test cost cap checking and enforcement."""

    @pytest.mark.asyncio
    async def test_is_agency_capped_under_limit(self):
        db = AsyncMock()
        agency_id = uuid.uuid4()

        config = BillingConfig(
            agency_id=agency_id,
            monthly_lead_cap=100,
            monthly_token_cap=100000,
            is_capped=False,
        )

        # First query: config
        # Second query: aggregate usage
        config_res = MagicMock()
        config_res.scalar_one_or_none.return_value = config

        usage_res = MagicMock()
        usage_res.first.return_value = MagicMock(leads=10, tokens=5000)

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "billing_config" in stmt_str:
                return config_res
            return usage_res

        db.execute.side_effect = execute_side_effect

        capped = await is_agency_capped(db, agency_id)
        assert capped is False
        assert config.is_capped is False

    @pytest.mark.asyncio
    async def test_is_agency_capped_over_lead_limit(self):
        db = AsyncMock()
        agency_id = uuid.uuid4()

        config = BillingConfig(
            agency_id=agency_id,
            monthly_lead_cap=50,
            monthly_token_cap=100000,
            is_capped=False,
        )

        config_res = MagicMock()
        config_res.scalar_one_or_none.return_value = config

        usage_res = MagicMock()
        usage_res.first.return_value = MagicMock(leads=55, tokens=5000)

        def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "billing_config" in stmt_str:
                return config_res
            return usage_res

        db.execute.side_effect = execute_side_effect

        capped = await is_agency_capped(db, agency_id)
        assert capped is True
        assert config.is_capped is True


class TestStripeWebhooks:
    """Test Stripe webhook payloads and state transformations."""

    @pytest.mark.asyncio
    async def test_stripe_webhook_invoice_paid_resets_cap(self):
        db = AsyncMock()
        config = BillingConfig(
            stripe_subscription_id="sub_test_123",
            is_capped=True,
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = config
        db.execute.return_value = result

        event_data = {
            "object": {
                "subscription": "sub_test_123",
                "customer": "cus_111",
            }
        }

        success = await process_stripe_webhook("invoice.payment_succeeded", event_data, db)
        assert success is True
        assert config.is_capped is False
