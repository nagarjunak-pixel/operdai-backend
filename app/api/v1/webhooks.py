"""Webhook API routes — inbound channel endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.client import Client
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.schemas.core import WebFormLead

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _get_or_create_lead(
    db: AsyncSession,
    client: Client,
    external_id: str,
    channel: str,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> Lead:
    """Find existing lead by external_id or create a new one."""
    result = await db.execute(
        select(Lead).where(
            Lead.client_id == client.id,
            Lead.external_id == external_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead:
        return lead

    lead = Lead(
        client_id=client.id,
        agency_id=client.agency_id,
        source_channel=channel,
        external_id=external_id,
        name=name,
        email=email,
        phone=phone,
    )
    db.add(lead)
    await db.flush()
    return lead


async def _get_or_create_conversation(
    db: AsyncSession, lead: Lead, channel: str
) -> Conversation:
    """Find active conversation for lead or create a new one."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.lead_id == lead.id,
            Conversation.channel == channel,
            Conversation.status == "active",
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        lead_id=lead.id,
        client_id=lead.client_id,
        agency_id=lead.agency_id,
        channel=channel,
    )
    db.add(conv)
    await db.flush()
    return conv


async def _process_inbound_message(
    client_id: uuid.UUID,
    channel: str,
    external_id: str,
    content: str,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    raw_metadata: dict | None = None,
) -> dict:
    """
    Core inbound processing:
    1. Find client
    2. Get/create lead
    3. Get/create conversation
    4. Store inbound message
    5. Trigger agent pipeline (async via Celery in production, inline for M1)
    """
    async with async_session_factory() as db:
        # 1. Find client
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client or not client.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Client not found or inactive"
            )

        # 2. Get or create lead
        lead = await _get_or_create_lead(
            db, client, external_id, channel, name=name, email=email, phone=phone
        )

        # 3. Get or create conversation
        conversation = await _get_or_create_conversation(db, lead, channel)

        # 4. Store inbound message
        message = Message(
            conversation_id=conversation.id,
            client_id=client.id,
            agency_id=client.agency_id,
            direction="inbound",
            sender_type="lead",
            content=content,
            metadata_=raw_metadata or {},
            status="sent",
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        await db.refresh(lead)
        await db.refresh(conversation)

        # 5. Trigger agent pipeline
        # M2: Full supervisor pipeline with all agents
        from app.agents.supervisor import run_full_pipeline
        pipeline_result = await run_full_pipeline(
            conversation_id=conversation.id,
            message_id=message.id,
            client_id=client.id,
            agency_id=client.agency_id,
        )

        return {
            "status": "processed",
            "lead_id": str(lead.id),
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "agent_decision": pipeline_result.get("decision", "unknown"),
            "agent_run_id": pipeline_result.get("agent_run_id"),
        }


@router.post("/form/{client_slug}")
async def web_form_webhook(client_slug: str, data: WebFormLead):
    """
    Generic web form webhook.
    Agencies embed a form that POSTs here.
    """
    # Find client by slug
    async with async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.slug == client_slug))
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
            )
        client_id = client.id

    # Determine external_id
    external_id = data.email or data.phone or f"webform-{uuid.uuid4().hex[:8]}"

    return await _process_inbound_message(
        client_id=client_id,
        channel="web_form",
        external_id=external_id,
        content=data.message,
        name=data.name,
        email=data.email,
        phone=data.phone,
        raw_metadata=data.metadata,
    )


async def _find_client_by_twilio_number(
    db: AsyncSession,
    to_phone: str,
    channel: str,
) -> Client | None:
    """Look up active client matching a Twilio phone number in their channel_config."""
    clean_phone = to_phone.replace("whatsapp:", "").strip()

    if channel == "whatsapp":
        # Check both with and without "whatsapp:" prefix
        stmt = select(Client).where(
            Client.is_active == True,  # noqa: E712
            (Client.channel_config["twilio_whatsapp_from"].astext == to_phone) |
            (Client.channel_config["twilio_whatsapp_from"].astext == clean_phone)
        )
    else:
        stmt = select(Client).where(
            Client.is_active == True,  # noqa: E712
            (Client.channel_config["twilio_sms_from"].astext == to_phone) |
            (Client.channel_config["twilio_sms_from"].astext == clean_phone)
        )

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("/twilio/whatsapp")
async def twilio_whatsapp_webhook(request: Request):
    """Twilio WhatsApp webhook — parses inbound, verifies signature, runs pipeline."""
    from app.config import settings
    from app.services.channels import parse_twilio_whatsapp, verify_twilio_signature

    form_data = await request.form()
    form_dict = dict(form_data)

    parsed = parse_twilio_whatsapp(form_dict)
    to_phone = form_dict.get("To", "")

    async with async_session_factory() as db:
        client = await _find_client_by_twilio_number(db, to_phone, channel="whatsapp")
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No client configured for Twilio WhatsApp number: {to_phone}",
            )

        # Verify Twilio signature if configured
        signature = request.headers.get("X-Twilio-Signature")
        auth_token = client.channel_config.get("twilio_auth_token")
        if signature and auth_token and settings.environment != "test":
            url = str(request.url)
            if not verify_twilio_signature(url, form_dict, signature, auth_token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Twilio signature",
                )

        client_id = client.id

    return await _process_inbound_message(
        client_id=client_id,
        channel="whatsapp",
        external_id=parsed["external_id"],
        content=parsed["content"],
        name=parsed.get("name"),
        phone=parsed.get("phone"),
        raw_metadata=parsed["raw"],
    )


@router.post("/twilio/sms")
async def twilio_sms_webhook(request: Request):
    """Twilio SMS webhook — parses inbound, verifies signature, runs pipeline."""
    from app.config import settings
    from app.services.channels import parse_twilio_sms, verify_twilio_signature

    form_data = await request.form()
    form_dict = dict(form_data)

    parsed = parse_twilio_sms(form_dict)
    to_phone = form_dict.get("To", "")

    async with async_session_factory() as db:
        client = await _find_client_by_twilio_number(db, to_phone, channel="sms")
        if not client:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No client configured for Twilio SMS number: {to_phone}",
            )

        # Verify Twilio signature if configured
        signature = request.headers.get("X-Twilio-Signature")
        auth_token = client.channel_config.get("twilio_auth_token")
        if signature and auth_token and settings.environment != "test":
            url = str(request.url)
            if not verify_twilio_signature(url, form_dict, signature, auth_token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Twilio signature",
                )

        client_id = client.id

    return await _process_inbound_message(
        client_id=client_id,
        channel="sms",
        external_id=parsed["external_id"],
        content=parsed["content"],
        phone=parsed.get("phone"),
        raw_metadata=parsed["raw"],
    )
