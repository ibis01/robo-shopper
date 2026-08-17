"""
Robo-Shopper V4 - Single State-Transition Authority (Sprint 5).
ONE function responsible for EVERY state mutation.
Atomic updates prevent race conditions.
Idempotent: repeated transitions to the same state return SUCCESS.
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any

from config import DB_PATH
from schemas import TradeStatus, ActorType

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

# --- Authorized actors ---
AUTHORIZED_ACTORS = {
    TradeStatus.PROPOSED: [ActorType.AI, ActorType.SYSTEM],
    TradeStatus.RISK_CHECKED: [ActorType.RISK_ENGINE],
    TradeStatus.AWAITING_APPROVAL: [ActorType.RISK_ENGINE],
    TradeStatus.APPROVED: [ActorType.HUMAN],                  # ONLY human
    TradeStatus.EXECUTED: [ActorType.EXECUTION_GATEWAY],      # NOT human directly
    TradeStatus.REJECTED: [ActorType.RISK_ENGINE, ActorType.GUARDRAIL, ActorType.HUMAN],
    TradeStatus.CLOSED: [ActorType.SYSTEM],
}

# ------------------------------------------------------------------
# ATOMIC UPDATE (optimistic concurrency control)
# ------------------------------------------------------------------
def _atomic_update(
    trade_id: int,
    target_status: TradeStatus,
    actor: ActorType,
    metadata: Optional[dict] = None,
    extra_where: str = ""
) -> int:
    """Performs an atomic UPDATE with a WHERE clause to prevent races."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get current status
    cursor.execute("SELECT status FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 0
    current_status = row[0]
    
    # Build SET clauses
    set_clauses = [
        "status = ?",
        "last_modified_at = ?",
        "last_modified_by = ?"
    ]
    params = [target_status.value, datetime.utcnow().isoformat(), actor.value]
    
    # Status-specific timestamp columns
    status_col_map = {
        TradeStatus.PROPOSED: "proposed_at",
        TradeStatus.RISK_CHECKED: "risk_checked_at",
        TradeStatus.AWAITING_APPROVAL: "approval_requested_at",
        TradeStatus.APPROVED: "approved_at",
        TradeStatus.EXECUTED: "executed_at",
        TradeStatus.CLOSED: "closed_at",
    }
    if target_status in status_col_map:
        set_clauses.append(f"{status_col_map[target_status]} = ?")
        params.append(datetime.utcnow().isoformat())
    
    if metadata:
        set_clauses.append("transition_metadata = ?")
        params.append(json.dumps(metadata))
    
    # WHERE clause: id = ? AND status = ? (atomic)
    params.append(current_status)   # for WHERE status =
    params.append(trade_id)         # for WHERE id =
    
    query = f"""
        UPDATE trades 
        SET {', '.join(set_clauses)}
        WHERE id = ? AND status = ?
        {extra_where}
    """
    
    cursor.execute(query, params)
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

# ------------------------------------------------------------------
# IDEMPOTENCY CHECK
# ------------------------------------------------------------------
def _is_already_in_state(trade_id: int, target_status: TradeStatus) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == target_status.value

# ------------------------------------------------------------------
# SINGLE STATE-TRANSITION AUTHORITY
# ------------------------------------------------------------------
def transition_trade(
    trade_id: int,
    target_status: TradeStatus,
    actor: ActorType,
    metadata: Optional[dict] = None,
    require_approval_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    SINGLE SOURCE OF TRUTH for all trade state changes.
    Enforces: legality, actor auth, hash match, atomicity, idempotency.
    """
    metadata = metadata or {}
    extra_where = ""
    
    # --- 1. Idempotency ---
    if _is_already_in_state(trade_id, target_status):
        return {
            "status": "SUCCESS",
            "trade_id": trade_id,
            "message": f"Trade already in {target_status.value}. Idempotent.",
            "idempotent": True
        }
    
    # --- 2. Fetch current state ---
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, status, proposal_hash, entry_price, quantity, stop_loss
        FROM trades WHERE id = ?
    """, (trade_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"status": "ERROR", "trade_id": trade_id, "message": f"Trade {trade_id} not found."}
    
    current_status = TradeStatus(row[1])
    stored_hash = row[2]
    
    # --- 3. Validate transition legality ---
    if target_status not in ALLOWED_TRANSITIONS.get(current_status, []):
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "message": (
                f"ILLEGAL: {current_status.value} → {target_status.value}. "
                f"Allowed: {[s.value for s in ALLOWED_TRANSITIONS.get(current_status, [])]}"
            ),
            "current_status": current_status.value,
            "target_status": target_status.value
        }
    
    # --- 4. Validate actor ---
    authorized = AUTHORIZED_ACTORS.get(target_status, [])
    if actor not in authorized:
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "message": f"UNAUTHORIZED: {actor.value} cannot perform {target_status.value}.",
            "authorized_actors": [a.value for a in authorized]
        }
    
    # --- 5. Special: EXECUTED requires approval hash ---
    if target_status == TradeStatus.EXECUTED:
        if not require_approval_hash:
            return {
                "status": "REJECTED",
                "trade_id": trade_id,
                "message": "EXECUTION BLOCKED: Approval hash required."
            }
        if stored_hash and require_approval_hash != stored_hash:
            return {
                "status": "REJECTED",
                "trade_id": trade_id,
                "message": "EXECUTION BLOCKED: Hash mismatch. Trade may be tampered.",
                "stored_hash": stored_hash,
                "provided_hash": require_approval_hash
            }
        # Extra safety: also check that status is APPROVED (enforced by state machine)
        if current_status != TradeStatus.APPROVED:
            return {
                "status": "REJECTED",
                "trade_id": trade_id,
                "message": f"EXECUTION BLOCKED: Trade must be APPROVED, but is {current_status.value}."
            }
    
    # --- 6. Atomic UPDATE ---
    affected = _atomic_update(trade_id, target_status, actor, metadata, extra_where)
    if affected == 0:
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "message": "Concurrent modification detected. Please retry."
        }
    
    return {
        "status": "SUCCESS",
        "trade_id": trade_id,
        "new_status": target_status.value,
        "actor": actor.value,
        "message": f"Trade {trade_id} → {target_status.value} by {actor.value}.",
        "timestamp": datetime.utcnow().isoformat()
    }