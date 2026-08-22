#!/usr/bin/env python3
"""
Robo-Shopper V4 - Governance Engine (Final Production Build).
Enforces the canonical trade lifecycle, cryptographic authorization, 
and the secure dashboard governance bridge.
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

# Ensure data directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def _ensure_schema():
    """Ensures the approval_tokens table has the correct schema and enables WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA journal_mode=WAL;")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            token TEXT,
            token_hash TEXT NOT NULL,
            proposal_hash TEXT,
            policy_version TEXT,
            requested_by TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            used_at TEXT
        )
    """)
    
    try:
        cursor.execute("ALTER TABLE approval_tokens ADD COLUMN token TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE approval_tokens ADD COLUMN proposal_hash TEXT")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()

_ensure_schema()

# ------------------------------------------------------------------
# SHARED HELPER: Compute proposal hash EXACTLY from stored DB values
# ------------------------------------------------------------------
def _get_proposal_hash(trade: Dict[str, Any]) -> str:
    """
    Computes the proposal hash using EXACT stored database values.
    No fallback logic – any missing field raises KeyError.
    This guarantees perfect consistency with the original hash.
    """
    entry = float(trade["entry_price"])
    stop = float(trade["stop_loss"])
    qty = float(trade["quantity"])
    balance = float(trade["portfolio_balance"])

    # Use stored risk metrics directly – no recomputation!
    risk_amount = float(trade["risk_amount"])
    risk_percent = float(trade["risk_percent"])

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
    """Mints a cryptographically secure, one-time approval token."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    
    conn.execute(
        "INSERT INTO approval_tokens (trade_id, token, token_hash, proposal_hash, policy_version, requested_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, token, token_hash, proposal_hash, policy_version, requested_by, expires_at.isoformat(), datetime.now(timezone.utc).isoformat())
    )
    return {"approval_token": token, "expires_at": expires_at.isoformat()}

