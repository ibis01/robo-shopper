"""
Robo-Shopper V4 - Single State-Transition Authority (Sprint 5).
ONE function responsible for EVERY state mutation.
No other module may directly execute UPDATE trades SET status = ...
"""
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

from config import DB_PATH
from schemas import TradeStatus

class ActorType(str, Enum):
    SYSTEM = "system"
    AI = "ai"
    HUMAN = "human"
    RISK_ENGINE = "risk_engine"
    GUARDRAIL = "guardrail"

# --- Legal transitions ---
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

# --- Actors allowed to perform each transition ---
AUTHORIZED_ACTORS = {
    TradeStatus.PROPOSED: [ActorType.AI, ActorType.SYSTEM],
    TradeStatus.RISK_CHECKED: [ActorType.RISK_ENGINE],
    TradeStatus.AWAITING_APPROVAL: [ActorType.RISK_ENGINE],
    TradeStatus.APPROVED: [ActorType.HUMAN, ActorType.SYSTEM],
    TradeStatus.EXECUTED: [ActorType.HUMAN, ActorType.SYSTEM],
    TradeStatus.REJECTED: [ActorType.RISK_ENGINE, ActorType.GUARDRAIL, ActorType.HUMAN],
    TradeStatus.CLOSED: [ActorType.SYSTEM],
}


def transition_trade(
    trade_id: int,
    target_status: TradeStatus,
    actor: ActorType,
    metadata: Optional[Dict[str, Any]] = None,
    require_approval_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    SINGLE SOURCE OF TRUTH for all trade state changes.
    
    Enforces:
    1. Trade exists
    2. Transition is legal (state machine)
    3. Actor is authorized
    4. (Optional) Approval hash matches for execution
    
    Returns:
        Dict with status, trade_id, new_status, message
    """
    metadata = metadata or {}
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Fetch current trade
    cursor.execute("""
        SELECT id, status, proposal_hash, entry_price, quantity, stop_loss
        FROM trades WHERE id = ?
    """, (trade_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {
            "status": "ERROR",
            "trade_id": trade_id,
            "message": f"Trade {trade_id} not found."
        }
    
    trade_status = TradeStatus(row[1])
    stored_hash = row[2]
    entry = row[3]
    qty = row[4]
    stop = row[5]
    
    # 2. Validate transition
    if target_status not in ALLOWED_TRANSITIONS.get(trade_status, []):
        conn.close()
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "message": (
                f"ILLEGAL TRANSITION: Cannot move from {trade_status.value} to {target_status.value}. "
                f"Allowed: {[s.value for s in ALLOWED_TRANSITIONS.get(trade_status, [])]}"
            ),
            "current_status": trade_status.value,
            "target_status": target_status.value
        }
    
    # 3. Validate actor
    authorized_actors = AUTHORIZED_ACTORS.get(target_status, [])
    if actor not in authorized_actors:
        conn.close()
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "message": f"UNAUTHORIZED ACTOR: {actor.value} cannot perform {target_status.value} transition.",
            "authorized_actors": [a.value for a in authorized_actors]
        }
    
    # 4. Special validation: EXECUTED requires approval hash match
    if target_status == TradeStatus.EXECUTED:
        if not require_approval_hash:
            conn.close()
            return {
                "status": "REJECTED",
                "trade_id": trade_id,
                "message": "EXECUTION BLOCKED: Approval hash required."
            }
        if stored_hash and require_approval_hash != stored_hash:
            conn.close()
            return {
                "status": "REJECTED",
                "trade_id": trade_id,
                "message": "EXECUTION BLOCKED: Proposal hash mismatch. Trade may have been tampered with.",
                "stored_hash": stored_hash,
                "provided_hash": require_approval_hash
            }
    
    # 5. Execute the transition
    timestamp = datetime.utcnow().isoformat()
    
    # Map status to column name
    status_column_map = {
        TradeStatus.PROPOSED: "proposed_at",
        TradeStatus.RISK_CHECKED: "risk_checked_at",
        TradeStatus.AWAITING_APPROVAL: "approval_requested_at",
        TradeStatus.APPROVED: "approved_at",
        TradeStatus.EXECUTED: "executed_at",
        TradeStatus.CLOSED: "closed_at",
    }
    
    # Build the UPDATE dynamically
    set_clauses = ["status = ?"]
    params = [target_status.value]
    
    if target_status in status_column_map:
        set_clauses.append(f"{status_column_map[target_status]} = ?")
        params.append(timestamp)
    
    # Store actor in a dedicated column
    set_clauses.append("last_modified_by = ?")
    params.append(actor.value)
    
    # Store metadata (JSON) if provided
    if metadata:
        import json
        set_clauses.append("transition_metadata = ?")
        params.append(json.dumps(metadata))
    
    params.append(trade_id)
    
    query = f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    
    return {
        "status": "SUCCESS",
        "trade_id": trade_id,
        "new_status": target_status.value,
        "actor": actor.value,
        "message": f"Trade {trade_id} transitioned to {target_status.value} by {actor.value}.",
        "timestamp": timestamp
    }


def get_allowed_next_states(current_status: TradeStatus) -> list[str]:
    """Returns human-readable list of allowed next states."""
    return [s.value for s in ALLOWED_TRANSITIONS.get(current_status, [])]