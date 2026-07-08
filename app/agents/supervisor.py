"""
Supervisor Agent — the orchestrator.

Runs the full pipeline:
  1. Classify (intent, urgency, language)
  2. KB Search (retrieve grounding facts)
  3. Qualify (score lead, generate qualifying questions)
  4. Respond (draft reply using KB facts + brand voice)
  5. Critic (verify grounding, never-say, brand voice)
  6. CRM Log (structured interaction record)
  7. Schedule (if booking intent detected)
  8. Follow-up (if lead goes silent)

Decision matrix:
  - Kill switch ON → BLOCK
  - Shadow mode → always DRAFT
  - Critic rejects → ESCALATE
  - High-risk topic → ESCALATE
  - Confidence < threshold → SAFE SCRIPT or ESCALATE
  - All clear → SEND (full_auto) or DRAFT (suggest_only)
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select

from app.agents.classifier import ClassifierAgent
from app.agents.critic import CriticAgent
from app.agents.crm_logger import CRMLoggerAgent, CRMLogInput
from app.agents.kb_agent import KBAgent
from app.agents.llm import LLMProvider, get_llm_provider
from app.agents.qualifier import QualifierAgent
from app.agents.responder import ResponderAgent
from app.agents.scheduler import SchedulerAgent, SchedulerInput
from app.agents.schemas import (
    ClassifierInput,
    ClassifierOutput,
    CriticInput,
    CriticOutput,
    KBQueryInput,
    KBQueryOutput,
    QualifierInput,
    QualifierOutput,
    ResponderInput,
    ResponderOutput,
)
from app.database import async_session_factory
from app.models.agent_run import AgentRun
from app.models.client import Client
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message


async def run_full_pipeline(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    client_id: uuid.UUID,
    agency_id: uuid.UUID,
    llm: LLMProvider | None = None,
) -> dict:
    """
    Full M2 Pipeline — Supervisor orchestrating all agents.

    Returns:
        dict with decision, agent_run_id, draft message, and full trace.
    """
    start_time = time.monotonic()
    steps: list[dict] = []
    total_tokens = 0
    total_cost = 0.0
    policy_flags: list[str] = []

    from app.services.observability import ObservabilityTracer
    tracer = ObservabilityTracer(run_id=message_id, trace_name="supervisor_pipeline")

    llm = llm or get_llm_provider()

    async with async_session_factory() as db:
        # ─── Load Context ────────────────────────────────────────
        conversation = await _load_one(db, Conversation, conversation_id)
        if not conversation:
            return _error("Conversation not found")

        inbound_message = await _load_one(db, Message, message_id)
        if not inbound_message:
            return _error("Message not found")

        client = await _load_one(db, Client, client_id)
        if not client:
            return _error("Client not found")

        # ─── Kill Switch ─────────────────────────────────────────
        if client.kill_switch:
            return await _log_and_return(
                db, conversation_id, client_id, agency_id, message_id,
                decision="block", confidence=1.0, steps=[],
                policy_flags=["kill_switch_active"], draft_message="",
                start_time=start_time, tracer=tracer,
            )

        # ─── Conversation History ────────────────────────────────
        history = await _get_history(db, conversation_id, limit=15)

        # ─── Step 1: CLASSIFY ────────────────────────────────────
        classifier = ClassifierAgent(llm=llm)
        cls_input = ClassifierInput(
            message=inbound_message.content,
            conversation_history=history,
        )
        cls_output, cls_step = await classifier.run(cls_input)
        steps.append(cls_step.model_dump())
        total_tokens += cls_step.tokens_in + cls_step.tokens_out
        total_cost += cls_step.cost_cents

        tracer.log_span(
            span_name="Classifier",
            input_data=cls_input.model_dump(),
            output_data=cls_output.model_dump() if cls_output else {},
            latency_ms=cls_step.duration_ms,
            tokens_in=cls_step.tokens_in,
            tokens_out=cls_step.tokens_out,
            cost_cents=cls_step.cost_cents,
        )

        if cls_output and isinstance(cls_output, ClassifierOutput):
            cls_result = cls_output
        else:
            cls_result = ClassifierOutput(
                intent="inquiry", urgency="medium", language="en", confidence=0.5
            )

        # Spam → block immediately
        if cls_result.intent == "spam":
            policy_flags.append("blocked:spam")
            return await _log_and_return(
                db, conversation_id, client_id, agency_id, message_id,
                decision="block", confidence=cls_result.confidence, steps=steps,
                policy_flags=policy_flags, draft_message="",
                start_time=start_time, tracer=tracer,
            )

        # ─── Step 2: KB SEARCH ───────────────────────────────────
        kb_agent = KBAgent(llm=llm)
        kb_input = KBQueryInput(
            query=inbound_message.content,
            client_id=str(client_id),
            max_results=5,
        )
        kb_output, kb_step = await kb_agent.run(kb_input)
        steps.append(kb_step.model_dump())
        total_tokens += kb_step.tokens_in + kb_step.tokens_out
        total_cost += kb_step.cost_cents

        tracer.log_span(
            span_name="KnowledgeBase",
            input_data=kb_input.model_dump(),
            output_data=kb_output.model_dump() if kb_output else {},
            latency_ms=kb_step.duration_ms,
            tokens_in=kb_step.tokens_in,
            tokens_out=kb_step.tokens_out,
            cost_cents=kb_step.cost_cents,
        )

        kb_facts = []
        if kb_output and isinstance(kb_output, KBQueryOutput):
            kb_facts = kb_output.facts

        # ─── Step 3: QUALIFY ─────────────────────────────────────
        qualifier = QualifierAgent(llm=llm)
        qual_criteria = client.autonomy_config.get("qualification_criteria", [])
        qual_input = QualifierInput(
            lead_data={
                "source_channel": getattr(conversation, "channel", "unknown"),
                "intent": cls_result.intent,
                "urgency": cls_result.urgency,
            },
            conversation_history=history,
            qualification_criteria=qual_criteria,
        )
        qual_output, qual_step = await qualifier.run(
            qual_input,
            context={
                "client_name": client.business_name,
                "qualification_criteria": qual_criteria,
            },
        )
        steps.append(qual_step.model_dump())
        total_tokens += qual_step.tokens_in + qual_step.tokens_out
        total_cost += qual_step.cost_cents

        tracer.log_span(
            span_name="Qualifier",
            input_data=qual_input.model_dump(),
            output_data=qual_output.model_dump() if qual_output else {},
            latency_ms=qual_step.duration_ms,
            tokens_in=qual_step.tokens_in,
            tokens_out=qual_step.tokens_out,
            cost_cents=qual_step.cost_cents,
        )

        qualifier_questions = []
        lead_score = 0.5
        if qual_output and isinstance(qual_output, QualifierOutput):
            qualifier_questions = qual_output.questions_to_ask
            lead_score = qual_output.lead_score

        # ─── Step 4: RESPOND ─────────────────────────────────────
        responder = ResponderAgent(llm=llm)
        resp_input = ResponderInput(
            conversation_history=history,
            lead_message=inbound_message.content,
            classifier_output=cls_result,
            kb_facts=kb_facts,
            brand_voice=client.brand_voice,
            client_name=client.business_name,
            qualifier_questions=qualifier_questions,
        )
        resp_output, resp_step = await responder.run(
            resp_input,
            context={
                "client_name": client.business_name,
                "brand_voice": client.brand_voice,
            },
        )
        steps.append(resp_step.model_dump())
        total_tokens += resp_step.tokens_in + resp_step.tokens_out
        total_cost += resp_step.cost_cents

        tracer.log_span(
            span_name="Responder",
            input_data=resp_input.model_dump(),
            output_data=resp_output.model_dump() if resp_output else {},
            latency_ms=resp_step.duration_ms,
            tokens_in=resp_step.tokens_in,
            tokens_out=resp_step.tokens_out,
            cost_cents=resp_step.cost_cents,
        )

        draft_message = ""
        if resp_output and isinstance(resp_output, ResponderOutput):
            draft_message = resp_output.message
        else:
            draft_message = "Thank you for reaching out! A team member will be with you shortly."

        # ─── Step 5: CRITIC ──────────────────────────────────────
        critic = CriticAgent(llm=llm)
        critic_input = CriticInput(
            draft_message=draft_message,
            brand_voice=client.brand_voice,
            never_say_list=client.never_say_list,
            kb_facts=kb_facts,
            conversation_history=history,
            classifier_output=cls_result,
        )
        critic_output, critic_step = await critic.run(
            critic_input,
            context={
                "brand_voice": client.brand_voice,
                "never_say_list": client.never_say_list,
                "kb_facts": [f.model_dump() for f in kb_facts] if kb_facts else [],
            },
        )
        steps.append(critic_step.model_dump())
        total_tokens += critic_step.tokens_in + critic_step.tokens_out
        total_cost += critic_step.cost_cents

        tracer.log_span(
            span_name="Critic",
            input_data=critic_input.model_dump(),
            output_data=critic_output.model_dump() if critic_output else {},
            latency_ms=critic_step.duration_ms,
            tokens_in=critic_step.tokens_in,
            tokens_out=critic_step.tokens_out,
            cost_cents=critic_step.cost_cents,
        )

        critic_approved = True
        critic_confidence = 1.0
        if critic_output and isinstance(critic_output, CriticOutput):
            critic_approved = critic_output.approved
            critic_confidence = critic_output.confidence

            # Meta-Debugger trigger: self-healing re-evaluation
            if not critic_approved:
                try:
                    from app.agents.meta_debugger import MetaDebuggerAgent, DebuggerInput
                    debugger = MetaDebuggerAgent(llm=llm)
                    dbg_input = DebuggerInput(
                        original_prompt=client.brand_voice,
                        draft_message=draft_message,
                        critic_feedback=", ".join([i.description for i in critic_output.issues]),
                        conversation_history=history,
                    )
                    dbg_output, dbg_step = await debugger.run(dbg_input)
                    steps.append(dbg_step.model_dump())
                    total_tokens += dbg_step.tokens_in + dbg_step.tokens_out
                    total_cost += dbg_step.cost_cents

                    tracer.log_span(
                        span_name="MetaDebugger",
                        input_data=dbg_input.model_dump(),
                        output_data=dbg_output.model_dump() if dbg_output else {},
                        latency_ms=dbg_step.duration_ms,
                        tokens_in=dbg_step.tokens_in,
                        tokens_out=dbg_step.tokens_out,
                        cost_cents=dbg_step.cost_cents,
                    )

                    if dbg_output.approved_for_retry:
                        # Re-run responder agent with healed instructions injected into brand voice!
                        healed_brand_voice = f"{client.brand_voice}\n[Correction Override]: {dbg_output.instruction_override}"
                        resp_input.brand_voice = healed_brand_voice

                        resp_output, resp_step = await responder.run(
                            resp_input,
                            context={
                                "client_name": client.business_name,
                                "brand_voice": healed_brand_voice,
                            },
                        )
                        steps.append(resp_step.model_dump())
                        total_tokens += resp_step.tokens_in + resp_step.tokens_out
                        total_cost += resp_step.cost_cents

                        tracer.log_span(
                            span_name="ResponderHealed",
                            input_data=resp_input.model_dump(),
                            output_data=resp_output.model_dump() if resp_output else {},
                            latency_ms=resp_step.duration_ms,
                            tokens_in=resp_step.tokens_in,
                            tokens_out=resp_step.tokens_out,
                            cost_cents=resp_step.cost_cents,
                        )

                        if resp_output and isinstance(resp_output, ResponderOutput):
                            draft_message = resp_output.message

                            # Re-run critic on the healed draft message
                            critic_input.draft_message = draft_message
                            critic_output, critic_step = await critic.run(
                                critic_input,
                                context={
                                    "brand_voice": healed_brand_voice,
                                    "never_say_list": client.never_say_list,
                                    "kb_facts": [f.model_dump() for f in kb_facts] if kb_facts else [],
                                },
                            )
                            steps.append(critic_step.model_dump())
                            total_tokens += critic_step.tokens_in + critic_step.tokens_out
                            total_cost += critic_step.cost_cents

                            tracer.log_span(
                                span_name="CriticHealed",
                                input_data=critic_input.model_dump(),
                                output_data=critic_output.model_dump() if critic_output else {},
                                latency_ms=critic_step.duration_ms,
                                tokens_in=critic_step.tokens_in,
                                tokens_out=critic_step.tokens_out,
                                cost_cents=critic_step.cost_cents,
                            )

                            if critic_output and isinstance(critic_output, CriticOutput):
                                critic_approved = critic_output.approved
                                critic_confidence = critic_output.confidence
                except Exception as e:
                    import logging
                    logging.getLogger("operdai.supervisor").error(f"Meta-Debugger healing failed: {e}")

            if not critic_approved:
                for issue in critic_output.issues:
                    policy_flags.append(f"critic:{issue.type}:{issue.severity}")

        # ─── Step 6: CRM LOG ─────────────────────────────────────
        crm_logger = CRMLoggerAgent(llm=llm)
        crm_input = CRMLogInput(
            lead_id=str(conversation.lead_id),
            conversation_id=str(conversation_id),
            lead_message=inbound_message.content,
            agent_response=draft_message,
            classifier_intent=cls_result.intent,
            classifier_urgency=cls_result.urgency,
            qualification_score=lead_score,
            confidence=cls_result.confidence,
            conversation_history=history,
        )
        crm_output, crm_step = await crm_logger.run(crm_input)
        steps.append(crm_step.model_dump())
        total_tokens += crm_step.tokens_in + crm_step.tokens_out
        total_cost += crm_step.cost_cents

        # ─── Step 7: SCHEDULER (conditional) ─────────────────────
        if cls_result.intent == "booking_request":
            # Call Consensus validation for booking action
            try:
                from app.services.consensus import ConsensusCoordinator
                coordinator = ConsensusCoordinator()
                proposed = {
                    "start_time": "2026-06-30T10:00:00Z",
                    "lead_id": str(conversation.lead_id),
                }
                consensus_res = await coordinator.evaluate_action(
                    action_type="confirm_booking",
                    proposed_payload=proposed,
                    conversation_history=history,
                )
                if consensus_res["decision"] != "approved":
                    policy_flags.append("consensus_failed:booking_quorum")
            except Exception as e:
                import logging
                logging.getLogger("operdai.supervisor").error(f"Consensus evaluation failed: {e}")

            scheduler = SchedulerAgent(llm=llm)
            sched_input = SchedulerInput(
                lead_name=None,  # Would come from lead profile
                conversation_history=history,
                lead_message=inbound_message.content,
                available_slots=[],  # Would come from calendar API
                timezone="UTC",
            )
            sched_output, sched_step = await scheduler.run(
                sched_input,
                context={
                    "client_name": client.business_name,
                    "available_slots": [],
                    "meeting_duration_minutes": 30,
                },
            )
            steps.append(sched_step.model_dump())
            total_tokens += sched_step.tokens_in + sched_step.tokens_out
            total_cost += sched_step.cost_cents

        # ─── DECISION ENGINE ─────────────────────────────────────
        autonomy = client.autonomy_config
        mode = autonomy.get("mode", "suggest_only")
        threshold = autonomy.get("confidence_threshold", 0.85)
        high_risk_topics = autonomy.get("high_risk_topics", [])

        # Aggregate confidence = min(classifier, critic)
        confidence = min(cls_result.confidence, critic_confidence)

        # Check high-risk
        is_high_risk = cls_result.intent in high_risk_topics or any(
            topic in inbound_message.content.lower() for topic in high_risk_topics
        )
        if is_high_risk:
            policy_flags.append(f"high_risk_topic:{cls_result.intent}")

        # Decision matrix
        if client.shadow_mode:
            decision = "draft"
            message_status = "draft"
        elif not critic_approved:
            decision = "escalate"
            message_status = "draft"
            policy_flags.append("escalated:critic_rejected")
        elif is_high_risk:
            decision = "escalate"
            message_status = "draft"
            policy_flags.append("escalated:high_risk")
        elif confidence < threshold:
            if mode == "full_auto":
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
        elif mode == "auto_with_approval":
            decision = "pending_approval"
            message_status = "draft"
        else:
            decision = "send"
            message_status = "sent"

        # ─── Store Outbound Message ──────────────────────────────
        outbound = Message(
            conversation_id=conversation_id,
            client_id=client_id,
            agency_id=agency_id,
            direction="outbound",
            sender_type="agent",
            content=draft_message,
            metadata_={
                "confidence": confidence,
                "intent": cls_result.intent,
                "urgency": cls_result.urgency,
                "lead_score": lead_score,
                "critic_approved": critic_approved,
                "decision": decision,
                "agent_steps": len(steps),
            },
            status=message_status,
        )
        db.add(outbound)

        # Update lead status if applicable
        lead = await _load_one(db, Lead, conversation.lead_id)
        if lead:
            if lead.status == "new" and decision in ("send", "draft", "pending_approval"):
                lead.status = "contacted"
            if lead_score >= 0.6 and lead.status in ("new", "contacted"):
                lead.status = "qualified"
            lead.score = lead_score

        # ─── Log Agent Run ───────────────────────────────────────
        return await _log_and_return(
            db, conversation_id, client_id, agency_id, message_id,
            decision=decision, confidence=confidence, steps=steps,
            policy_flags=policy_flags, draft_message=draft_message,
            start_time=start_time, total_tokens=total_tokens,
            total_cost=total_cost, lead_score=lead_score,
            critic_approved=critic_approved,
            intent=cls_result.intent, urgency=cls_result.urgency,
            message_status=message_status, tracer=tracer,
        )


# ═══════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════

async def _load_one(db, model, record_id):
    result = await db.execute(select(model).where(model.id == record_id))
    return result.scalar_one_or_none()


async def _get_history(db, conversation_id, limit=15):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return [
        {"role": "lead" if m.direction == "inbound" else "agent", "content": m.content}
        for m in reversed(messages)
    ]


def _error(msg: str) -> dict:
    return {"decision": "error", "error": msg}


async def _log_and_return(
    db, conversation_id, client_id, agency_id, message_id,
    decision, confidence, steps, policy_flags, draft_message,
    start_time, total_tokens=0, total_cost=0.0, tracer=None, **extra,
) -> dict:
    if tracer:
        try:
            tracer.export()
        except Exception as te:
            import logging
            logging.getLogger("operdai.supervisor").error(f"Failed to export telemetry: {te}")

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

    # Log usage in billing system
    try:
        from app.services.billing import log_usage
        # Count inbound messages in this conversation to determine if it's a new lead
        msg_count_stmt = select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id,
            Message.direction == "inbound",
        )
        msg_count_res = await db.execute(msg_count_stmt)
        inbound_count = msg_count_res.scalar() or 0
        is_new = inbound_count <= 1

        sent_outbound = decision in ("send", "script_fallback")

        await log_usage(
            db=db,
            agency_id=agency_id,
            client_id=client_id,
            tokens=total_tokens,
            cost_cents=int(total_cost * 100),
            message_sent=sent_outbound,
            is_new_lead=is_new,
        )
    except Exception as e:
        import logging
        logging.getLogger("operdai.supervisor").error(f"Failed to log billing usage: {e}")

    # Fire escalation notification if decision is escalate
    if decision == "escalate":
        try:
            from app.models.conversation import Conversation
            from app.models.lead import Lead
            from app.models.user import User
            from app.services.notifications import send_escalation_notification

            # Look up admin email, client name, and lead name
            admin_stmt = select(User).where(User.agency_id == agency_id, User.role == "agency_admin")
            admin_res = await db.execute(admin_stmt)
            admin_user = admin_res.scalar_one_or_none()
            admin_email = admin_user.email if admin_user else "alerts@operdai.com"

            client_result = await db.execute(select(Client).where(Client.id == client_id))
            client = client_result.scalar_one_or_none()
            client_name = client.business_name if client else "Client Workspace"

            conv_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
            conv = conv_result.scalar_one_or_none()
            lead_name = "Lead"
            if conv:
                lead_result = await db.execute(select(Lead).where(Lead.id == conv.lead_id))
                lead = lead_result.scalar_one_or_none()
                if lead:
                    lead_name = lead.name or lead.external_id

            reason = ", ".join(policy_flags) if policy_flags else "Confidence threshold / safety trigger."

            # Run notification trigger asynchronously
            import asyncio
            asyncio.create_task(
                send_escalation_notification(
                    client_name=client_name,
                    lead_name=lead_name,
                    reason=reason,
                    draft_content=draft_message,
                    recipient_email=admin_email,
                )
            )
        except Exception as e:
            import logging
            logging.getLogger("operdai.supervisor").error(f"Failed to trigger escalation notification: {e}")

    return {
        "decision": decision,
        "agent_run_id": str(agent_run.id),
        "confidence": confidence,
        "draft_message": draft_message,
        "policy_flags": policy_flags,
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
        "agent_steps": len(steps),
        **extra,
    }
