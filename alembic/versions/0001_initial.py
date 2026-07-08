"""Initial schema for OperdAI platform.

Creates all core tables: agencies, clients, users, leads, conversations,
messages, kb_documents, kb_chunks, agent_runs, audit_log, billing, etc.

Revision ID: 0001_initial
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers
revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Agencies ===
    op.create_table(
        'agencies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('custom_domain', sa.String(255), nullable=True),
        sa.Column('branding', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_agencies_slug', 'agencies', ['slug'])

    # === Clients ===
    op.create_table(
        'clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('business_name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('brand_voice', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('never_say_list', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('autonomy_config', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('kill_switch', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('shadow_mode', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('channel_config', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('calendar_config', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('safe_scripts', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_clients_agency_id', 'clients', ['agency_id'])
    op.create_index('ix_clients_slug', 'clients', ['slug'])

    # === Users ===
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('google_oauth_id', sa.String(255), nullable=True, unique=True),
        sa.Column('role', sa.String(50), nullable=False, server_default='agency_member'),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=True),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_agency_id', 'users', ['agency_id'])

    # === Leads ===
    op.create_table(
        'leads',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('source_channel', sa.String(50), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('qualification_data', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('qualification_score', sa.Float, nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='new'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_leads_client_id', 'leads', ['client_id'])
    op.create_index('ix_leads_agency_id', 'leads', ['agency_id'])
    op.create_index('ix_leads_external_id', 'leads', ['external_id'])

    # === Conversations ===
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('channel', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('context', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_conversations_lead_id', 'conversations', ['lead_id'])
    op.create_index('ix_conversations_client_id', 'conversations', ['client_id'])
    op.create_index('ix_conversations_agency_id', 'conversations', ['agency_id'])

    # === Messages ===
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('sender_type', sa.String(20), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_index('ix_messages_client_id', 'messages', ['client_id'])
    op.create_index('ix_messages_agency_id', 'messages', ['agency_id'])

    # === KB Documents ===
    op.create_table(
        'kb_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('doc_type', sa.String(50), nullable=False, server_default='general'),
        sa.Column('source_url', sa.String(2000), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_kb_documents_client_id', 'kb_documents', ['client_id'])
    op.create_index('ix_kb_documents_agency_id', 'kb_documents', ['agency_id'])

    # === KB Chunks (with pgvector) ===
    op.create_table(
        'kb_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('kb_documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_kb_chunks_document_id', 'kb_chunks', ['document_id'])
    op.create_index('ix_kb_chunks_client_id', 'kb_chunks', ['client_id'])
    op.create_index('ix_kb_chunks_agency_id', 'kb_chunks', ['agency_id'])

    # === Agent Runs ===
    op.create_table(
        'agent_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('trigger_message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('messages.id'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('steps', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('decision', sa.String(30), nullable=True),
        sa.Column('confidence_score', sa.Float, nullable=True),
        sa.Column('policy_flags', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('total_tokens', sa.Integer, nullable=False, server_default='0'),
        sa.Column('total_cost_cents', sa.Integer, nullable=False, server_default='0'),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_agent_runs_conversation_id', 'agent_runs', ['conversation_id'])
    op.create_index('ix_agent_runs_client_id', 'agent_runs', ['client_id'])
    op.create_index('ix_agent_runs_agency_id', 'agent_runs', ['agency_id'])

    # === Audit Log ===
    op.create_table(
        'audit_log',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('actor_type', sa.String(20), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('details', postgresql.JSONB, nullable=True),
        sa.Column('ip_address', postgresql.INET, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_audit_log_agency_id', 'audit_log', ['agency_id'])

    # === Follow Up Schedule ===
    op.create_table(
        'follow_up_schedule',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('step_number', sa.Integer, nullable=False, server_default='1'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('template_key', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_follow_up_lead_id', 'follow_up_schedule', ['lead_id'])
    op.create_index('ix_follow_up_client_id', 'follow_up_schedule', ['client_id'])
    op.create_index('ix_follow_up_agency_id', 'follow_up_schedule', ['agency_id'])

    # === Calendar Bookings ===
    op.create_table(
        'calendar_bookings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('calendar_event_id', sa.String(255), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='confirmed'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_calendar_bookings_lead_id', 'calendar_bookings', ['lead_id'])
    op.create_index('ix_calendar_bookings_client_id', 'calendar_bookings', ['client_id'])
    op.create_index('ix_calendar_bookings_agency_id', 'calendar_bookings', ['agency_id'])

    # === Usage Records ===
    op.create_table(
        'usage_records',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('leads_handled', sa.Integer, nullable=False, server_default='0'),
        sa.Column('messages_sent', sa.Integer, nullable=False, server_default='0'),
        sa.Column('tokens_used', sa.BigInteger, nullable=False, server_default='0'),
        sa.Column('cost_cents', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_usage_records_agency_id', 'usage_records', ['agency_id'])
    op.create_index('ix_usage_records_client_id', 'usage_records', ['client_id'])

    # === Billing Config ===
    op.create_table(
        'billing_config',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False, unique=True),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('plan_type', sa.String(50), nullable=False, server_default='starter'),
        sa.Column('monthly_lead_cap', sa.Integer, nullable=True),
        sa.Column('monthly_token_cap', sa.BigInteger, nullable=True),
        sa.Column('cost_per_lead_cents', sa.Integer, nullable=False, server_default='50'),
        sa.Column('alert_threshold_pct', sa.Integer, nullable=False, server_default='80'),
        sa.Column('is_capped', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # === Tone Feedback ===
    op.create_table(
        'tone_feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id'), nullable=False),
        sa.Column('agency_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agencies.id'), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('original_draft', sa.Text, nullable=False),
        sa.Column('human_response', sa.Text, nullable=False),
        sa.Column('edited', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_tone_feedback_client_id', 'tone_feedback', ['client_id'])
    op.create_index('ix_tone_feedback_agency_id', 'tone_feedback', ['agency_id'])

    # === Agent Templates ===
    op.create_table(
        'agent_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('brand_voice', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('never_say_list', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('autonomy_config', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # === Integrations ===
    op.create_table(
        'integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('credentials', postgresql.JSON, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_integrations_client_id', 'integrations', ['client_id'])

    # ─── RLS Policies ──────────────────────────────────────────
    # Enable RLS on tenant-scoped tables
    op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE leads ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kb_documents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE kb_chunks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE follow_up_schedule ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE calendar_bookings ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tone_feedback ENABLE ROW LEVEL SECURITY;")

    # Create RLS policies using session variables set by the app
    for table in ['clients', 'leads', 'conversations', 'messages', 'kb_documents',
                  'kb_chunks', 'agent_runs', 'audit_log', 'follow_up_schedule',
                  'calendar_bookings', 'usage_records', 'tone_feedback']:
        op.execute(f"""
            CREATE POLICY {table}_agency_isolation ON {table}
                USING (agency_id = current_setting('app.current_agency_id', true)::uuid);
        """)
        op.execute(f"""
            CREATE POLICY {table}_platform_admin_bypass ON {table}
                USING (current_setting('app.current_role', true) = 'platform_admin');
        """)


def downgrade() -> None:
    # Drop in reverse order
    tables = [
        'integrations', 'agent_templates', 'tone_feedback', 'billing_config',
        'usage_records', 'calendar_bookings', 'follow_up_schedule', 'audit_log',
        'agent_runs', 'kb_chunks', 'kb_documents', 'messages', 'conversations',
        'leads', 'clients', 'users', 'agencies',
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
