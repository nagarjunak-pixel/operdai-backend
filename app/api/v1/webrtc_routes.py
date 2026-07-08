"""WebRTC API Router — exposes audio gateway connections and verbal triggers."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_current_user, get_tenant_db
from app.models.user import User
from app.services.webrtc import initiate_voice_session, handle_verbal_trigger

router = APIRouter(prefix="/webrtc", tags=["webrtc"])


class VoiceTriggerRequest(BaseModel):
    client_id: uuid.UUID
    agency_id: uuid.UUID
    conversation_id: uuid.UUID
    transcript: str


@router.post("/session")
async def create_voice_session(
    client_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    """Initiates WebRTC streaming connection credentials."""
    return await initiate_voice_session(client_id)


@router.post("/trigger")
async def trigger_voice_response(
    body: VoiceTriggerRequest,
    user: User = Depends(get_current_user),
):
    """Submits incoming verbal transcript and returns synthesizable speech text."""
    return await handle_verbal_trigger(
        client_id=body.client_id,
        agency_id=body.agency_id,
        conversation_id=body.conversation_id,
        transcript=body.transcript,
    )
