"""
Robo-Shopper V4 - One-Time Approval Tokens (Sprint 5).
Prevents replay, expiry, and unauthorized approval.
"""
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from config import DB_PATH

def create_approval_token(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Create a one‑time token that expires in 1 hour."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=1)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO approval_tokens (token, trade_id, requested_by, expires_at)
        VALUES (?, ?, ?, ?)
    """, (token, trade_id, requested_by, expires_at.isoformat()))
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "approval_token": token,
        "trade_id": trade_id,
        "expires_at": expires_at.isoformat()
    }

def validate_approval_token(token: str) -> Optional[Dict[str, Any]]:
    """Returns trade_id if valid, else None (expired/used/invalid)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT trade_id, expires_at, used_at FROM approval_tokens WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    trade_id, expires_at_str, used_at = row
    expires_at = datetime.fromisoformat(expires_at_str)
    
    if datetime.utcnow() > expires_at:
        return None
    if used_at:
        return None
    
    return {"trade_id": trade_id}

def mark_token_used(token: str) -> bool:
    """Marks a token as used to prevent replay."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE approval_tokens
        SET used_at = ?
        WHERE token = ? AND used_at IS NULL
    """, (datetime.utcnow().isoformat(), token))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected == 1