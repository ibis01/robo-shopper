"""
Robo-Shopper V4 - One-Time Approval Tokens (Sprint 5).
Transaction‑aware token validation for atomic approval.
"""
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

from config import DB_PATH

def create_approval_token(
    trade_id: int, 
    proposal_hash: str, 
    policy_version: str,
    requested_by: str = "ai"
) -> Dict[str, Any]:
    """Create a one‑time token bound to the exact proposal hash."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=1)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO approval_tokens 
        (token, trade_id, proposal_hash, policy_version, requested_by, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (token, trade_id, proposal_hash, policy_version, requested_by, expires_at.isoformat()))
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "approval_token": token,
        "trade_id": trade_id,
        "proposal_hash": proposal_hash,
        "policy_version": policy_version,
        "expires_at": expires_at.isoformat()
    }

def validate_and_consume_token_in_transaction(conn: sqlite3.Connection, token: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Validates and consumes the token INSIDE an existing transaction.
    Returns (trade_id, proposal_hash, policy_version) if valid, else (None, None, None).
    
    The caller manages the transaction (BEGIN/COMMIT/ROLLBACK).
    """
    cursor = conn.cursor()
    
    # 1. Select token with FOR UPDATE (locking) to prevent race conditions
    # SQLite doesn't have SELECT ... FOR UPDATE, but we can use BEGIN EXCLUSIVE.
    cursor.execute("""
        SELECT id, trade_id, proposal_hash, policy_version, expires_at, used_at
        FROM approval_tokens
        WHERE token = ?
    """, (token,))
    row = cursor.fetchone()
    
    if not row:
        return None, None, None
    
    token_id, trade_id, proposal_hash, policy_version, expires_at_str, used_at = row
    expires_at = datetime.fromisoformat(expires_at_str)
    
    # 2. Validate
    if datetime.utcnow() > expires_at:
        return None, None, None
    if used_at is not None:
        return None, None, None
    
    # 3. Mark as used (atomic update within the same transaction)
    cursor.execute("""
        UPDATE approval_tokens
        SET used_at = ?
        WHERE id = ? AND used_at IS NULL
    """, (datetime.utcnow().isoformat(), token_id))
    
    if cursor.rowcount == 0:
        return None, None, None
    
    return trade_id, proposal_hash, policy_version