#!/usr/bin/env python3
"""
Robo-Shopper V4 - Governance Engine.
Enforces the canonical trade lifecycle, cryptographic authorization, 
and the secure dashboard governance bridge.
"""
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
from state_machine import transition_trade
import trade_memory_mcp
import risk_management_mcp
import guardrails_mcp

# ------------------------------------------------------------------
# TOKEN MANAGEMENT HELPERS (Server-Side Only)
# ------------------------------------------------------------------
def _create_approval_token(trade_id: int, proposal_hash: str, policy_version: str, requested_by: str, conn: sqlite3.Connection) -> Dict[str, Any]:
    """Mints a cryptographically secure, one-time approval token."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    
    conn.execute(
        "INSERT INTO approval_tokens (trade_id, token_hash, policy_version, requested_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (trade_id, token_hash, policy_version, requested_by, expires_at.isoformat(), datetime.now(timezone.utc).isoformat())
    )
    return {"approval_token": token, "expires_at": expires_at.isoformat()}

def _validate_and_consume_token_in_transaction(conn: sqlite3.Connection, approval_token: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Validates token, checks expiry/replay, and marks as used. Returns (trade_id, token_hash, policy_version) or (None, None, None)."""
    token_hash = hashlib.sha256(approval_token.encode()).hexdigest()
    cursor = conn.execute(
        "SELECT id, trade_id, token_hash, policy_version, expires_at, used_at FROM approval_tokens WHERE token_hash = ?",
        (token_hash,)
    )
    row = cursor.fetchone()
    if not row:
        return None, None, None
    
    token_id, trade_id, stored_hash, policy_version, expires_at_str, used_at = row
    
    if used_at is not None:
        return None, None, None  # Replay protection
        
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
        
    if datetime.now(timezone.utc) > expires_at:
        return None, None, None  # Expiration
        
    conn.execute("UPDATE approval_tokens SET used_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), token_id))
    return trade_id, token_hash, policy_version

# ------------------------------------------------------------------
# 1. SCREENING (Deterministic Veto Gate)
# ------------------------------------------------------------------
def screen_trade(trade_id: int) -> Dict[str, Any]:
    """Runs deterministic risk, exposure, and circuit breaker checks."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {"status": "ERROR", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'proposed'."}
    
    # TRUST BOUNDARY: Do NOT pass portfolio_balance from the trade record.
    # The risk engine fetches the authoritative balance from the treasury.
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=trade["symbol"], side=trade["side"], 
        entry=trade["entry_price"], stop=trade["stop_loss"], 
        size=trade["quantity"]
    )
    
    if risk_result["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.RISK_ENGINE, {"risk_result": risk_result})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": risk_result["reason"], "stage": "risk_engine"}
    
    exposure = guardrails_mcp.check_exposure_limit(trade["quantity"], trade["entry_price"])
    if exposure["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"exposure_result": exposure})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": exposure["reason"], "stage": "exposure_guardrail"}
    
    breaker = guardrails_mcp.check_circuit_breaker() or {"status": "OK", "reason": "No circuit breaker state"}
    if breaker.get("status") == "TRIPPED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"breaker_result": breaker})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": breaker["reason"], "stage": "circuit_breaker"}
    
    transition_trade(trade_id, TradeStatus.RISK_CHECKED, ActorType.RISK_ENGINE)
    transition_trade(trade_id, TradeStatus.AWAITING_APPROVAL, ActorType.RISK_ENGINE)
    
    return {
        "status": "SUCCESS", "trade_id": trade_id,
        "message": "Passed all gates. Awaiting human approval.",
        "risk_check": risk_result, "exposure_check": exposure, "circuit_breaker": breaker,
        "new_status": TradeStatus.AWAITING_APPROVAL.value
    }

# ------------------------------------------------------------------
# 2. REQUEST APPROVAL (Mints Token)
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Mints a one-time approval token for an already screened trade."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade['status']}'. Must call screen_trade() first."}

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            conn.rollback(); return {"status": "ERROR", "reason": "Trade not found."}
        
        cols = [c[0] for c in conn.execute("SELECT * FROM trades LIMIT 1").description]
        trade_data = dict(zip(cols, row))
        
        entry = trade_data["entry_price"]; stop = trade_data["stop_loss"]; qty = trade_data["quantity"]
        balance = trade_data.get("portfolio_balance") or 10000.0
        risk_amount = trade_data.get("risk_amount") or abs(entry - stop) * qty
        risk_percent = trade_data.get("risk_percent") or (risk_amount / balance if balance > 0 else 0.02)
        
        expires_at_str = trade_data.get("proposal_expires_at")
        if not expires_at_str:
            conn.rollback(); return {"status": "REJECTED", "reason": "Trade has no expiration set."}

        proposal = TradeProposal(
            asset=trade_data["symbol"], side=trade_data["side"], entry_price=entry, stop_loss=stop,
            take_profit=trade_data.get("take_profit"), quantity=qty, risk_percent=risk_percent,
            risk_amount=risk_amount, portfolio_balance_at_time=balance,
            agent_reasoning=trade_data.get("reasoning", ""), risk_decision="PENDING",
            expires_at=datetime.fromisoformat(expires_at_str),
        )
        proposal_hash = proposal.compute_hash()
        policy_version = proposal.policy_version

        conn.execute("UPDATE trades SET proposal_hash = ?, policy_version = ?, proposal_expires_at = ? WHERE id = ?",
                     (proposal_hash, policy_version, expires_at_str, trade_id))
        
        token_result = _create_approval_token(trade_id, proposal_hash, policy_version, requested_by, conn)
        conn.commit()
        
        return {
            "status": "success", "trade_id": trade_id,
            "approval_token": token_result["approval_token"],
            "expires_at": token_result["expires_at"],
            "proposal_hash": proposal_hash, "policy_version": policy_version,
        }
    except Exception as e:
        try: conn.rollback()
        except: pass
        return {"status": "ERROR", "reason": f"request_approval exception: {e}"}
    finally:
        conn.close()

# ------------------------------------------------------------------
# 3. APPROVE TRADE (Consumes Token & Transitions State)
# ------------------------------------------------------------------
def approve_trade(approval_token: str, approved_by: str = "system") -> Dict[str, Any]:
    """Validates the token and transitions the trade to APPROVED."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    try:
        trade_id, token_hash, token_policy = _validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None:
            conn.rollback(); conn.close()
            return {"status": "REJECTED", "reason": "Invalid, expired, or already used token."}
        
        trade = trade_memory_mcp.get_trade(trade_id)
        if not trade or trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback(); conn.close()
            return {"status": "REJECTED", "reason": f"Trade is {trade['status'] if trade else 'missing'}, must be 'awaiting_approval'."}
        
        # Defense-in-depth: Verify proposal hash match
        if trade.get("proposal_hash") != token_hash:
            conn.rollback(); conn.close()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: token_hash != trade_hash."}
        if trade.get("policy_version") != token_policy:
            conn.rollback(); conn.close()
            return {"status": "REJECTED", "reason": "POLICY MISMATCH."}
        
        result = transition_trade(trade_id, TradeStatus.APPROVED, ActorType.HUMAN, {"approved_by": approved_by, "proposal_hash": token_hash}, conn=conn)
        if result["status"] != "SUCCESS":
            conn.rollback(); conn.close()
            return result
        
        conn.commit(); conn.close()
        return {"status": "SUCCESS", "trade_id": trade_id, "new_status": TradeStatus.APPROVED.value, "approved_by": approved_by}
    except Exception as e:
        conn.rollback(); conn.close()
        return {"status": "ERROR", "reason": str(e)}

# ------------------------------------------------------------------
# 4. EXECUTE TRADE
# ------------------------------------------------------------------
def execute_trade(trade_id: int, execution_price: float, executed_by: str = "execution_gateway") -> Dict[str, Any]:
    """Transitions an APPROVED trade to EXECUTED."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] == TradeStatus.EXECUTED.value:
        return {"status": "SUCCESS", "new_status": TradeStatus.EXECUTED.value, "idempotent": True}
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'approved'."}
    
    stored_hash = trade.get("proposal_hash")
    if not stored_hash: return {"status": "REJECTED", "reason": "No proposal hash."}
    
    # Recompute hash to verify no tampering
    expires_at_str = trade.get("proposal_expires_at")
    expires_at = datetime.fromisoformat(expires_at_str) if expires_at_str else datetime.now(timezone.utc)
    if expires_at.tzinfo is None: expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    proposal = TradeProposal(
        asset=trade["symbol"], side=trade["side"], entry_price=trade["entry_price"], stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"), quantity=trade["quantity"], risk_percent=trade["risk_percent"],
        risk_amount=trade["risk_amount"], portfolio_balance_at_time=trade["portfolio_balance"],
        agent_reasoning=trade.get("reasoning", ""), risk_decision="PASSED", expires_at=expires_at
    )
    computed_hash = proposal.compute_hash()
    if computed_hash != stored_hash:
        return {"status": "REJECTED", "reason": "PROPOSAL TAMPERED: Hash mismatch.", "stored": stored_hash, "computed": computed_hash}
    
    return transition_trade(trade_id, TradeStatus.EXECUTED, ActorType.EXECUTION_GATEWAY, {"execution_price": execution_price, "executed_by": executed_by, "proposal_hash": stored_hash}, require_approval_hash=stored_hash)

# ------------------------------------------------------------------
# 5. EXECUTION GATEWAY (Dry-Run Command Generation)
# ------------------------------------------------------------------
def generate_execution_command(trade_id: int) -> Dict[str, Any]:
    """Generates a dry-run CLI command ONLY for an APPROVED trade. Enforces strict state and hash checks."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade['status']}'. Must be 'approved' to generate execution command."}
    
    expires_at_str = trade.get("proposal_expires_at")
    if not expires_at_str: return {"status": "ERROR", "reason": "Missing proposal expiration."}
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None: expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    proposal = TradeProposal(
        asset=trade["symbol"], side=trade["side"], entry_price=trade["entry_price"], stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"), quantity=trade["quantity"], risk_percent=trade["risk_percent"],
        risk_amount=trade["risk_amount"], portfolio_balance_at_time=trade["portfolio_balance"],
        agent_reasoning=trade.get("reasoning", ""), risk_decision="PASSED", expires_at=expires_at
    )
    computed_hash = proposal.compute_hash()
    stored_hash = trade.get("proposal_hash")
    
    if not stored_hash or computed_hash != stored_hash:
        return {"status": "REJECTED", "reason": "PROPOSAL TAMPERED: Hash mismatch."}
    
    return {
        "status": "SUCCESS", "trade_id": trade_id,
        "command": f"onchainos --dry-run {trade['side']} {trade['quantity']} {trade['symbol']}",
        "symbol": trade["symbol"], "side": trade["side"], "quantity": trade["quantity"],
        "message": "Copy and paste this command into your terminal to execute."
    }

# ------------------------------------------------------------------
# 6. DASHBOARD GOVERNANCE BRIDGE (P0 SECURE INTEGRATION)
# ------------------------------------------------------------------
def dashboard_approve_trade(trade_id: int) -> Dict[str, Any]:
    """
    Server-side bridge: resolves trade_id to its approval token and delegates
    to the existing cryptographic approve_trade() primitive.
    The browser NEVER sees the token.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
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
    
    # Delegate to existing cryptographic governance (preserves hash/policy/expiry checks)
    return approve_trade(row[0], approved_by="human_dashboard")

def dashboard_reject_trade(trade_id: int) -> Dict[str, Any]:
    """
    Server-side bridge: uses the canonical state machine to reject the trade.
    Does not delete the trade or bypass governance.
    """
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
    return transition_trade(trade_id, TradeStatus.REJECTED, ActorType.HUMAN, {"reason": "Rejected via dashboard"})