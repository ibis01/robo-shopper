"""
Robo-Shopper V4 - Trade State Machine (Sprint 5).
Ensures trades cannot skip steps (e.g., PROPOSED -> EXECUTED without approval).
"""
from enum import Enum
from typing import List
from schemas import TradeStatus

# Define the legal transitions
ALLOWED_TRANSITIONS = {
    TradeStatus.ANALYZING: [TradeStatus.PROPOSED, TradeStatus.REJECTED],
    TradeStatus.PROPOSED: [TradeStatus.RISK_CHECKED, TradeStatus.REJECTED],
    TradeStatus.RISK_CHECKED: [TradeStatus.AWAITING_APPROVAL, TradeStatus.REJECTED],
    TradeStatus.AWAITING_APPROVAL: [TradeStatus.APPROVED, TradeStatus.REJECTED],
    TradeStatus.APPROVED: [TradeStatus.EXECUTED, TradeStatus.CLOSED, TradeStatus.REJECTED],
    TradeStatus.EXECUTED: [TradeStatus.CLOSED],
    TradeStatus.REJECTED: [],
    TradeStatus.CLOSED: [],
}

def transition_status(current: TradeStatus, target: TradeStatus) -> TradeStatus:
    """
    Validates a state transition. Raises ValueError if illegal.
    """
    if current == target:
        return target  # Idempotent
    
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise ValueError(
            f"ILLEGAL STATE TRANSITION: Cannot go from {current.value} to {target.value}. "
            f"Allowed transitions: {[s.value for s in allowed]}"
        )
    return target

# --- Optional: Add this to your MCP tools so the LLM can't bypass it ---
def get_allowed_next_states(current: TradeStatus) -> List[str]:
    """Returns a list of human-readable next states."""
    return [s.value for s in ALLOWED_TRANSITIONS.get(current, [])]