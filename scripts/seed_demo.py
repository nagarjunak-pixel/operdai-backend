"""Seed demo data for OperdAI platform.

Creates:
- Platform admin user
- Demo agency "LeadGen Pro" 
- 2 clients (Acme Web Design, Zenith Lawyers)
- Sample KB documents with embeddings
- Sample leads, conversations, messages
- Agent runs with full traces
- Billing config
"""
import asyncio
import uuid
from datetime import datetime, timedelta, UTC

from sqlalchemy import select

from app.database import async_session_factory, Base, engine
from app.models.agency import Agency
from app.models.client import Client
from app.models.user import User
from app.models.lead import Lead
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.agent_run import AgentRun
from app.models.kb import KBDocument, KBChunk
from app.models.billing import BillingConfig, UsageRecord
from app.models.audit import AuditLog
from app.services.auth import AuthService
from app.services.embeddings import ingest_document_chunks


async def seed():
    print("🌱 Seeding OperdAI demo data...")
    
    async with async_session_factory() as db:
        # ─── Platform Admin ──────────────────────────────────────
        existing_admin = await db.execute(
            select(User).where(User.email == "admin@operdai.com")
        )
        if not existing_admin.scalar_one_or_none():
            admin = User(
                email="admin@operdai.com",
                name="OperdAI Admin",
                password_hash=AuthService.hash_password("admin12345"),
                role="platform_admin",
            )
            db.add(admin)
            print("  ✅ Created platform admin: admin@operdai.com / admin12345")

        # ─── Agency ──────────────────────────────────────────────
        existing_agency = await db.execute(
            select(Agency).where(Agency.slug == "leadgen-pro")
        )
        agency = existing_agency.scalar_one_or_none()
        if not agency:
            agency = Agency(
                name="LeadGen Pro",
                slug="leadgen-pro",
                branding={
                    "logo_url": "",
                    "primary_color": "#6366F1",
                    "secondary_color": "#8B5CF6",
                    "accent_color": "#F59E0B",
                    "font_family": "Inter",
                    "email_from_name": "LeadGen Pro",
                    "email_from_address": "hello@leadgenpro.com",
                },
            )
            db.add(agency)
            await db.flush()
            print(f"  ✅ Created agency: {agency.name} ({agency.slug})")

        # ─── Agency Admin User ───────────────────────────────────
        existing_agency_admin = await db.execute(
            select(User).where(User.email == "admin@leadgenpro.com")
        )
        if not existing_agency_admin.scalar_one_or_none():
            agency_admin = User(
                email="admin@leadgenpro.com",
                name="Sarah Agency",
                password_hash=AuthService.hash_password("agency12345"),
                role="agency_admin",
                agency_id=agency.id,
            )
            db.add(agency_admin)
            print("  ✅ Created agency admin: admin@leadgenpro.com / agency12345")

        # ─── Billing Config ──────────────────────────────────────
        existing_billing = await db.execute(
            select(BillingConfig).where(BillingConfig.agency_id == agency.id)
        )
        if not existing_billing.scalar_one_or_none():
            billing = BillingConfig(
                agency_id=agency.id,
                plan_type="growth",
                monthly_lead_cap=500,
                monthly_token_cap=10_000_000,
                cost_per_lead_cents=50,
                alert_threshold_pct=80,
            )
            db.add(billing)

        # ─── Clients ─────────────────────────────────────────────
        existing_clients = await db.execute(
            select(Client).where(Client.agency_id == agency.id)
        )
        existing_client_list = existing_clients.scalars().all()
        
        client_acme = None
        client_zenith = None
        
        for c in existing_client_list:
            if c.slug == "acme-web":
                client_acme = c
            elif c.slug == "zenith-law":
                client_zenith = c
        
        if not client_acme:
            client_acme = Client(
                agency_id=agency.id,
                business_name="Acme Web Design",
                slug="acme-web",
                brand_voice={
                    "tone": "friendly",
                    "style": "professional",
                    "examples": [
                        "Hi there! Thanks for reaching out to us.",
                        "We'd love to help with your project!"
                    ],
                },
                never_say_list={
                    "phrases": ["guaranteed", "100%", "cheapest", "promise"],
                    "topics": ["competitor pricing", "legal advice"],
                },
                autonomy_config={
                    "mode": "suggest_only",
                    "confidence_threshold": 0.85,
                    "high_risk_topics": ["pricing_negotiation", "refund", "legal", "medical"],
                    "max_autonomous_messages_per_lead": 10,
                    "follow_up_cadence": {"delays_hours": [4, 24, 72], "max_follow_ups": 3},
                },
                shadow_mode=True,
                channel_config={
                    "twilio_whatsapp_from": "+15551234567",
                    "twilio_sms_from": "+15551234567",
                },
            )
            db.add(client_acme)
            await db.flush()

        if not client_zenith:
            client_zenith = Client(
                agency_id=agency.id,
                business_name="Zenith Lawyers",
                slug="zenith-law",
                brand_voice={
                    "tone": "formal",
                    "style": "professional",
                    "examples": [
                        "Good day. Thank you for your inquiry.",
                        "Our team will review your matter promptly."
                    ],
                },
                never_say_list={
                    "phrases": ["guaranteed win", "we will definitely", "cheapest rates"],
                    "topics": ["opposing counsel", "judge relationships"],
                },
                autonomy_config={
                    "mode": "suggest_only",
                    "confidence_threshold": 0.90,
                    "high_risk_topics": ["legal", "pricing_negotiation", "refund"],
                    "max_autonomous_messages_per_lead": 5,
                    "follow_up_cadence": {"delays_hours": [24, 48], "max_follow_ups": 2},
                },
                shadow_mode=True,
                channel_config={},
            )
            db.add(client_zenith)
            await db.flush()

        # ─── KB Documents ────────────────────────────────────────
        existing_kb = await db.execute(
            select(KBDocument).where(KBDocument.client_id == client_acme.id)
        )
        if not existing_kb.scalars().all():
            kb1 = KBDocument(
                client_id=client_acme.id,
                agency_id=agency.id,
                title="Pricing & Packages FAQ",
                content="""Acme Web Design packages:

1. Starter Plan ($499/mo) - Basic custom website, 2-week turnaround, 5 pages, responsive design, contact form, basic SEO setup.

2. Growth Plan ($999/mo) - SEO optimization, blog setup, integrations (CRM, email marketing), 10 pages, 3-4 week turnaround, priority support.

3. Enterprise (Custom pricing) - Full custom web applications, portals, e-commerce, dedicated project manager, 8-12 week turnaround.

All plans include: SSL certificate, hosting for 12 months, monthly maintenance, and analytics dashboard.""",
                doc_type="pricing",
            )
            db.add(kb1)
            await db.flush()
            await ingest_document_chunks(db, kb1)

            kb2 = KBDocument(
                client_id=client_acme.id,
                agency_id=agency.id,
                title="Services & Timelines",
                content="""Acme Web Design Services:

Turnaround times:
- Starter plans: 2 weeks from kickoff to launch
- Growth plans: 3-4 weeks from kickoff to launch
- Custom Enterprise builds: 8-12 weeks

All builds include:
- Initial discovery call and requirements gathering
- Wireframing and design mockups (2 rounds of revisions)
- Responsive mobile optimization
- Cross-browser testing
- Performance optimization (target: 90+ PageSpeed score)
- Basic on-page SEO setup
- 30-day post-launch support

Our process:
1. Discovery & Planning (Week 1)
2. Design & Review (Week 1-2)
3. Development (Week 2-3)
4. Testing & Launch (Week 3-4)""",
                doc_type="general",
            )
            db.add(kb2)
            await db.flush()
            await ingest_document_chunks(db, kb2)
            print("  ✅ Created KB documents with embeddings for Acme Web Design")

        # ─── Sample Leads & Conversations ────────────────────────
        existing_leads = await db.execute(
            select(Lead).where(Lead.client_id == client_acme.id)
        )
        if not existing_leads.scalars().all():
            # Lead 1: John Davis - active conversation
            lead1 = Lead(
                client_id=client_acme.id,
                agency_id=agency.id,
                source_channel="whatsapp",
                external_id="+15550192834",
                name="John Davis",
                email="john@davisconsulting.com",
                phone="+15550192834",
                status="qualified",
                qualification_score=0.85,
            )
            db.add(lead1)
            await db.flush()

            conv1 = Conversation(
                lead_id=lead1.id,
                client_id=client_acme.id,
                agency_id=agency.id,
                channel="whatsapp",
                status="active",
            )
            db.add(conv1)
            await db.flush()

            # Messages for conv1
            msgs1 = [
                Message(
                    conversation_id=conv1.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="Hi, I saw your web design services. What are your starting prices?",
                    status="sent",
                    metadata_={},
                ),
                Message(
                    conversation_id=conv1.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="outbound",
                    sender_type="agent",
                    content="Hello John! Thanks for reaching out to Acme Web Design. Our starting package is the Starter plan at $499/mo, which covers a standard website redesign with 5 pages and 2-week delivery. We also offer a Growth plan at $999/mo for larger projects with SEO and integrations. What kind of business website are you looking to build?",
                    status="sent",
                    metadata_={"confidence": 0.94, "intent": "pricing_question", "model": "claude-haiku-4-5"},
                ),
                Message(
                    conversation_id=conv1.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="We need a site for our consulting practice. We need it done by end of July. Can you do that?",
                    status="sent",
                    metadata_={},
                ),
                Message(
                    conversation_id=conv1.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="outbound",
                    sender_type="agent",
                    content="Yes, absolutely! Our standard turnaround time is 2-4 weeks, so completing it by the end of July is fully achievable. I would love to schedule a brief call with our lead designer to discuss your specific requirements. Are you available next Monday at 10 AM or Tuesday at 2 PM?",
                    status="sent",
                    metadata_={"confidence": 0.91, "intent": "booking_request", "model": "claude-haiku-4-5"},
                ),
                Message(
                    conversation_id=conv1.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="Are you available to build this next week?",
                    status="sent",
                    metadata_={},
                ),
            ]
            for m in msgs1:
                db.add(m)

            # Agent run for the last message
            run1 = AgentRun(
                conversation_id=conv1.id,
                client_id=client_acme.id,
                agency_id=agency.id,
                trigger_message_id=msgs1[-1].id,
                status="completed",
                decision="draft",
                confidence_score=0.92,
                policy_flags=[],
                total_tokens=1240,
                total_cost_cents=1,
                duration_ms=2100,
                steps=[
                    {
                        "agent": "classifier",
                        "input_data": {"message": "Are you available to build this next week?"},
                        "output_data": {"intent": "booking_request", "urgency": "medium", "language": "en", "confidence": 0.95},
                        "model": "claude-haiku-4-5",
                        "tokens_in": 350, "tokens_out": 80,
                        "cost_cents": 0.3,
                        "duration_ms": 420,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    {
                        "agent": "kb_agent",
                        "input_data": {"query": "Are you available to build this next week?", "client_id": str(client_acme.id)},
                        "output_data": {"facts": [{"content": "Starter plans: 2 weeks", "source_title": "Services & Timelines", "relevance": 0.85}], "confidence": 0.88},
                        "model": "claude-haiku-4-5",
                        "tokens_in": 500, "tokens_out": 120,
                        "cost_cents": 0.4,
                        "duration_ms": 310,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    {
                        "agent": "qualifier",
                        "input_data": {"lead_data": {"intent": "booking_request", "urgency": "medium"}},
                        "output_data": {"lead_score": 0.85, "status": "qualified", "questions_to_ask": []},
                        "model": "claude-haiku-4-5",
                        "tokens_in": 280, "tokens_out": 90,
                        "cost_cents": 0.2,
                        "duration_ms": 280,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    {
                        "agent": "responder",
                        "input_data": {"lead_message": "Are you available to build this next week?"},
                        "output_data": {"message": "Yes! We can start next week. Our standard turnaround is 2-4 weeks. Would you like to schedule a quick call to discuss details?", "tone_match_score": 0.92},
                        "model": "claude-haiku-4-5",
                        "tokens_in": 620, "tokens_out": 140,
                        "cost_cents": 0.5,
                        "duration_ms": 680,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    {
                        "agent": "critic",
                        "input_data": {"draft_message": "Yes! We can start next week..."},
                        "output_data": {"approved": True, "issues": [], "confidence": 0.94},
                        "model": "claude-opus-4-8",
                        "tokens_in": 450, "tokens_out": 60,
                        "cost_cents": 0.8,
                        "duration_ms": 410,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                ],
            )
            db.add(run1)

            # Lead 2: Sarah Jenkins - escalated
            lead2 = Lead(
                client_id=client_acme.id,
                agency_id=agency.id,
                source_channel="sms",
                external_id="+15550219876",
                name="Sarah Jenkins",
                email="sarah.j@gmail.com",
                phone="+15550219876",
                status="new",
                score=0.30,
            )
            db.add(lead2)
            await db.flush()

            conv2 = Conversation(
                lead_id=lead2.id,
                client_id=client_acme.id,
                agency_id=agency.id,
                channel="sms",
                status="escalated",
            )
            db.add(conv2)
            await db.flush()

            msgs2 = [
                Message(
                    conversation_id=conv2.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="Hello, I was looking at your services. Do you also host the website?",
                    status="sent",
                    metadata_={},
                ),
                Message(
                    conversation_id=conv2.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="outbound",
                    sender_type="agent",
                    content="Hi Sarah! Yes, we handle hosting and support on all of our plans so you do not have to worry about the technical details.",
                    status="sent",
                    metadata_={"confidence": 0.88},
                ),
                Message(
                    conversation_id=conv2.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="I need a refund for the hosting fee.",
                    status="sent",
                    metadata_={},
                ),
            ]
            for m in msgs2:
                db.add(m)

            run2 = AgentRun(
                conversation_id=conv2.id,
                client_id=client_acme.id,
                agency_id=agency.id,
                trigger_message_id=msgs2[-1].id,
                status="completed",
                decision="escalate",
                confidence_score=0.42,
                policy_flags=["escalated:high_risk", "high_risk_topic:refund"],
                total_tokens=980,
                total_cost_cents=1,
                duration_ms=1800,
                steps=[
                    {
                        "agent": "classifier",
                        "input_data": {"message": "I need a refund for the hosting fee."},
                        "output_data": {"intent": "refund", "urgency": "high", "language": "en", "confidence": 0.91},
                        "model": "claude-haiku-4-5",
                        "tokens_in": 320, "tokens_out": 75,
                        "cost_cents": 0.3,
                        "duration_ms": 380,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    {
                        "agent": "kb_agent",
                        "input_data": {"query": "refund hosting fee", "client_id": str(client_acme.id)},
                        "output_data": {"facts": [], "confidence": 0.0},
                        "model": "none",
                        "tokens_in": 0, "tokens_out": 0,
                        "cost_cents": 0,
                        "duration_ms": 5,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                    {
                        "agent": "critic",
                        "input_data": {"draft_message": "I'll look into that for you."},
                        "output_data": {"approved": False, "issues": [{"type": "policy_violation", "severity": "critical", "description": "High-risk topic (refund) requires human handling"}], "confidence": 0.42},
                        "model": "claude-opus-4-8",
                        "tokens_in": 400, "tokens_out": 85,
                        "cost_cents": 0.7,
                        "duration_ms": 520,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                ],
            )
            db.add(run2)

            # Lead 3: Carlos Ruiz - resolved
            lead3 = Lead(
                client_id=client_acme.id,
                agency_id=agency.id,
                source_channel="web_form",
                external_id="carlos@ruizrealty.com",
                name="Carlos Ruiz",
                email="carlos@ruizrealty.com",
                status="qualified",
                score=0.78,
            )
            db.add(lead3)
            await db.flush()

            conv3 = Conversation(
                lead_id=lead3.id,
                client_id=client_acme.id,
                agency_id=agency.id,
                channel="web_form",
                status="active",
            )
            db.add(conv3)
            await db.flush()

            msgs3 = [
                Message(
                    conversation_id=conv3.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="Web Form Inquiry: Need a new lead generation site for our real estate group. Budget is $1500.",
                    status="sent",
                    metadata_={"source": "web_form"},
                ),
                Message(
                    conversation_id=conv3.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="outbound",
                    sender_type="agent",
                    content="Hi Carlos! Thanks for reaching out. We can absolutely design a premium real estate lead generation website within your $1500 budget. Let's schedule a quick discovery call to lock in specifications. Would Tuesday at 2:00 PM work for you?",
                    status="sent",
                    metadata_={"confidence": 0.89},
                ),
                Message(
                    conversation_id=conv3.id,
                    client_id=client_acme.id,
                    agency_id=agency.id,
                    direction="inbound",
                    sender_type="lead",
                    content="That slot works perfectly, see you then.",
                    status="sent",
                    metadata_={},
                ),
            ]
            for m in msgs3:
                db.add(m)

            print("  ✅ Created 3 sample leads with conversations and agent runs")

        # ─── Usage Records ───────────────────────────────────────
        existing_usage = await db.execute(
            select(UsageRecord).where(UsageRecord.agency_id == agency.id)
        )
        if not existing_usage.scalars().all():
            today = datetime.now(UTC).date()
            usage = UsageRecord(
                agency_id=agency.id,
                client_id=client_acme.id,
                period_start=today.replace(day=1),
                period_end=today,
                leads_handled=3,
                messages_sent=4,
                tokens_used=3420,
                cost_cents=3,
            )
            db.add(usage)

        # ─── Audit Log ──────────────────────────────────────────
        audit = AuditLog(
            agency_id=agency.id,
            actor_type="system",
            action="seed.data_loaded",
            details={"source": "seed_demo.py"},
        )
        db.add(audit)

        await db.commit()
        print("\n🎉 Seed complete! You can now:")
        print("   - Login as admin@operdai.com / admin12345 (platform admin)")
        print("   - Login as admin@leadgenpro.com / agency12345 (agency admin)")
        print("   - API: http://localhost:8000/api/v1/health")


if __name__ == "__main__":
    asyncio.run(seed())
