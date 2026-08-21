"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Atomic request_approval(), approve_trade(), execute_trade().
"""
import sqlite3
from typing import Dict, Any
from datetime import datetime, timedelta, timezone

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
from state_machine import transition_trade
from approval_tokens import create_approval_token, validate_and_consume_token_in_transaction
import risk_management_mcp
import guardrails_mcp
import trade_memory_mcp

# ------------------------------------------------------------------
# STEP 1: REQUEST APPROVAL (auto‑transitions PROPOSED -> AWAITING_APPROVAL)
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Mint a one-time approval token for an already screened trade."""
    # --- Phase 1: verify trade has been screened ---
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}

    # Enforcement: trade MUST already be AWAITING_APPROVAL (meaning screen_trade() passed)
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {
            "status": "REJECTED",
            "reason": f"Trade {trade_id} is '{trade['status']}'. Must call screen_trade() first."
        }

    # --- Phase 2: mint token under exclusive lock (single connection only) ---
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            conn.rollback()
            return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
        cols = [c[0] for c in conn.execute("SELECT * FROM trades LIMIT 1").description]
        trade = dict(zip(cols, row))
        current_status = trade["status"]

        if current_status != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback()
            return {"status": "ERROR",
                    "reason": f"Trade {trade_id} is '{current_status}', must be 'awaiting_approval'."}

        entry = trade["entry_price"]; stop = trade["stop_loss"]; qty = trade["quantity"]
        balance = trade.get("portfolio_balance") or 10000.0
        risk_amount = trade.get("risk_amount")
        if risk_amount is None:
            risk_amount = abs(entry - stop) * qty
        risk_percent = trade.get("risk_percent")
        if risk_percent is None:
            risk_percent = (risk_amount / balance) if balance > 0 else 0.02

        expires_at_str = trade.get("proposal_expires_at")
        if not expires_at_str:
            conn.rollback()
            return {"status": "REJECTED", "reason": "Trade has no expiration set."}

        proposal = TradeProposal(
            asset=trade["symbol"],
            side=trade["side"],
            entry_price=entry,
            stop_loss=stop,
            take_profit=trade.get("take_profit"),
            quantity=qty,
            risk_percent=risk_percent,
            risk_amount=risk_amount,
            portfolio_balance_at_time=balance,
            agent_reasoning=trade.get("reasoning", ""),
            risk_decision="PENDING",
            expires_at=datetime.fromisoformat(expires_at_str),
        )
        proposal_hash = proposal.compute_hash()
        policy_version = proposal.policy_version

        cur = conn.execute(
            "UPDATE trades SET proposal_hash = ?, policy_version = ?, proposal_expires_at = ? WHERE id = ?",
            (proposal_hash, policy_version, expires_at_str, trade_id))
        if cur.rowcount == 0:
            conn.rollback()
            return {"status": "ERROR", "reason": "Failed to update trade."}

        token_result = create_approval_token(trade_id, proposal_hash, policy_version, requested_by, conn=conn)
        conn.commit()
        return {
            "status": "success",
            "trade_id": trade_id,
            "approval_token": token_result["approval_token"],
            "expires_at": token_result["expires_at"],
            "proposal_hash": proposal_hash,
            "policy_version": policy_version,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"status": "ERROR", "reason": f"request_approval exception: {e}"}
    finally:
        conn.close()


