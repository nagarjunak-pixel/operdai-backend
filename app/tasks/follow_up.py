"""
Celery tasks for follow-ups and lead re-engagement.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.agents.follow_up import FollowUpAgent, FollowUpInput
from app.celery_app import celery_app
from app.database import async_session_factory
from app.models.client import Client
from app.models.conversation import Conversation
from app.models.follow_up import FollowUpSchedule
from app.models.lead import Lead
from app.models.message import Message
from app.services.channels import Channel, OutboundMessage, send_outbound


@celery_app.task(name="app.tasks.follow_up.check_and_trigger_follow_ups")
def check_and_trigger_follow_ups() -> None:
    """
    Periodic task to check and trigger follow-up schedules.
    """
    async def _run():
        now = datetime.now(UTC)
        async with async_session_factory() as db:
            # Query all due pending follow-ups
            stmt = (
                select(FollowUpSchedule)
                .where(
                    FollowUpSchedule.status == "pending",
                    FollowUpSchedule.scheduled_at <= now,
                )
            )
            result = await db.execute(stmt)
            follow_ups = result.scalars().all()

            for fu in follow_ups:
                await _process_single_follow_up(db, fu, now)

            await db.commit()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


async def _process_single_follow_up(
    db: any,
    fu: FollowUpSchedule,
    now: datetime,
) -> None:
    from app.services.locking import DistributedLock
    # Acquire distributed lock to prevent concurrent workers from triggering same follow-up twice
    async with DistributedLock(f"follow_up:{fu.lead_id}", lease_seconds=15) as acquired:
        if not acquired:
            return

        # 1. Load Lead and Conversation
        lead_result = await db.execute(select(Lead).where(Lead.id == fu.lead_id))
        lead = lead_result.scalar_one_or_none()
        if not lead:
            fu.status = "cancelled"
            return

        conv_result = await db.execute(
            select(Conversation)
            .where(
                Conversation.lead_id == fu.lead_id,
                Conversation.status == "active",
            )
        )
        conv = conv_result.scalar_one_or_none()
        if not conv:
            fu.status = "cancelled"
            return

        # 2. Get latest messages to check response status
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
        )
        messages = msg_result.scalars().all()
        if not messages:
            fu.status = "cancelled"
            return

        latest_msg = messages[0]

        # If lead sent the last message, they responded!
        if latest_msg.direction == "inbound":
            fu.status = "responded"
            # Cancel any other pending follow-ups for this lead
            await db.execute(
                update(FollowUpSchedule)
                .where(
                    FollowUpSchedule.lead_id == fu.lead_id,
                    FollowUpSchedule.status == "pending",
                )
                .values(status="responded")
            )
            return

        # Extract conversation details
        lead_message_content = "N/A"
        agent_last_response_content = "N/A"
        for msg in messages:
            if msg.direction == "inbound" and lead_message_content == "N/A":
                lead_message_content = msg.content
            elif msg.direction == "outbound" and agent_last_response_content == "N/A":
                agent_last_response_content = msg.content

        # Load Client config
        client_result = await db.execute(select(Client).where(Client.id == fu.client_id))
        client = client_result.scalar_one_or_none()
        if not client:
            fu.status = "cancelled"
            return

        # 3. Configure and execute Follow-up Agent
        autonomy_cfg = client.autonomy_config or {}
        cadence = autonomy_cfg.get("follow_up_cadence", {})
        max_attempts = cadence.get("max_follow_ups", 3)
        delays = cadence.get("delays_hours", [4, 24, 72])

        hours_elapsed = (now - latest_msg.created_at).total_seconds() / 3600.0

        input_data = FollowUpInput(
            lead_name=lead.name,
            lead_message=lead_message_content,
            agent_last_response=agent_last_response_content,
            hours_since_last_contact=hours_elapsed,
            follow_up_step=fu.step_number,
            max_follow_ups=max_attempts,
            cadence_delays_hours=delays,
            brand_voice=client.brand_voice or {},
            client_name=client.business_name,
        )

        agent = FollowUpAgent()
        output, step = await agent.run(
            input_data,
            context={
                "client_name": client.business_name,
                "brand_voice": client.brand_voice or {},
                "follow_up_step": fu.step_number,
                "max_follow_ups": max_attempts,
                "lead_message": lead_message_content,
                "agent_last_response": agent_last_response_content,
                "hours_since_last_contact": hours_elapsed,
            },
        )

        # 4. Trigger Outbound Sending & Next Schedule
        if output and output.should_follow_up and output.message:
            msg = Message(
                conversation_id=conv.id,
                client_id=client.id,
                agency_id=client.agency_id,
                direction="outbound",
                sender_type="agent",
                content=output.message,
                status="sending",
            )
            db.add(msg)
            await db.flush()

            recipient = lead.phone if conv.channel in ("whatsapp", "sms") else (lead.email or lead.external_id)
            outbound = OutboundMessage(
                channel=Channel(conv.channel),
                recipient=recipient,
                content=output.message,
            )

            result = await send_outbound(outbound, client.channel_config)
            msg.status = "sent" if result.success else "failed"
            if result.message_sid:
                msg.metadata_ = {"twilio_sid": result.message_sid}

            fu.status = "sent"

            # Check if we should schedule next step
            next_step = fu.step_number + 1
            if next_step <= max_attempts and not output.is_final_follow_up:
                delay_hours = output.schedule_hours_from_now or (
                    delays[next_step - 1] if next_step - 1 < len(delays) else 24.0
                )
                next_scheduled = now + timedelta(hours=delay_hours)

                next_fu = FollowUpSchedule(
                    lead_id=fu.lead_id,
                    client_id=fu.client_id,
                    agency_id=fu.agency_id,
                    step_number=next_step,
                    scheduled_at=next_scheduled,
                    status="pending",
                )
                db.add(next_fu)
        else:
            fu.status = "cancelled"
