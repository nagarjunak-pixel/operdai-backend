"""
Billing Service — usage metering, cost caps, and Stripe webhook handling.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import BillingConfig, UsageRecord

logger = logging.getLogger("operdai.billing")


def get_current_period() -> tuple[date, date]:
    """Helper to get current month's start and end dates."""
    today = date.today()
    start = date(today.year, today.month, 1)
    if today.month == 12:
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year, today.month + 1, 1)
    return start, end


async def log_usage(
    db: AsyncSession,
    agency_id: uuid.UUID,
    client_id: uuid.UUID,
    tokens: int,
    cost_cents: int,
    message_sent: bool = False,
    is_new_lead: bool = False,
) -> UsageRecord:
    """
    Log usage metrics for an agent run in the current billing period.
    Creates or updates the monthly UsageRecord.
    """
    start, end = get_current_period()

    # Search for existing record
    stmt = select(UsageRecord).where(
        UsageRecord.agency_id == agency_id,
        UsageRecord.client_id == client_id,
        UsageRecord.period_start == start,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        record = UsageRecord(
            agency_id=agency_id,
            client_id=client_id,
            period_start=start,
            period_end=end,
            leads_handled=1 if is_new_lead else 0,
            messages_sent=1 if message_sent else 0,
            tokens_used=tokens,
            cost_cents=cost_cents,
        )
        db.add(record)
    else:
        record.tokens_used += tokens
        record.cost_cents += cost_cents
        if message_sent:
            record.messages_sent += 1
        if is_new_lead:
            record.leads_handled += 1

    await db.flush()
    return record


async def is_agency_capped(
    db: AsyncSession,
    agency_id: uuid.UUID,
) -> bool:
    """
    Checks if the agency has exceeded its monthly lead cap or token cap.
    If caps are exceeded, marks BillingConfig as capped and returns True.
    """
    # 1. Fetch Billing Config
    config_result = await db.execute(
        select(BillingConfig).where(BillingConfig.agency_id == agency_id)
    )
    config = config_result.scalar_one_or_none()

    if not config:
        return False

    if config.is_capped:
        return True

    # 2. Get aggregate usage for current period
    start, _ = get_current_period()
    stmt = (
        select(
            func.sum(UsageRecord.leads_handled).label("leads"),
            func.sum(UsageRecord.tokens_used).label("tokens"),
        )
        .where(
            UsageRecord.agency_id == agency_id,
            UsageRecord.period_start == start,
        )
    )
    res = await db.execute(stmt)
    usage = res.first()

    total_leads = (usage.leads or 0) if usage else 0
    total_tokens = (usage.tokens or 0) if usage else 0

    # 3. Check caps
    cap_reached = False
    if config.monthly_lead_cap and total_leads >= config.monthly_lead_cap:
        cap_reached = True
        logger.warning(f"Agency {agency_id} exceeded monthly lead cap: {total_leads}/{config.monthly_lead_cap}")

    if config.monthly_token_cap and total_tokens >= config.monthly_token_cap:
        cap_reached = True
        logger.warning(f"Agency {agency_id} exceeded monthly token cap: {total_tokens}/{config.monthly_token_cap}")

    if cap_reached:
        config.is_capped = True
        await db.flush()
        return True

    return False


async def get_usage_summary(
    db: AsyncSession,
    agency_id: uuid.UUID,
) -> dict:
    """
    Get aggregated usage metrics and cap utilization for an agency.
    """
    start, _ = get_current_period()

    # Get total usage
    usage_stmt = (
        select(
            func.sum(UsageRecord.leads_handled).label("leads"),
            func.sum(UsageRecord.messages_sent).label("messages"),
            func.sum(UsageRecord.tokens_used).label("tokens"),
            func.sum(UsageRecord.cost_cents).label("cost"),
        )
        .where(
            UsageRecord.agency_id == agency_id,
            UsageRecord.period_start == start,
        )
    )
    res = await db.execute(usage_stmt)
    usage = res.first()

    total_leads = (usage.leads or 0) if usage else 0
    total_messages = (usage.messages or 0) if usage else 0
    total_tokens = (usage.tokens or 0) if usage else 0
    total_cost = (usage.cost or 0) if usage else 0

    # Get limits
    config_result = await db.execute(
        select(BillingConfig).where(BillingConfig.agency_id == agency_id)
    )
    config = config_result.scalar_one_or_none()

    lead_cap = config.monthly_lead_cap if config else None
    token_cap = config.monthly_token_cap if config else None
    is_capped = config.is_capped if config else False

    lead_utilization = (total_leads / lead_cap) * 100 if lead_cap else 0
    token_utilization = (total_tokens / token_cap) * 100 if token_cap else 0

    return {
        "period_start": start.isoformat(),
        "usage": {
            "leads_handled": total_leads,
            "messages_sent": total_messages,
            "tokens_used": total_tokens,
            "cost_cents": total_cost,
        },
        "caps": {
            "monthly_lead_cap": lead_cap,
            "monthly_token_cap": token_cap,
            "lead_utilization_pct": round(lead_utilization, 2),
            "token_utilization_pct": round(token_utilization, 2),
            "is_capped": is_capped,
        },
    }


async def process_stripe_webhook(
    event_type: str,
    event_data: dict,
    db: AsyncSession,
) -> bool:
    """
    Handles Stripe webhooks to keep BillingConfigs up-to-date.
    Supported: customer.subscription.created, customer.subscription.deleted, invoice.payment_succeeded.
    """
    obj = event_data.get("object", {})
    customer_id = obj.get("customer")
    subscription_id = obj.get("id")

    if event_type == "customer.subscription.created":
        # Find billing config and associate subscription
        stmt = select(BillingConfig).where(BillingConfig.stripe_customer_id == customer_id)
        res = await db.execute(stmt)
        cfg = res.scalar_one_or_none()
        if cfg:
            cfg.stripe_subscription_id = subscription_id
            cfg.is_capped = False  # Reset cap on new subscription
            await db.flush()
            return True

    elif event_type == "customer.subscription.deleted":
        # Cap agency since subscription has been canceled
        stmt = select(BillingConfig).where(BillingConfig.stripe_subscription_id == subscription_id)
        res = await db.execute(stmt)
        cfg = res.scalar_one_or_none()
        if cfg:
            cfg.is_capped = True
            await db.flush()
            return True

    elif event_type == "invoice.payment_succeeded":
        # Reset caps after successful payment
        sub_id = obj.get("subscription")
        stmt = select(BillingConfig).where(BillingConfig.stripe_subscription_id == sub_id)
        res = await db.execute(stmt)
        cfg = res.scalar_one_or_none()
        if cfg:
            cfg.is_capped = False
            await db.flush()
            return True

    return False