def approve_trade(approval_token: str, approved_by: str = "system") -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    try:
        trade_id, token_hash, token_policy = validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Invalid, expired, or already used token."}
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, status, proposal_hash, policy_version, entry_price, quantity, stop_loss,
                   risk_percent, risk_amount, portfolio_balance, proposal_expires_at, reasoning,
                   symbol, side, take_profit
            FROM trades WHERE id = ?
        """, (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
        
        (_, trade_status, trade_hash, trade_policy, entry, qty, stop,
         risk_pct, risk_amt, balance, expires_at_str, reasoning,
         symbol, side, take_profit) = row
        
        if trade_status != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade_status}', must be 'awaiting_approval'."}
        
        # Defense-in-depth: recompute proposal hash and verify three-way match
        # TOKEN HASH == TRADE HASH == COMPUTED HASH
        # For hash verification, use defensive defaults if values are None
        # (actual execution will fail-closed, but hash verification needs complete data)
        # Fail closed: reject if any authorization field is missing
        if not symbol:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Missing symbol in trade record."}
        if not side:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Missing side in trade record."}
        if risk_pct is None:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Missing risk_percent in trade record."}
        if risk_amt is None:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Missing risk_amount in trade record."}
        if balance is None:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Missing portfolio_balance in trade record."}
        if not expires_at_str:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Missing proposal expiration."}
        
        expires_at = datetime.fromisoformat(expires_at_str)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        proposal = TradeProposal(
            asset=symbol,
            side=side,
            entry_price=entry,
            stop_loss=stop,
            take_profit=take_profit,
            quantity=qty,
            risk_percent=risk_pct,
            risk_amount=risk_amt,
            portfolio_balance_at_time=balance,
            agent_reasoning=reasoning or "",
            risk_decision="PASSED",
            expires_at=datetime.fromisoformat(expires_at_str)
        )
        computed_hash = proposal.compute_hash()
        
        if token_hash != trade_hash:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: token_hash != trade_hash."}
        
        if computed_hash != trade_hash:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: computed_hash != trade_hash."}
        if token_policy != trade_policy:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "POLICY MISMATCH."}
        if not expires_at_str:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Trade has no expiration."}
        
        result = transition_trade(
            trade_id,
            TradeStatus.APPROVED,
            ActorType.HUMAN,
            {"approved_by": approved_by, "proposal_hash": token_hash},
            conn=conn
        )
        if result["status"] != "SUCCESS":
            conn.rollback()
            conn.close()
            return result
        
        conn.commit()
        conn.close()
        return {
            "status": "SUCCESS",
            "trade_id": trade_id,
            "new_status": TradeStatus.APPROVED.value,
            "approved_by": approved_by,
            "proposal_hash": token_hash,
            "message": f"Trade {trade_id} approved by {approved_by}."
        }
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "ERROR", "reason": str(e)}

# ------------------------------------------------------------------
# STEP 3: EXECUTE TRADE (unchanged)
# ------------------------------------------------------------------
def execute_trade(
    trade_id: int,
    execution_price: float,
    executed_by: str = "execution_gateway"
) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    # IDEMPOTENCY: if already executed, return success
    if trade["status"] == TradeStatus.EXECUTED.value:
        return {
            "status": "SUCCESS",
            "new_status": TradeStatus.EXECUTED.value,
            "idempotent": True,
            "reason": "Trade already executed."
        }
    
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'approved'."}
    
    stored_hash = trade.get("proposal_hash")
    if not stored_hash:
        return {"status": "REJECTED", "reason": "No proposal hash."}
    
    risk_percent = trade.get("risk_percent")
    if risk_percent is None:
        return {"status": "REJECTED", "reason": "Missing risk_percent in trade record."}
    risk_amount = trade.get("risk_amount")
    if risk_amount is None:
        return {"status": "REJECTED", "reason": "Missing risk_amount in trade record."}
    
    portfolio_balance = trade.get("portfolio_balance")
    if portfolio_balance is None:
        return {"status": "REJECTED", "reason": "Missing portfolio_balance in trade record."}
    expires_at_str = trade.get("proposal_expires_at")
    if not expires_at_str:
        return {"status": "REJECTED", "reason": "Trade has no expiration set."}
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
        risk_percent=risk_percent,
        risk_amount=risk_amount,
        portfolio_balance_at_time=portfolio_balance,
        agent_reasoning=trade.get("reasoning", ""),
        risk_decision="PASSED",
        expires_at=expires_at
    )
    computed_hash = proposal.compute_hash()
    
    if computed_hash != stored_hash:
        return {
            "status": "REJECTED",
            "reason": "PROPOSAL TAMPERED: Hash mismatch.",
            "stored": stored_hash,
            "computed": computed_hash
        }
    
    result = transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.EXECUTION_GATEWAY,
        {
            "execution_price": execution_price, 
            "executed_by": executed_by,
            "proposal_hash": stored_hash
        },
        require_approval_hash=stored_hash
    )
    return result

# ------------------------------------------------------------------
# STEP 4: EXECUTION COMMAND GENERATION (DRY-RUN ONLY)
# ------------------------------------------------------------------
def generate_execution_command(trade_id: int) -> Dict[str, Any]:
    """
    Generates a dry-run CLI command ONLY for an APPROVED trade.
    Enforces strict state and proposal integrity checks.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    # 1. REQUIRE APPROVED STATE
    if trade["status"] != TradeStatus.APPROVED.value:
        return {
            "status": "REJECTED", 
            "reason": f"Trade {trade_id} is '{trade['status']}'. Must be 'approved' to generate execution command."
        }
    
    # 2. VERIFY PROPOSAL INTEGRITY
    expires_at_str = trade.get("proposal_expires_at")
    if not expires_at_str:
        return {"status": "ERROR", "reason": "Missing proposal expiration."}
    
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
        risk_percent=trade["risk_percent"],
        risk_amount=trade["risk_amount"],
        portfolio_balance_at_time=trade["portfolio_balance"],
        agent_reasoning=trade.get("reasoning", ""),
        risk_decision="PASSED",
        expires_at=expires_at
    )
    computed_hash = proposal.compute_hash()
    stored_hash = trade.get("proposal_hash")
    
    if not stored_hash or computed_hash != stored_hash:
        return {"status": "REJECTED", "reason": "PROPOSAL TAMPERED: Hash mismatch."}
    
    # 3. USE DATABASE VALUES (DRY-RUN ONLY)
    return {
        "status": "SUCCESS",
        "trade_id": trade_id,
        "command": f"onchainos --dry-run {trade['side']} {trade['quantity']} {trade['symbol']}",
        "symbol": trade["symbol"],
        "side": trade["side"],
        "quantity": trade["quantity"],
        "message": "Copy and paste this command into your terminal to execute."
    }
