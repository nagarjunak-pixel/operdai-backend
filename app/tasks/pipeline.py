"""
Celery pipeline tasks.
"""

from __future__ import annotations

import asyncio
import uuid

from app.agents.supervisor import run_full_pipeline
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.pipeline.run_agent_pipeline_task")
def run_agent_pipeline_task(
    conversation_id: str,
    message_id: str,
    client_id: str,
    agency_id: str,
) -> dict:
    """
    Celery task that runs the full agent pipeline in an isolated thread.
    """
    async def _run():
        return await run_full_pipeline(
            conversation_id=uuid.UUID(conversation_id),
            message_id=uuid.UUID(message_id),
            client_id=uuid.UUID(client_id),
            agency_id=uuid.UUID(agency_id),
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
