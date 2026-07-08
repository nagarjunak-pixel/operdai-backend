"""RLHF Service — auto-tunes system prompts based on operator feedback and edits."""

from __future__ import annotations

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.feedback import ToneFeedback
from app.agents.llm import get_llm_provider

logger = logging.getLogger("operdai.rlhf")


async def auto_tune_prompt(db: AsyncSession, client_id: uuid.UUID) -> str:
    """
    Collects recent ToneFeedback entries, summarizes operator edits,
    and updates the client's brand voice instructions autonomously.
    """
    # 1. Fetch client
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        return "Client not found"

    # 2. Fetch recent feedback records
    feedback_res = await db.execute(
        select(ToneFeedback).where(
            ToneFeedback.client_id == client_id,
            ToneFeedback.edited == True  # noqa: E712
        ).limit(5)
    )
    feedbacks = feedback_res.scalars().all()
    if not feedbacks:
        return "No feedback entries available to learn from."

    # 3. Simulate analysis of changes
    edits_summary = []
    for f in feedbacks:
        edits_summary.append(
            f"Original Draft: '{f.original_draft}' -> Operator Edited: '{f.human_response}'"
        )

    current_voice = client.brand_voice.get("tone", "") if isinstance(client.brand_voice, dict) else str(client.brand_voice)

    # Autonomously tune the prompt using the mock/real LLM provider
    analysis_prompt = (
        f"You are the RLHF Prompt Optimizer. Here are recent edits made by the business operator:\n"
        f"{chr(10).join(edits_summary)}\n"
        f"Analyze these edits and adjust the current brand voice guide: '{current_voice}' "
        f"to prevent the operator from needing to rewrite these drafts in the future."
    )

    llm = get_llm_provider(mock=True)
    res = await llm.complete(
        messages=[{"role": "user", "content": analysis_prompt}],
        system="You output a concise, refined version of the brand guide incorporating the operator's style changes.",
    )

    refined_brand_voice = res.content or f"{current_voice}\nNote: Keep responses concise."

    # 4. Save and commit updated brand voice
    if isinstance(client.brand_voice, dict):
        client.brand_voice["tone"] = refined_brand_voice
    else:
        client.brand_voice = {"tone": refined_brand_voice}
    db.add(client)
    await db.commit()

    logger.info(f"Auto-tuned brand voice prompt for client {client_id}")
    return refined_brand_voice