def _validate_and_consume_token_in_transaction(conn: sqlite3.Connection, approval_token: str) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """Validates token, checks expiry/replay, and marks as used."""
    token_hash = hashlib.sha256(approval_token.encode()).hexdigest()
    cursor = conn.execute(
        "SELECT id, trade_id, token_hash, proposal_hash, policy_version, expires_at, used_at FROM approval_tokens WHERE token_hash = ?",
        (token_hash,)
    )
    row = cursor.fetchone()
    if not row: return None, None, None, None
    
    token_id, trade_id, stored_hash, token_proposal_hash, policy_version, expires_at_str, used_at = row
    if used_at is not None: return None, None, None, None
        
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None: expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at: return None, None, None, None
        
    conn.execute("UPDATE approval_tokens SET used_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), token_id))
    return trade_id, token_hash, token_proposal_hash, policy_version

# ------------------------------------------------------------------
# 1. SCREENING (Deterministic Veto Gate)
# ------------------------------------------------------------------
def screen_trade(trade_id: int) -> Dict[str, Any]:
    """Runs deterministic risk, exposure, and circuit breaker checks."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}."}
    
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=trade["symbol"], side=trade["side"], 
        entry=trade["entry_price"], stop=trade["stop_loss"], 
        size=trade["quantity"]
    )
    if risk_result["status"] == "REJECTED":
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("UPDATE trades SET status = 'rejected', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), trade_id))
        conn.commit()
        conn.close()
        return {"status": "REJECTED", "reason": risk_result["reason"]}
    
    exposure = guardrails_mcp.check_exposure_limit(trade["quantity"], trade["entry_price"])
    if exposure["status"] == "REJECTED":
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("UPDATE trades SET status = 'rejected', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), trade_id))
        conn.commit()
        conn.close()
        return {"status": "REJECTED", "reason": exposure["reason"]}
    
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("UPDATE trades SET status = 'awaiting_approval', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), trade_id))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS", "message": "Passed all gates."}

# ------------------------------------------------------------------
# 2. REQUEST APPROVAL (Mints Token)
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Mints a one-time approval token for an already screened trade."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "REJECTED", "reason": f"Trade is {trade['status']}. Must call screen_trade() first."}

    if not trade.get("proposal_expires_at"):
        return {"status": "REJECTED", "reason": "No expiration set."}
    
    # Use shared helper for consistent hash computation
    proposal_hash = _get_proposal_hash(trade)
    policy_version = "1.0.0"

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT id FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            conn.rollback(); return {"status": "ERROR", "reason": "Trade not found in DB."}
        
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
        try: conn.rollback()
        except: pass
        return {"status": "ERROR", "reason": f"Exception: {e}"}
    finally:
        conn.close()

# ------------------------------------------------------------------
# 3. APPROVE TRADE (Consumes Token & Transitions State)
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
        
        row = conn.execute("SELECT id, status, proposal_hash, policy_version FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            conn.rollback()
            return {"status": "REJECTED", "reason": "Trade not found."}
        
        tid, status, trade_proposal_hash, trade_policy_version = row
        
        if status != "awaiting_approval":
            conn.rollback()
            return {"status": "REJECTED", "reason": f"Trade is {status}."}
        
        if trade_proposal_hash != token_proposal_hash:
            conn.rollback()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: trade modified after token minted."}
        
        if trade_policy_version != token_policy:
            conn.rollback()
            return {"status": "REJECTED", "reason": "POLICY MISMATCH: trade policy version changed after token minted."}
        
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE trades SET status = 'approved', updated_at = ? WHERE id = ?", (now, trade_id))
        
        conn.commit()
        return {"status": "SUCCESS", "trade_id": trade_id, "new_status": "approved"}
        
    except Exception as e:
        try: conn.rollback()
        except: pass
        return {"status": "ERROR", "reason": str(e)}
    finally:
        conn.close()

# ------------------------------------------------------------------
# 4. EXECUTE TRADE (With Hash Verification)
# ------------------------------------------------------------------
def execute_trade(trade_id: int, execution_price: float, executed_by: str = "execution_gateway") -> Dict[str, Any]:
    """Transitions an APPROVED trade to EXECUTED with hash verification."""
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
    
    # Use shared helper for consistent hash computation
    computed_hash = _get_proposal_hash(trade)
    
    if computed_hash != stored_hash:
        return {"status": "REJECTED", "reason": "PROPOSAL TAMPERED: Hash mismatch."}
    
    return transition_trade(trade_id, TradeStatus.EXECUTED, ActorType.EXECUTION_GATEWAY, {"execution_price": execution_price, "executed_by": executed_by})

# ------------------------------------------------------------------
# 5. DASHBOARD GOVERNANCE BRIDGE
# ------------------------------------------------------------------
def dashboard_approve_trade(trade_id: int) -> Dict[str, Any]:
    """
    Server-side bridge: resolves trade_id to its raw approval token and delegates
    to the existing cryptographic approve_trade() primitive.
    The browser NEVER sees the token.
    """
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
        try: conn.close()
        except: pass
        return {"status": "ERROR", "reason": str(e)}

def dashboard_reject_trade(trade_id: int) -> Dict[str, Any]:
    """
    Server-side bridge: uses the CANONICAL state machine to reject the trade.
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

# ------------------------------------------------------------------
# 6. EXECUTION GATEWAY (Dry-Run Command Generation)
# ------------------------------------------------------------------
def generate_execution_command(trade_id: int) -> Dict[str, Any]:
    """Generates a dry-run CLI command ONLY for an APPROVED trade (not yet executed)."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] == TradeStatus.EXECUTED.value:
        return {"status": "REJECTED", "reason": "Trade already executed."}
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade is {trade['status']}. Must be 'approved'."}
    
    # Use shared helper for consistent hash verification
    computed_hash = _get_proposal_hash(trade)
    stored_hash = trade.get("proposal_hash")
    
    if not stored_hash or computed_hash != stored_hash:
        return {"status": "REJECTED", "reason": "PROPOSAL TAMPERED: Hash mismatch."}
    
    return {
        "status": "SUCCESS", "trade_id": trade_id,
        "command": f"onchainos --dry-run {trade['side']} {trade['quantity']} {trade['symbol']}",
        "symbol": trade["symbol"], "side": trade["side"], "quantity": trade["quantity"]
    }