# ------------------------------------------------------------------
# UNIFIED SCREEN (unchanged)
# ------------------------------------------------------------------
def screen_trade(trade_id: int) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {"status": "ERROR", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'proposed'."}
    
    symbol = trade["symbol"]
    side = trade["side"]
    entry = trade["entry_price"]
    stop = trade["stop_loss"]
    size = trade["quantity"]
    
    # TRUST BOUNDARY: evaluate_trade_risk fetches authoritative balance internally.
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=symbol, side=side, entry=entry, stop=stop, size=size
    )
    if risk_result["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.RISK_ENGINE, {"risk_result": risk_result})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": risk_result["reason"], "stage": "risk_engine"}
    
    exposure = guardrails_mcp.check_exposure_limit(size, entry)
    if exposure["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"exposure_result": exposure})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": exposure["reason"], "stage": "exposure_guardrail"}
    
    breaker = guardrails_mcp.check_circuit_breaker() or {"status": "OK", "reason": "No circuit breaker state"}
    if breaker.get("status") == "TRIPPED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"breaker_result": breaker})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": breaker["reason"], "stage": "circuit_breaker"}
    
    result1 = transition_trade(trade_id, TradeStatus.RISK_CHECKED, ActorType.RISK_ENGINE)
    if result1.get("status") not in ("SUCCESS", "success"):
        return result1
    
    result2 = transition_trade(trade_id, TradeStatus.AWAITING_APPROVAL, ActorType.RISK_ENGINE)
    if result2.get("status") not in ("SUCCESS", "success"):
        return result2
    
    return {
        "status": "SUCCESS",
        "trade_id": trade_id,
        "message": "Passed all gates. Awaiting human approval.",
        "risk_check": risk_result,
        "exposure_check": exposure,
        "circuit_breaker": breaker,
        "new_status": TradeStatus.AWAITING_APPROVAL.value
    }
# -----------------------------------------------------------------
# DASHBOARD INTEGRATION HELPERS
# -----------------------------------------------------------------
def dashboard_approve_trade(trade_id: int, approved_by: str = "dashboard_ui") -> Dict[str, Any]:
    """
    Finds the active approval token for a trade and consumes it via the standard approve_trade flow.
    Keeps the token hidden from the UI.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Find the most recent unused token for this trade
    cursor.execute("SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1", (trade_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"status": "ERROR", "reason": "No active approval token found for this trade."}
    
    return approve_trade(row[0], approved_by=approved_by)

def dashboard_reject_trade(trade_id: int, reason: str = "Rejected via dashboard") -> Dict[str, Any]:
    """Transitions a trade from AWAITING_APPROVAL to REJECTED."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
    result = transition_trade(trade_id, TradeStatus.REJECTED, ActorType.HUMAN, {"reason": reason})
    return result

    # ------------------------------------------------------------------
