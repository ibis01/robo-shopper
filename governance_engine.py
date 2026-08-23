#!/usr/bin/env python3
"""
Robo-Shopper V4 - Governance Engine (Final Production Build).
"""
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
from state_machine import transition_trade
import trade_memory_mcp
import risk_management_mcp
import guardrails_mcp

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def _ensure_schema():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            token_hash TEXT NOT NULL UNIQUE,
            proposal_hash TEXT,
            policy_version TEXT,
            requested_by TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            used_at TEXT
        )
    """)
    conn.commit()
    conn.close()

_ensure_schema()

# ------------------------------------------------------------------
# SHARED HELPER: Compute hash from core parameters (deterministic)
# ------------------------------------------------------------------
def _get_proposal_hash(trade: Dict[str, Any]) -> str:
    entry = float(trade["entry_price"])
    stop = float(trade["stop_loss"])
    qty = float(trade["quantity"])
    balance = float(trade["portfolio_balance"])

    risk_per_unit = abs(entry - stop)
    risk_amount = round(risk_per_unit * qty, 8)
    risk_percent = round(risk_amount / balance, 6) if balance > 0 else 0.02

    if risk_percent > 1.0:
        risk_percent = 1.0
        risk_amount = risk_percent * balance

    # 🔒 FAIL CLOSED: proposal_expires_at must exist
    expires_at_str = trade["proposal_expires_at"]
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    take_profit = trade.get("take_profit")
    agent_reasoning = trade.get("reasoning") or ""

    proposal = TradeProposal(
        asset=str(trade["symbol"]),
        side=str(trade["side"]),
        entry_price=entry,
        stop_loss=stop,
        take_profit=take_profit,
        quantity=qty,
        risk_percent=risk_percent,
        risk_amount=risk_amount,
        portfolio_balance_at_time=balance,
        agent_reasoning=agent_reasoning,
        risk_decision="PENDING",
        expires_at=expires_at
    )
    return proposal.compute_hash()

# ------------------------------------------------------------------
# TOKEN MANAGEMENT
# ------------------------------------------------------------------
def _create_approval_token(trade_id: int, proposal_hash: str, policy_version: str, requested_by: str, conn: sqlite3.Connection) -> Dict[str, Any]:
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    conn.execute(
        "INSERT INTO approval_tokens (trade_id, token, token_hash, proposal_hash, policy_version, requested_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, token, token_hash, proposal_hash, policy_version, requested_by, expires_at.isoformat(), datetime.now(timezone.utc).isoformat())
    )
    return {"approval_token": token, "expires_at": expires_at.isoformat()}

def _validate_and_consume_token_in_transaction(conn: sqlite3.Connection, approval_token: str) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    token_hash = hashlib.sha256(approval_token.encode()).hexdigest()
    cursor = conn.execute(
        "SELECT id, trade_id, token_hash, proposal_hash, policy_version, expires_at, used_at FROM approval_tokens WHERE token_hash = ?",
        (token_hash,)
    )
    row = cursor.fetchone()
    if not row:
        return None, None, None, None
    token_id, trade_id, stored_hash, token_proposal_hash, policy_version, expires_at_str, used_at = row
    if used_at is not None:
        return None, None, None, None
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return None, None, None, None
    conn.execute("UPDATE approval_tokens SET used_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), token_id))
    return trade_id, token_hash, token_proposal_hash, policy_version

# ------------------------------------------------------------------
# 1. SCREENING (two-step transition to enforce state machine)
# ------------------------------------------------------------------
def screen_trade(trade_id: int) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}."}
    
    # Check risk
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=trade["symbol"], side=trade["side"],
        entry=trade["entry_price"], stop=trade["stop_loss"],
        size=trade["quantity"]
    )
    if risk_result["status"] == "REJECTED":
        # Transition the trade to REJECTED state (for audit trail)
        transition_trade(
            trade_id,
            TradeStatus.REJECTED,
            ActorType.RISK_ENGINE,
            {"risk_result": risk_result}
        )
        # Return REJECTED status to the caller (so tests can assert it)
        return {"status": "REJECTED", "reason": risk_result["reason"], "details": risk_result}
    
    # Check exposure
    exposure = guardrails_mcp.check_exposure_limit(trade["quantity"], trade["entry_price"])
    if exposure["status"] == "REJECTED":
        transition_trade(
            trade_id,
            TradeStatus.REJECTED,
            ActorType.GUARDRAIL,
            {"exposure_result": exposure}
        )
        return {"status": "REJECTED", "reason": exposure["reason"], "details": exposure}
    
    # Pass: PROPOSED → RISK_CHECKED → AWAITING_APPROVAL
    result1 = transition_trade(
        trade_id,
        TradeStatus.RISK_CHECKED,
        ActorType.RISK_ENGINE,
        {"message": "Risk checks passed"}
    )
    if result1["status"] != "SUCCESS":
        return result1
    
    result2 = transition_trade(
        trade_id,
        TradeStatus.AWAITING_APPROVAL,
        ActorType.RISK_ENGINE,
        {"message": "Awaiting human approval"}
    )
    return result2

# ------------------------------------------------------------------
# 2. REQUEST APPROVAL (Idempotent)
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "REJECTED", "reason": f"Trade is {trade['status']}. Must call screen_trade() first."}
    if not trade.get("proposal_expires_at"):
        return {"status": "REJECTED", "reason": "No expiration set."}
    
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT token, expires_at, proposal_hash, policy_version FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL AND expires_at > ?",
        (trade_id, datetime.now(timezone.utc).isoformat())
    )
    existing = cursor.fetchone()
    if existing:
        token, expires_at, stored_hash, stored_policy = existing
        conn.close()
        return {
            "status": "success",
            "trade_id": trade_id,
            "approval_token": token,
            "expires_at": expires_at,
            "proposal_hash": stored_hash,
            "policy_version": stored_policy,
            "message": "Existing active token reused."
        }

    proposal_hash = _get_proposal_hash(trade)
    policy_version = "1.0.0"

    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT id FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            conn.rollback()
            return {"status": "ERROR", "reason": "Trade not found in DB."}
        conn.execute("UPDATE trades SET proposal_hash = ?, policy_version = ? WHERE id = ?",
                     (proposal_hash, policy_version, trade_id))
        token_result = _create_approval_token(trade_id, proposal_hash, policy_version, requested_by, conn)
        conn.commit()
        return {
            "status": "success", "trade_id": trade_id,
            "approval_token": token_result["approval_token"],
            "expires_at": token_result["expires_at"],
            "proposal_hash": proposal_hash, "policy_version": policy_version,
        }
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        return {"status": "ERROR", "reason": f"Exception: {e}"}
    finally:
        conn.close()

# ------------------------------------------------------------------
# 3. APPROVE TRADE (with independent hash recomputation)
# ------------------------------------------------------------------
def approve_trade(approval_token: str, approved_by: str = "system") -> Dict[str, Any]:
    """Validates the token and transitions the trade to APPROVED."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        conn.execute("BEGIN EXCLUSIVE")
        
        trade_id, token_hash, token_proposal_hash, token_policy = _validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None:
            conn.rollback()
            return {"status": "REJECTED", "reason": "Invalid, expired, or used token."}
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, status, proposal_hash, policy_version,
                   entry_price, quantity, stop_loss, portfolio_balance,
                   risk_percent, risk_amount, proposal_expires_at,
                   symbol, side, take_profit, reasoning
            FROM trades WHERE id = ?
        """, (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return {"status": "REJECTED", "reason": "Trade not found."}
        
        col_names = [
            "id", "status", "proposal_hash", "policy_version",
            "entry_price", "quantity", "stop_loss", "portfolio_balance",
            "risk_percent", "risk_amount", "proposal_expires_at",
            "symbol", "side", "take_profit", "reasoning"
        ]
        trade = dict(zip(col_names, row))
        
        current_hash = _get_proposal_hash(trade)
        if current_hash != token_proposal_hash:
            conn.rollback()
            return {
                "status": "REJECTED",
                "reason": f"PROPOSAL TAMPERED: trade modified after token minted. "
                          f"Token: {token_proposal_hash[:12]}... Current: {current_hash[:12]}..."
            }
        
        tid, status, trade_proposal_hash, trade_policy_version = row[:4]
        if status != "awaiting_approval":
            conn.rollback()
            return {"status": "REJECTED", "reason": f"Trade is {status}."}
        if trade_proposal_hash != token_proposal_hash:
            conn.rollback()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: stored hash differs from token."}
        if trade_policy_version != token_policy:
            conn.rollback()
            return {"status": "REJECTED", "reason": "POLICY MISMATCH: trade policy version changed after token minted."}
        
        # Use transition_trade to log audit event
        result = transition_trade(
            trade_id,
            TradeStatus.APPROVED,
            ActorType.HUMAN,
            {"approved_by": approved_by, "proposal_hash": token_proposal_hash},
            conn=conn  # pass the connection to stay in transaction
        )
        if result["status"] != "SUCCESS":
            conn.rollback()
            return result
        
        conn.commit()
        return {"status": "SUCCESS", "trade_id": trade_id, "new_status": "approved"}
        
    except Exception as e:
        try:
            conn.rollback()
        except:
            pass
        return {"status": "ERROR", "reason": str(e)}
    finally:
        conn.close()

# ------------------------------------------------------------------
# 4. EXECUTE TRADE (with idempotency, uses transition_trade)
# ------------------------------------------------------------------
def execute_trade(trade_id: int, execution_price: float, executed_by: str = "execution_gateway") -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    if trade["status"] == TradeStatus.EXECUTED.value:
        return {"status": "SUCCESS", "new_status": TradeStatus.EXECUTED.value, "idempotent": True}
    
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'approved'."}
    
    stored_hash = trade.get("proposal_hash")
    if not stored_hash:
        return {"status": "REJECTED", "reason": "No proposal hash."}
    
    computed_hash = _get_proposal_hash(trade)
    if computed_hash != stored_hash:
        return {
            "status": "REJECTED",
            "reason": f"PROPOSAL TAMPERED: Hash mismatch. Stored: {stored_hash[:12]}... Computed: {computed_hash[:12]}...",
            "stored_hash": stored_hash,
            "computed_hash": computed_hash
        }
    
    return transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.EXECUTION_GATEWAY,
        {"execution_price": execution_price, "executed_by": executed_by},
        require_approval_hash=stored_hash
    )

# ------------------------------------------------------------------
# 5. DASHBOARD GOVERNANCE BRIDGE
# ------------------------------------------------------------------
def dashboard_approve_trade(trade_id: int) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
            (trade_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"status": "ERROR", "reason": "No active approval token found."}
        token = row[0]
        conn.close()
        return approve_trade(token, approved_by="human_dashboard")
    except Exception as e:
        try:
            conn.close()
        except:
            pass
        return {"status": "ERROR", "reason": str(e)}

def dashboard_reject_trade(trade_id: int) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}, must be awaiting_approval."}
    # Use transition_trade to log audit event
    return transition_trade(
        trade_id,
        TradeStatus.REJECTED,
        ActorType.HUMAN,
        {"reason": "Rejected via dashboard"}
    )

# ------------------------------------------------------------------
# 6. EXECUTION GATEWAY
# ------------------------------------------------------------------
def generate_execution_command(trade_id: int) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] == TradeStatus.EXECUTED.value:
        return {"status": "REJECTED", "reason": "Trade already executed."}
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade is {trade['status']}. Must be 'approved'."}
    
    computed_hash = _get_proposal_hash(trade)
    stored_hash = trade.get("proposal_hash")
    if not stored_hash or computed_hash != stored_hash:
        return {"status": "REJECTED", "reason": "PROPOSAL TAMPERED: Hash mismatch."}
    
    return {
        "status": "SUCCESS", "trade_id": trade_id,
        "command": f"onchainos --dry-run {trade['side']} {trade['quantity']} {trade['symbol']}",
        "symbol": trade["symbol"], "side": trade["side"], "quantity": trade["quantity"]
    }