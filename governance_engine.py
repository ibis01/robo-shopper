#!/usr/bin/env python3
"""
Robo-Shopper V4 - Governance Engine (Final P0 Fix).
"""
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
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
    try: cursor.execute("ALTER TABLE approval_tokens ADD COLUMN token TEXT")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE approval_tokens ADD COLUMN proposal_hash TEXT")
    except sqlite3.OperationalError: pass
    conn.commit()
    conn.close()

_ensure_schema()

def _create_approval_token(trade_id, proposal_hash, policy_version, requested_by, conn):
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    conn.execute(
        "INSERT INTO approval_tokens (trade_id, token, token_hash, proposal_hash, policy_version, requested_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, token, token_hash, proposal_hash, policy_version, requested_by, expires_at.isoformat(), datetime.now(timezone.utc).isoformat())
    )
    return {"approval_token": token, "expires_at": expires_at.isoformat()}

def _validate_and_consume_token_in_transaction(conn, approval_token):
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

def screen_trade(trade_id):
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {"status": "ERROR", "reason": f"Trade is {trade['status']}."}
    risk_result = risk_management_mcp.evaluate_trade_risk(symbol=trade["symbol"], side=trade["side"], entry=trade["entry_price"], stop=trade["stop_loss"], size=trade["quantity"])
    if risk_result["status"] == "REJECTED":
        conn = sqlite3.connect(DB_PATH, timeout=30); conn.execute("PRAGMA journal_mode=WAL;"); conn.execute("UPDATE trades SET status = 'rejected', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), trade_id)); conn.commit(); conn.close()
        return {"status": "REJECTED", "reason": risk_result["reason"]}
    exposure = guardrails_mcp.check_exposure_limit(trade["quantity"], trade["entry_price"])
    if exposure["status"] == "REJECTED":
        conn = sqlite3.connect(DB_PATH, timeout=30); conn.execute("PRAGMA journal_mode=WAL;"); conn.execute("UPDATE trades SET status = 'rejected', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), trade_id)); conn.commit(); conn.close()
        return {"status": "REJECTED", "reason": exposure["reason"]}
    conn = sqlite3.connect(DB_PATH, timeout=30); conn.execute("PRAGMA journal_mode=WAL;"); conn.execute("UPDATE trades SET status = 'awaiting_approval', updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), trade_id)); conn.commit(); conn.close()
    return {"status": "SUCCESS", "message": "Passed all gates."}

def request_approval(trade_id, requested_by="ai"):
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {"status": "REJECTED", "reason": f"Trade is {trade['status']}. Must call screen_trade() first."}
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        conn.execute("BEGIN EXCLUSIVE")
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row: conn.rollback(); return {"status": "ERROR", "reason": "Trade not found in DB."}
        cols = [c[0] for c in conn.execute("SELECT * FROM trades LIMIT 1").description]
        trade_data = dict(zip(cols, row))
        entry = trade_data["entry_price"]; stop = trade_data["stop_loss"]; qty = trade_data["quantity"]
        balance = trade_data.get("portfolio_balance") or 10000.0
        risk_amount = trade_data.get("risk_amount") or abs(entry - stop) * qty
        risk_percent = trade_data.get("risk_percent") or (risk_amount / balance if balance > 0 else 0.02)
        expires_at_str = trade_data.get("proposal_expires_at")
        if not expires_at_str: conn.rollback(); return {"status": "REJECTED", "reason": "No expiration set."}
        proposal = TradeProposal(asset=trade_data["symbol"], side=trade_data["side"], entry_price=entry, stop_loss=stop, take_profit=trade_data.get("take_profit"), quantity=qty, risk_percent=risk_percent, risk_amount=risk_amount, portfolio_balance_at_time=balance, agent_reasoning=trade_data.get("reasoning", ""), risk_decision="PENDING", expires_at=datetime.fromisoformat(expires_at_str))
        proposal_hash = proposal.compute_hash()
        policy_version = proposal.policy_version
        conn.execute("UPDATE trades SET proposal_hash = ?, policy_version = ? WHERE id = ?", (proposal_hash, policy_version, trade_id))
        token_result = _create_approval_token(trade_id, proposal_hash, policy_version, requested_by, conn)
        conn.commit()
        return {"status": "success", "trade_id": trade_id, "approval_token": token_result["approval_token"], "expires_at": token_result["expires_at"], "proposal_hash": proposal_hash, "policy_version": policy_version}
    except Exception as e:
        try: conn.rollback()
        except: pass
        return {"status": "ERROR", "reason": f"Exception: {e}"}
    finally: conn.close()

def approve_trade(approval_token, approved_by="system"):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        conn.execute("BEGIN EXCLUSIVE")
        trade_id, token_hash, token_proposal_hash, token_policy = _validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None: conn.rollback(); return {"status": "REJECTED", "reason": "Invalid, expired, or used token."}
        row = conn.execute("SELECT id, status, proposal_hash FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row: conn.rollback(); return {"status": "REJECTED", "reason": "Trade not found."}
        tid, status, trade_proposal_hash = row
        if status != "awaiting_approval": conn.rollback(); return {"status": "REJECTED", "reason": f"Trade is {status}."}
        if trade_proposal_hash != token_proposal_hash:
            conn.rollback()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: trade modified after token minted."}
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE trades SET status = 'approved', updated_at = ? WHERE id = ?", (now, trade_id))
        conn.commit()
        return {"status": "SUCCESS", "trade_id": trade_id, "new_status": "approved"}
    except Exception as e:
        try: conn.rollback()
        except: pass
        return {"status": "ERROR", "reason": str(e)}
    finally: conn.close()

def dashboard_approve_trade(trade_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT token FROM approval_tokens WHERE trade_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1", (trade_id,))
        row = cursor.fetchone()
        if not row: return {"status": "ERROR", "reason": "No active approval token found."}
        conn.close()
        return approve_trade(row[0], approved_by="human_dashboard")
    except Exception as e:
        try: conn.close()
        except: pass
        return {"status": "ERROR", "reason": str(e)}

def dashboard_reject_trade(trade_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        row = conn.execute("SELECT status FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row: return {"status": "ERROR", "reason": "Trade not found."}
        if row[0] != "awaiting_approval": return {"status": "ERROR", "reason": f"Trade is {row[0]}."}
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE trades SET status = 'rejected', updated_at = ? WHERE id = ?", (now, trade_id))
        conn.commit()
        return {"status": "SUCCESS", "message": "Trade rejected."}
    except Exception as e:
        try: conn.rollback()
        except: pass
        return {"status": "ERROR", "reason": str(e)}
    finally: conn.close()

def generate_execution_command(trade_id):
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade: return {"status": "ERROR", "reason": "Trade not found."}
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade is {trade['status']}. Must be approved."}
    return {"status": "SUCCESS", "trade_id": trade_id, "command": f"onchainos --dry-run {trade['side']} {trade['quantity']} {trade['symbol']}", "symbol": trade["symbol"], "side": trade["side"], "quantity": trade["quantity"]}
