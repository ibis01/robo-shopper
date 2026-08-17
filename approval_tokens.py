"""
Robo-Shopper V4 - One-Time Approval Tokens (Sprint 5).
Transaction‑aware token validation for atomic approval.
"""
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

from config import DB_PATH

def create_approval_token(
    trade_id: int, 
    proposal_hash: str, 
    policy_version: str,
    requested_by: str = "ai",
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """Create a one‑time token. If conn is provided, use it (no commit)."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    
    own_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        own_conn = True
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO approval_tokens 
        (token, trade_id, proposal_hash, policy_version, requested_by, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (token, trade_id, proposal_hash, policy_version, requested_by, expires_at.isoformat()))
    
    if own_conn:
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
    The caller must have begun a transaction (BEGIN EXCLUSIVE) to serialize
    token consumption and prevent race conditions.
    
    Returns (trade_id, proposal_hash, policy_version) if valid, else (None, None, None).
    """
    cursor = conn.cursor()
    
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
    # Normalize: if stored as naive, assume UTC (make aware for comparison)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    # Both sides now aware — safe to compare
    if datetime.now(timezone.utc) > expires_at:
        return None, None, None
    if used_at is not None:
        return None, None, None
    
    # Mark as used (atomic update within the same transaction)
    cursor.execute("""
        UPDATE approval_tokens
        SET used_at = ?
        WHERE id = ? AND used_at IS NULL
    """, (datetime.now(timezone.utc).isoformat(), token_id))
    
    if cursor.rowcount == 0:
        return None, None, None
    
    return trade_id, proposal_hash, policy_version