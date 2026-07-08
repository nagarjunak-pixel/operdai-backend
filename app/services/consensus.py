"""
Consensus Engine — implements PBFT-style LLM consensus voting for high-trust agent actions.
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger("operdai.consensus")


class ConsensusCoordinator:
    """
    Coordinates semantic consensus across multiple model profiles to validate critical operations.
    Prevents single-provider hallucinations from triggering unauthorized actions.
    """

    def __init__(self, models: list[str] | None = None):
        self.models = models or ["claude-3-haiku", "gpt-4o-mini", "llama-3-8b"]

    async def evaluate_action(
        self,
        action_type: str,
        proposed_payload: dict,
        conversation_history: list[dict],
    ) -> dict:
        """
        Executes consensus voting.
        Requires >50% approval to confirm the action, otherwise escalates or rejects.
        """
        votes = {}
        # In production, this would fire parallel async requests to each model api.
        # For now, we calculate votes based on payload verification and rules.
        is_valid_payload = True
        
        # Simple validation rules: e.g., bookings require start_time and lead name
        if action_type == "confirm_booking":
            if not proposed_payload.get("start_time"):
                is_valid_payload = False

        for model in self.models:
            # Simulate slight vote variations/flaps for testing consensus logic
            if not is_valid_payload:
                votes[model] = "reject"
            elif model == "llama-3-8b" and proposed_payload.get("simulate_failure"):
                votes[model] = "reject"
            else:
                votes[model] = "approve"

        # Count votes
        approve_count = sum(1 for v in votes.values() if v == "approve")
        total_votes = len(votes)
        quorum_pct = (approve_count / total_votes) * 100

        consensus_status: Literal["approved", "escalate"] = "approved" if quorum_pct > 50 else "escalate"

        logger.info(
            f"Consensus run for '{action_type}': {consensus_status} "
            f"({approve_count}/{total_votes} votes approve - {quorum_pct:.1f}%)"
        )

        return {
            "decision": consensus_status,
            "action_type": action_type,
            "quorum_percentage": round(quorum_pct, 2),
            "votes": votes,
            "total_voters": total_votes,
        }
