"""
Calendar Service — integrations with scheduling tools (e.g., Calendly webhooks).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_booking import CalendarBooking
from app.models.conversation import Conversation
from app.models.follow_up import FollowUpSchedule
from app.models.lead import Lead
from app.models.message import Message


async def process_calendly_webhook(
    payload: dict,
    db: AsyncSession,
) -> dict:
    """
    Process incoming Calendly webhook event (e.g., invitee.created).
    Finds lead by email/phone, logs booking, cancels follow-ups, and updates lead status.
    """
    event_payload = payload.get("payload", {}) or payload
    invitee = event_payload.get("invitee", {}) or event_payload
    scheduled_event = event_payload.get("scheduled_event", {}) or event_payload

    email = invitee.get("email")
    phone = invitee.get("phone")
    name = invitee.get("name")

    start_time_str = scheduled_event.get("start_time") or event_payload.get("start_time")
    end_time_str = scheduled_event.get("end_time") or event_payload.get("end_time")
    event_id = scheduled_event.get("uuid") or event_payload.get("event_id") or str(uuid.uuid4())

    if not email and not phone:
        return {"status": "ignored", "reason": "No email or phone in payload"}

    # 1. Look up Lead by email or phone
    stmt = select(Lead)
    if email and phone:
        stmt = stmt.where((Lead.email == email) | (Lead.phone == phone))
    elif email:
        stmt = stmt.where(Lead.email == email)
    else:
        stmt = stmt.where(Lead.phone == phone)

    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()

    if not lead:
        return {"status": "ignored", "reason": f"Lead not found for email: {email} / phone: {phone}"}

    # Parse ISO times
    try:
        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(minutes=30)

    # 2. Create Calendar Booking
    booking = CalendarBooking(
        lead_id=lead.id,
        client_id=lead.client_id,
        agency_id=lead.agency_id,
        calendar_event_id=event_id,
        start_time=start_time,
        end_time=end_time,
        status="confirmed",
    )
    db.add(booking)

    # 3. Update Lead Status
    lead.status = "qualified"
    lead.last_activity_at = datetime.now(UTC)

    # 4. Cancel all pending follow-up schedules
    await db.execute(
        update(FollowUpSchedule)
        .where(
            FollowUpSchedule.lead_id == lead.id,
            FollowUpSchedule.status == "pending",
        )
        .values(status="responded")
    )

    # 5. Log system message in conversation if active conversation exists
    conv_result = await db.execute(
        select(Conversation)
        .where(
            Conversation.lead_id == lead.id,
            Conversation.status == "active",
        )
    )
    conv = conv_result.scalar_one_or_none()
    if conv:
        system_msg = Message(
            conversation_id=conv.id,
            client_id=lead.client_id,
            agency_id=lead.agency_id,
            direction="outbound",
            sender_type="agent",
            content=f"System Notification: Lead booked a discovery call for {start_time.strftime('%Y-%m-%d %H:%M UTC')}.",
            status="sent",
            metadata_={"system": True, "event_id": event_id},
        )
        db.add(system_msg)

    await db.flush()
    return {
        "status": "processed",
        "lead_id": str(lead.id),
        "booking_id": str(booking.id),
    }
