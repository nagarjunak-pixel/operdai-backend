"""WebRTC Voice Gateway Service — handles audio streaming connection tokens and speech pipelines."""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger("operdai.webrtc")


async def initiate_voice_session(client_id: uuid.UUID) -> dict:
    """Generate mock WebRTC/LiveKit access tokens and ICE servers for audio sessions."""
    session_id = str(uuid.uuid4())
    logger.info(f"Initiated WebRTC session {session_id} for client {client_id}")

    return {
        "status": "connected",
        "session_id": session_id,
        "token": f"livekit-token-{session_id[:8]}",
        "ice_servers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "turn:turn.operd.ai:3478", "username": "operd", "credential": "key"},
        ],
    }


async def handle_verbal_trigger(
    client_id: uuid.UUID,
    agency_id: uuid.UUID,
    conversation_id: uuid.UUID,
    transcript: str,
) -> dict:
    """
    Processes spoken text transcript (Speech-to-Text), runs supervisor pipeline,
    and returns textual result prepared for Text-to-Speech (TTS) engine.
    """
    from app.agents.supervisor import run_full_pipeline
    from app.database import async_session_factory
    from app.models.message import Message

    # 1. Insert incoming transcript message
    async with async_session_factory() as db:
        msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            client_id=client_id,
            agency_id=agency_id,
            direction="inbound",
            sender_type="lead",
            content=transcript,
        )
        db.add(msg)
        await db.commit()

        # 2. Run supervisor
        from app.agents.llm import get_llm_provider
        llm = get_llm_provider(mock=True)
        res = await run_full_pipeline(
            conversation_id=conversation_id,
            message_id=msg.id,
            client_id=client_id,
            agency_id=agency_id,
            llm=llm,
        )

        decision = res.get("decision", "escalate")
        draft = res.get("draft_message", "I will get a representative to help you with that.")

        return {
            "session_id": str(conversation_id),
            "transcript_received": transcript,
            "tts_output": draft,
            "decision": decision,
        }
