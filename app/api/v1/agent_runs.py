"""Agent Runs API — list, view, and replay agent pipeline traces."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_tenant_db
from app.models.agent_run import AgentRun
from app.models.user import User

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


@router.get("")
async def list_agent_runs(
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
    client_id: uuid.UUID | None = None,
    decision: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """List agent pipeline runs with optional filtering."""
    query = select(AgentRun).order_by(desc(AgentRun.created_at))

    if client_id:
        query = query.where(AgentRun.client_id == client_id)
    if decision:
        query = query.where(AgentRun.decision == decision)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    runs = result.scalars().all()

    # Count
    count_query = select(func.count(AgentRun.id))
    if client_id:
        count_query = count_query.where(AgentRun.client_id == client_id)
    if decision:
        count_query = count_query.where(AgentRun.decision == decision)
    total = (await db.execute(count_query)).scalar()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [
            {
                "id": str(run.id),
                "conversation_id": str(run.conversation_id),
                "client_id": str(run.client_id),
                "decision": run.decision,
                "confidence_score": run.confidence_score,
                "policy_flags": run.policy_flags,
                "total_tokens": run.total_tokens,
                "total_cost_cents": run.total_cost_cents,
                "duration_ms": run.duration_ms,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
            for run in runs
        ],
    }


@router.get("/{run_id}")
async def get_agent_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """Get full agent run details including the step-by-step trace."""
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "client_id": str(run.client_id),
        "agency_id": str(run.agency_id),
        "trigger_message_id": str(run.trigger_message_id) if run.trigger_message_id else None,
        "status": run.status,
        "decision": run.decision,
        "confidence_score": run.confidence_score,
        "policy_flags": run.policy_flags,
        "total_tokens": run.total_tokens,
        "total_cost_cents": run.total_cost_cents,
        "duration_ms": run.duration_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "steps": run.steps,  # Full trace — every agent call
    }


@router.get("/{run_id}/replay")
async def replay_agent_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """
    Replay an agent run — returns the full trace in a timeline-friendly format.

    Used by the dashboard to show the agent's decision-making process
    step-by-step with tokens, costs, and timing for each agent.
    """
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    timeline = []
    cumulative_tokens = 0
    cumulative_cost = 0.0
    cumulative_ms = 0

    for i, step in enumerate(run.steps or []):
        tokens = step.get("tokens_in", 0) + step.get("tokens_out", 0)
        cost = step.get("cost_cents", 0)
        duration = step.get("duration_ms", 0)
        cumulative_tokens += tokens
        cumulative_cost += cost
        cumulative_ms += duration

        timeline.append({
            "step": i + 1,
            "agent": step.get("agent", "unknown"),
            "model": step.get("model", ""),
            "input_summary": _summarize_data(step.get("input_data", {})),
            "output_summary": _summarize_data(step.get("output_data", {})),
            "tokens": tokens,
            "cost_cents": cost,
            "duration_ms": duration,
            "cumulative_tokens": cumulative_tokens,
            "cumulative_cost_cents": cumulative_cost,
            "cumulative_ms": cumulative_ms,
            "timestamp": step.get("timestamp", ""),
        })

    return {
        "run_id": str(run.id),
        "decision": run.decision,
        "confidence": run.confidence_score,
        "policy_flags": run.policy_flags,
        "total_steps": len(timeline),
        "total_tokens": run.total_tokens,
        "total_cost_cents": run.total_cost_cents,
        "total_duration_ms": run.duration_ms,
        "timeline": timeline,
    }


def _summarize_data(data: dict, max_len: int = 200) -> str:
    """Create a human-readable summary of agent I/O data."""
    if not data:
        return ""

    # For classifier output
    if "intent" in data and "urgency" in data:
        return f"Intent: {data['intent']}, Urgency: {data['urgency']}, Confidence: {data.get('confidence', 'N/A')}"

    # For responder output
    if "message" in data and "tone_match_score" in data:
        msg = data["message"]
        return f"Draft ({len(msg)} chars): {msg[:100]}..." if len(msg) > 100 else f"Draft: {msg}"

    # For critic output
    if "approved" in data:
        issues = data.get("issues", [])
        return f"Approved: {data['approved']}, Issues: {len(issues)}"

    # For qualifier output
    if "lead_score" in data:
        return f"Score: {data['lead_score']}, Status: {data.get('status', 'N/A')}"

    # Generic
    import json
    summary = json.dumps(data, default=str)
    return summary[:max_len] + "..." if len(summary) > max_len else summary


@router.post("/simulate-red-team")
async def simulate_red_team(
    client_id: uuid.UUID,
    rounds: int = Query(default=3, le=5),
    db: AsyncSession = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
):
    """
    Launch an automated Red-Team simulation against a client workspace.
    """
    from app.services.simulation import run_red_team_simulation
    return await run_red_team_simulation(db, client_id, rounds)


@router.post("/negotiate")
async def negotiate_agents(
    client_a_id: uuid.UUID,
    client_b_id: uuid.UUID,
    topic: str,
    rounds: int = Query(default=3, le=5),
    user: User = Depends(get_current_user),
):
    """
    Simulates cross-agent negotiations between two business workspaces.
    """
    from app.services.negotiation import run_agent_negotiation
    return await run_agent_negotiation(client_a_id, client_b_id, topic, rounds)
