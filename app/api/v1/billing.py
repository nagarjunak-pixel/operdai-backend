"""
Billing API routes — usage summary and Stripe webhooks.
"""

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.deps import AgencyAdmin, RawDB, TenantDB
from app.services.billing import get_usage_summary, process_stripe_webhook

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/usage")
async def get_agency_billing_usage(
    token: AgencyAdmin,
    db: TenantDB,
):
    """
    Get aggregated usage metrics, costs, caps, and limit percentages.
    Only available to Agency Administrators.
    """
    return await get_usage_summary(db, UUID(token.agency_id))


@router.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    db: RawDB,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
):
    """
    Stripe webhook endpoint.
    Processes subscription events and payments to update limit caps.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    event_type = payload.get("type")
    event_data = payload.get("data", {})

    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event type",
        )

    success = await process_stripe_webhook(event_type, event_data, db)
    await db.commit()

    return {"status": "processed" if success else "ignored", "event": event_type}


@router.get("/profit-audit")
async def profit_margin_audit(
    token: AgencyAdmin,
    db: TenantDB,
):
    """
    Generate financial profit margins for the active agency.
    Calculates total SaaS subscriptions revenue vs OpenAI API costs.
    """
    from sqlalchemy import select, func
    from app.models.billing import UsageRecord, BillingConfig
    from app.services.billing import get_current_period
    import uuid

    agency_id = uuid.UUID(token.agency_id)
    start, _ = get_current_period()

    # 1. Calculate cumulative usage cost
    usage_stmt = select(func.sum(UsageRecord.cost_cents)).where(
        UsageRecord.agency_id == agency_id,
        UsageRecord.period_start == start,
    )
    usage_res = await db.execute(usage_stmt)
    total_cost_cents = usage_res.scalar() or 0

    # 2. Get active plan type to estimate billing revenue
    config_stmt = select(BillingConfig).where(BillingConfig.agency_id == agency_id)
    config_res = await db.execute(config_stmt)
    config = config_res.scalar_one_or_none()

    plan = config.plan_type if config else "starter"
    pricing_tiers = {"starter": 29900, "growth": 79900, "enterprise": 249900}
    revenue_cents = pricing_tiers.get(plan.lower(), 29900)

    net_profit_cents = revenue_cents - total_cost_cents
    margin_pct = (net_profit_cents / revenue_cents) * 100 if revenue_cents > 0 else 0.0

    return {
        "agency_id": str(agency_id),
        "plan_type": plan,
        "revenue_cents": revenue_cents,
        "api_cost_cents": total_cost_cents,
        "net_profit_cents": net_profit_cents,
        "profit_margin_pct": round(margin_pct, 2),
    }
