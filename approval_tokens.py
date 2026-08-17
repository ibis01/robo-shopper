"""
Robo-Shopper V4 - One-Time Approval Tokens (Sprint 5).
Tokens are cryptographically bound to the proposal hash.
Consumption is atomic with approval to prevent race conditions.
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

def validate_and_consume_token(token: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Atomically validates and consumes the token in a single transaction.
    Returns (trade_id, proposal_hash) if valid, else (None, None).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Start transaction
    cursor.execute("BEGIN TRANSACTION")
    
    # 1. Select token with FOR UPDATE (locking) to prevent race conditions
    cursor.execute("""
        SELECT id, trade_id, proposal_hash, expires_at, used_at
        FROM approval_tokens
        WHERE token = ?
    """, (token,))
    row = cursor.fetchone()
    
    if not row:
        conn.rollback()
        conn.close()
        return None, None
    
    token_id, trade_id, proposal_hash, expires_at_str, used_at = row
    expires_at = datetime.fromisoformat(expires_at_str)
    
    # 2. Validate
    if datetime.utcnow() > expires_at:
        conn.rollback()
        conn.close()
        return None, None
    if used_at is not None:
        conn.rollback()
        conn.close()
        return None, None
    
    # 3. Mark as used (atomic update)
    cursor.execute("""
        UPDATE approval_tokens
        SET used_at = ?
        WHERE id = ? AND used_at IS NULL
    """, (datetime.utcnow().isoformat(), token_id))
    
    if cursor.rowcount == 0:
        conn.rollback()
        conn.close()
        return None, None
    
    # 4. Commit the consumption
    conn.commit()
    conn.close()
    
    return trade_id, proposal_hash