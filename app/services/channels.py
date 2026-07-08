"""
Channel Service — abstraction for sending outbound messages across all channels.

Supports: Web form response (via stored message), WhatsApp (Twilio), SMS (Twilio).
"""

from __future__ import annotations

import hashlib
import hmac
from enum import Enum

from pydantic import BaseModel


class Channel(str, Enum):
    WEB_FORM = "web_form"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    EMAIL = "email"


class OutboundMessage(BaseModel):
    """Standardized outbound message."""
    channel: Channel
    recipient: str  # Phone number, email, or external_id
    content: str
    metadata: dict = {}


class ChannelResult(BaseModel):
    """Result of sending an outbound message."""
    success: bool
    channel: str
    message_sid: str | None = None  # Twilio message SID
    error: str | None = None


class TwilioConfig(BaseModel):
    account_sid: str = ""
    auth_token: str = ""
    whatsapp_from: str = ""  # e.g., "whatsapp:+14155238886"
    sms_from: str = ""       # e.g., "+15558675310"


def verify_twilio_signature(
    url: str,
    params: dict[str, str],
    signature: str,
    auth_token: str,
) -> bool:
    """
    Verify Twilio webhook signature to prevent spoofing.
    https://www.twilio.com/docs/usage/security#validating-requests
    """
    # Build the data string
    data = url
    for key in sorted(params.keys()):
        data += key + params[key]

    # Compute HMAC-SHA1
    computed = hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    ).digest()

    import base64
    expected = base64.b64encode(computed).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def parse_twilio_whatsapp(form_data: dict[str, str]) -> dict:
    """Parse Twilio WhatsApp webhook form data into our format."""
    from_number = form_data.get("From", "").replace("whatsapp:", "")
    return {
        "external_id": from_number,
        "content": form_data.get("Body", ""),
        "channel": "whatsapp",
        "phone": from_number,
        "name": form_data.get("ProfileName"),
        "num_media": int(form_data.get("NumMedia", "0")),
        "message_sid": form_data.get("MessageSid", ""),
        "raw": dict(form_data),
    }


def parse_twilio_sms(form_data: dict[str, str]) -> dict:
    """Parse Twilio SMS webhook form data into our format."""
    from_number = form_data.get("From", "")
    return {
        "external_id": from_number,
        "content": form_data.get("Body", ""),
        "channel": "sms",
        "phone": from_number,
        "message_sid": form_data.get("MessageSid", ""),
        "raw": dict(form_data),
    }


async def send_twilio_message(
    to: str,
    body: str,
    channel: Channel,
    twilio_config: TwilioConfig,
) -> ChannelResult:
    """
    Send a message via Twilio (WhatsApp or SMS).

    In production, use the Twilio Python SDK.
    This implementation uses httpx for zero-dependency flexibility.
    """
    import httpx

    if not twilio_config.account_sid or not twilio_config.auth_token:
        return ChannelResult(
            success=False, channel=channel.value,
            error="Twilio credentials not configured",
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_config.account_sid}/Messages.json"

    if channel == Channel.WHATSAPP:
        from_number = twilio_config.whatsapp_from
        to_number = f"whatsapp:{to}" if not to.startswith("whatsapp:") else to
    else:
        from_number = twilio_config.sms_from
        to_number = to

    data = {
        "From": from_number,
        "To": to_number,
        "Body": body,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                data=data,
                auth=(twilio_config.account_sid, twilio_config.auth_token),
            )
            if response.status_code in (200, 201):
                result = response.json()
                return ChannelResult(
                    success=True,
                    channel=channel.value,
                    message_sid=result.get("sid"),
                )
            else:
                return ChannelResult(
                    success=False,
                    channel=channel.value,
                    error=f"Twilio error: {response.status_code} - {response.text[:200]}",
                )
    except Exception as e:
        return ChannelResult(
            success=False, channel=channel.value, error=str(e),
        )


async def send_outbound(
    message: OutboundMessage,
    client_channel_config: dict,
) -> ChannelResult:
    """
    Send an outbound message through the appropriate channel.
    Uses the client's channel_config for credentials.
    """
    if message.channel in (Channel.WHATSAPP, Channel.SMS):
        twilio_cfg = TwilioConfig(
            account_sid=client_channel_config.get("twilio_account_sid", ""),
            auth_token=client_channel_config.get("twilio_auth_token", ""),
            whatsapp_from=client_channel_config.get("twilio_whatsapp_from", ""),
            sms_from=client_channel_config.get("twilio_sms_from", ""),
        )
        return await send_twilio_message(
            to=message.recipient,
            body=message.content,
            channel=message.channel,
            twilio_config=twilio_cfg,
        )
    elif message.channel == Channel.WEB_FORM:
        # Web form responses are stored in DB — no outbound push needed
        return ChannelResult(success=True, channel="web_form")
    else:
        return ChannelResult(
            success=False, channel=message.channel,
            error=f"Unsupported channel: {message.channel}",
        )