# DASHBOARD INTEGRATION HELPERS (Secure Wrappers)
# ------------------------------------------------------------------
def dashboard_approve_trade(trade_id: int, approved_by: str = "dashboard_ui") -> Dict[str, Any]:
    """
    Dashboard-safe wrapper. Finds the active approval token for a trade 
    and consumes it via the standard approve_trade flow.
    Keeps the token hidden from the browser.
    """
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Find the most recent unused token for this trade
    cursor.execute(
        "SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1", 
        (trade_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"status": "ERROR", "reason": "No active approval token found for this trade."}
    
    # Delegate to the authoritative cryptographic approval function
    return approve_trade(row[0], approved_by=approved_by)

def dashboard_reject_trade(trade_id: int, reason: str = "Rejected via dashboard") -> Dict[str, Any]:
    """
    Dashboard-safe wrapper. Transitions a trade from AWAITING_APPROVAL to REJECTED 
    using the state machine. Does not delete the trade.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
    # Delegate to the authoritative state machine transition
    result = transition_trade(trade_id, TradeStatus.REJECTED, ActorType.HUMAN, {"reason": reason})
    return result

    # ------------------------------------------------------------------
# DASHBOARD INTEGRATION HELPERS (Server-Side Token Management)
# ------------------------------------------------------------------
def dashboard_approve_trade(trade_id: int, approved_by: str = "dashboard_ui") -> Dict[str, Any]:
    """
    Server-side approval handler. Finds the active approval token for a trade 
    and consumes it via the standard approve_trade flow.
    Keeps the token hidden from the browser.
    """
    # Verify trade exists and is in correct state
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
    # Retrieve the server-side approval token
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1", 
        (trade_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {"status": "ERROR", "reason": "No active approval token found for this trade."}
    
    # Delegate to the authoritative cryptographic approval function
    return approve_trade(row[0], approved_by=approved_by)

def dashboard_reject_trade(trade_id: int, reason: str = "Rejected via dashboard") -> Dict[str, Any]:
    """
    Server-side rejection handler. Transitions a trade from AWAITING_APPROVAL to REJECTED 
    using the state machine. Does not delete the trade.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
    # Use the state machine for the transition
    result = transition_trade(trade_id, TradeStatus.REJECTED, ActorType.HUMAN, {"reason": reason})
    return result

# -----------------------------------------------------------------
# DASHBOARD INTEGRATION BRIDGE (Server-Side Token Resolution)
# -----------------------------------------------------------------
def dashboard_approve_trade(trade_id: int, approved_by: str = "dashboard_ui") -> Dict[str, Any]:
    """
    Server-side bridge for the dashboard. 
    Resolves the trade_id to a server-side token and delegates to approve_trade().
    The browser NEVER sees the token.
    """
    # 1. Verify trade state
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}

    # 2. Retrieve the server-side pending authorization token
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1", 
        (trade_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"status": "ERROR", "reason": "No active approval token found for this trade."}

    # 3. Delegate to existing cryptographic governance (preserves hash/policy/expiry checks)
    return approve_trade(row[0], approved_by=approved_by)

def dashboard_reject_trade(trade_id: int, reason: str = "Rejected via dashboard") -> Dict[str, Any]:
    """
    Server-side bridge for the dashboard.
    Uses the canonical state machine to reject the trade.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}

    # Delegate to the state machine
    return transition_trade(trade_id, TradeStatus.REJECTED, ActorType.HUMAN, {"reason": reason})

# ------------------------------------------------------------------
# DASHBOARD GOVERNANCE BRIDGE (Server-Side Token Resolution)
# ------------------------------------------------------------------
def dashboard_approve_trade(trade_id: int) -> Dict[str, Any]:
    """
    Resolves a trade_id to its server-side approval token and delegates 
    to the existing cryptographic approve_trade() primitive.
    The browser NEVER sees the token.
    """
    # 1. Verify trade exists and is in the correct state
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}

    # 2. Retrieve the server-side pending authorization token
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1", 
        (trade_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"status": "ERROR", "reason": "No active approval token found for this trade."}

    # 3. Delegate to existing cryptographic governance (preserves hash/policy/expiry checks)
    return approve_trade(row[0], approved_by="dashboard_ui")

def dashboard_reject_trade(trade_id: int) -> Dict[str, Any]:
    """
    Uses the canonical state machine to reject the trade.
    Does not delete the trade or bypass governance.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}

    return transition_trade(
        trade_id, 
        TradeStatus.REJECTED, 
        ActorType.HUMAN, 
        {"reason": "Rejected via dashboard"}
    )