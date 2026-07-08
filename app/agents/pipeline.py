"""
Agent Pipeline — M1 simplified pipeline: Classify → Respond → Log trace.

In M2, the Supervisor agent will orchestrate all workers.
For M1, we run a hardcoded Classify → Respond sequence.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select

from app.agents.classifier import ClassifierAgent
from app.agents.llm import get_llm_provider
from app.agents.responder import ResponderAgent
from app.agents.schemas import (
    ClassifierInput,
    ClassifierOutput,
    ResponderInput,
    ResponderOutput,
)
from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.client import Client
from app.models.conversation import Conversation
from app.models.message import Message


async def run_agent_pipeline(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    client_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> dict:
    """
    M1 Pipeline: Classify → Respond → Log trace.

    Returns dict with decision, agent_run_id, and draft message.
    """
    start_time = time.monotonic()
    steps: list[dict] = []
    total_tokens = 0
    total_cost = 0.0

    llm = get_llm_provider()

    async with async_session_factory() as db:
        # Load context
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            return {"decision": "error", "error": "Conversation not found"}

        msg_result = await db.execute(
            select(Message).where(Message.id == message_id)
        )
        inbound_message = msg_result.scalar_one_or_none()
        if not inbound_message:
            return {"decision": "error", "error": "Message not found"}

        client_result = await db.execute(
            select(Client).where(Client.id == client_id)
        )
        client = client_result.scalar_one_or_none()
        if not client:
            return {"decision": "error", "error": "Client not found"}

        # Check kill switch
        if client.kill_switch:
            agent_run = AgentRun(
                conversation_id=conversation_id,
                client_id=client_id,
                agency_id=agency_id,
                trigger_message_id=message_id,
                status="completed",
                steps=[],
                decision="block",
                confidence_score=1.0,
                policy_flags=["kill_switch_active"],
                total_tokens=0,
                total_cost_cents=0,
                duration_ms=0,
            )
            db.add(agent_run)
            await db.commit()
            return {
                "decision": "block",
                "agent_run_id": str(agent_run.id),
                "reason": "Kill switch is active",
            }

        # Get conversation history
        msgs_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(10)
        )
        recent_messages = msgs_result.scalars().all()
        history = [
            {"role": "lead" if m.direction == "inbound" else "agent", "content": m.content}
            for m in reversed(recent_messages)
        ]

        # === Step 1: Classify ===
        classifier = ClassifierAgent(llm=llm)
        classifier_input = ClassifierInput(
            message=inbound_message.content,
            conversation_history=history,
        )
        classifier_output, classifier_step = await classifier.run(classifier_input)
        steps.append(classifier_step.model_dump())
        total_tokens += classifier_step.tokens_in + classifier_step.tokens_out
        total_cost += classifier_step.cost_cents

        # Use the parsed output or create a default
        if classifier_output and isinstance(classifier_output, ClassifierOutput):
            cls_out = classifier_output
        else:
            cls_out = ClassifierOutput(
                intent="inquiry", urgency="medium", language="en", confidence=0.5
            )

        # === Step 2: Respond ===
        responder = ResponderAgent(llm=llm)
        responder_input = ResponderInput(
            conversation_history=history,
            lead_message=inbound_message.content,
            classifier_output=cls_out,
            kb_facts=[],  # M1: no KB yet
            brand_voice=client.brand_voice,
            client_name=client.business_name,
        )
        responder_output, responder_step = await responder.run(
            responder_input,
            context={
                "client_name": client.business_name,
                "brand_voice": client.brand_voice,
            },
        )
        steps.append(responder_step.model_dump())
        total_tokens += responder_step.tokens_in + responder_step.tokens_out
        total_cost += responder_step.cost_cents

        # Get draft message
        draft_message = ""
        if responder_output and isinstance(responder_output, ResponderOutput):
            draft_message = responder_output.message
        else:
            draft_message = "Thank you for reaching out! A team member will be with you shortly."

        # === Determine decision ===
        confidence = cls_out.confidence
        autonomy = client.autonomy_config
        mode = autonomy.get("mode", "suggest_only")
        threshold = autonomy.get("confidence_threshold", 0.85)
        high_risk_topics = autonomy.get("high_risk_topics", [])

        # Check for high-risk intent
        is_high_risk = cls_out.intent in high_risk_topics or any(
            topic in inbound_message.content.lower() for topic in high_risk_topics
        )

        policy_flags = []
        if is_high_risk:
            policy_flags.append(f"high_risk_topic:{cls_out.intent}")

        # Decision logic
        if client.shadow_mode:
            decision = "draft"  # Shadow mode: never send
            message_status = "draft"
        elif is_high_risk:
            decision = "escalate"
            message_status = "draft"
            policy_flags.append("escalated:high_risk")
        elif confidence < threshold:
            if mode == "full_auto":
                # Use safe script fallback
                decision = "script_fallback"
                draft_message = client.safe_scripts.get(
                    "greeting_fallback",
                    "Thanks for reaching out! A team member will get back to you shortly."
                )
                message_status = "sent"
            else:
                decision = "escalate"
                message_status = "draft"
                policy_flags.append("escalated:low_confidence")
        elif mode == "suggest_only":
            decision = "draft"
            message_status = "draft"
        else:
            decision = "send"
            message_status = "sent"

        # Store the outbound message
        outbound = Message(
            conversation_id=conversation_id,
            client_id=client_id,
            agency_id=agency_id,
            direction="outbound",
            sender_type="agent",
            content=draft_message,
            metadata_={
                "confidence": confidence,
                "model": classifier_step.model,
                "intent": cls_out.intent,
                "urgency": cls_out.urgency,
                "decision": decision,
            },
            status=message_status,
        )
        db.add(outbound)

        # Update lead status
        if cls_out.intent == "booking_request":
            from app.models.lead import Lead
            lead_result = await db.execute(
                select(Lead).where(Lead.id == conversation.lead_id)
            )
            lead = lead_result.scalar_one_or_none()
            if lead and lead.status == "new":
                lead.status = "contacted"

        # Log agent run
        duration_ms = int((time.monotonic() - start_time) * 1000)
        agent_run = AgentRun(
            conversation_id=conversation_id,
            client_id=client_id,
            agency_id=agency_id,
            trigger_message_id=message_id,
            status="completed",
            steps=steps,
            decision=decision,
            confidence_score=confidence,
            policy_flags=policy_flags,
            total_tokens=total_tokens,
            total_cost_cents=int(total_cost * 100),
            duration_ms=duration_ms,
        )
        db.add(agent_run)
        await db.commit()
        await db.refresh(agent_run)

        return {
            "decision": decision,
            "agent_run_id": str(agent_run.id),
            "confidence": confidence,
            "intent": cls_out.intent,
            "draft_message": draft_message,
            "message_status": message_status,
            "policy_flags": policy_flags,
            "total_tokens": total_tokens,
            "duration_ms": duration_ms,
        }
