#!/usr/bin/env python3
"""
Robo-Shopper V4 - Trade Memory MCP (Sprint 5).
Manages the SQLite ledger with strict state enforcement.
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

from config import DB_PATH
from schemas import TradeStatus, TradeProposal

# ------------------------------------------------------------------
# 0. DATABASE MIGRATION (Ensures columns exist)
# ------------------------------------------------------------------
def _ensure_schema():
    """Idempotently adds new columns if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create base table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL,
            reasoning TEXT,
            portfolio_balance REAL,
            status TEXT,
            created_at TIMESTAMP,
            risk_checked_at TIMESTAMP,
            approved_at TIMESTAMP,
            approved_by TEXT,
            executed_at TIMESTAMP,
            execution_price REAL,
            closed_at TIMESTAMP,
            pnl REAL,
            feedback TEXT
        )
    """)
    
    # Check existing columns and add missing ones
    cursor.execute("PRAGMA table_info(trades)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    
    new_columns = [
        ("execution_price", "REAL"),
        ("approved_by", "TEXT"),
    ]
    
    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
    
    conn.commit()
    conn.close()

# Run migration on import
_ensure_schema()

# ------------------------------------------------------------------
# 1. PROPOSE A TRADE
# ------------------------------------------------------------------
def propose_trade(
    symbol: str,
    side: str,
    quantity: float,
    entry_price: float,
    stop_loss: float,
    take_profit: Optional[float] = None,
    reasoning: Optional[str] = None,
    portfolio_balance: Optional[float] = None
) -> Dict[str, Any]:
    """
    Logs a new trade proposal with status = PROPOSED.
    """
    if not symbol or not side or quantity <= 0 or entry_price <= 0 or stop_loss <= 0:
        raise ValueError("Invalid trade parameters. All values must be positive.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO trades (
            symbol, side, quantity, entry_price, stop_loss, take_profit, 
            reasoning, portfolio_balance, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, side, quantity, entry_price, stop_loss, take_profit,
        reasoning, portfolio_balance, TradeStatus.PROPOSED.value, datetime.utcnow().isoformat()
    ))
    
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "message": f"Trade {trade_id} proposed for {symbol} {side}.",
        "current_status": TradeStatus.PROPOSED.value
    }

# ------------------------------------------------------------------
# 2. GET A TRADE BY ID (for screen_trade)
# ------------------------------------------------------------------
def get_trade(trade_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a single trade by ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))

# ------------------------------------------------------------------
# 3. UPDATE RISK CHECK STATUS (Called by screen_trade)
# ------------------------------------------------------------------
def set_risk_checked(trade_id: int) -> Dict[str, Any]:
    """Moves a trade from PROPOSED to RISK_CHECKED."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Trade {trade_id} not found.")
    
    if row[0] != TradeStatus.PROPOSED.value:
        conn.close()
        raise ValueError(f"Trade {trade_id} is '{row[0]}', must be '{TradeStatus.PROPOSED.value}' to run risk checks.")
    
    cursor.execute("""
        UPDATE trades 
        SET status = ?, risk_checked_at = ?
        WHERE id = ?
    """, (TradeStatus.RISK_CHECKED.value, datetime.utcnow().isoformat(), trade_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "trade_id": trade_id, "new_status": TradeStatus.RISK_CHECKED.value}

# ------------------------------------------------------------------
# 4. SET AWAITING APPROVAL (Called by screen_trade after risk passes)
# ------------------------------------------------------------------
def set_awaiting_approval(trade_id: int) -> Dict[str, Any]:
    """Moves a trade from RISK_CHECKED to AWAITING_APPROVAL."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Trade {trade_id} not found.")
    
    if row[0] != TradeStatus.RISK_CHECKED.value:
        conn.close()
        raise ValueError(f"Trade {trade_id} is '{row[0]}', must be '{TradeStatus.RISK_CHECKED.value}' to request approval.")
    
    cursor.execute("""
        UPDATE trades 
        SET status = ?
        WHERE id = ?
    """, (TradeStatus.AWAITING_APPROVAL.value, trade_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "trade_id": trade_id, "new_status": TradeStatus.AWAITING_APPROVAL.value}

# ------------------------------------------------------------------
# 5. APPROVE A TRADE (with actor tracking)
# ------------------------------------------------------------------
def approve_trade(trade_id: int, approved_by: str = "human") -> Dict[str, Any]:
    """
    Moves a trade from AWAITING_APPROVAL to APPROVED.
    Tracks who approved it (human, system, etc.).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Trade {trade_id} not found.")
    
    if row[0] != TradeStatus.AWAITING_APPROVAL.value:
        conn.close()
        raise ValueError(f"Trade {trade_id} is '{row[0]}', must be '{TradeStatus.AWAITING_APPROVAL.value}' to approve.")
    
    cursor.execute("""
        UPDATE trades 
        SET status = ?, approved_at = ?, approved_by = ?
        WHERE id = ?
    """, (TradeStatus.APPROVED.value, datetime.utcnow().isoformat(), approved_by, trade_id))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "new_status": TradeStatus.APPROVED.value,
        "approved_by": approved_by
    }

# ------------------------------------------------------------------
# 6. RECORD EXECUTION (WITH HARD STATE ENFORCEMENT + PRICE STORAGE)
# ------------------------------------------------------------------
def record_execution(
    trade_id: int, 
    execution_price: float, 
    feedback: Optional[str] = None,
    executed_by: str = "human"
) -> Dict[str, Any]:
    """
    Records the execution of a trade.
    🔒 HARD STOP: Trade MUST be in APPROVED status.
    Stores the actual execution price for P&L accuracy.
    """
    if not trade_id or trade_id <= 0:
        raise ValueError("Invalid trade_id.")
    if execution_price <= 0:
        raise ValueError("Execution price must be positive.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Fetch the current trade
    cursor.execute("SELECT status, entry_price, stop_loss, quantity FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Trade ID {trade_id} not found.")
    
    current_status, entry, stop, qty = row
    
    # 2. 🔥 ENFORCE STATE MACHINE: Only APPROVED can be executed
    if current_status != TradeStatus.APPROVED.value:
        conn.close()
        raise ValueError(
            f"ILLEGAL STATE TRANSITION: Trade {trade_id} is '{current_status}', "
            f"but must be '{TradeStatus.APPROVED.value}' to execute."
        )
    
    # 3. Update to EXECUTED, store execution price
    cursor.execute("""
        UPDATE trades 
        SET status = ?, executed_at = ?, execution_price = ?, feedback = ?
        WHERE id = ?
    """, (TradeStatus.EXECUTED.value, datetime.utcnow().isoformat(), execution_price, feedback, trade_id))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "message": f"Trade {trade_id} executed at ${execution_price:.2f}.",
        "new_status": TradeStatus.EXECUTED.value,
        "execution_price": execution_price,
        "executed_by": executed_by
    }

# ------------------------------------------------------------------
# 7. GET TRADE HISTORY (unchanged, but uses unified DB)
# ------------------------------------------------------------------
def get_trade_history(limit: int = 10) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, symbol, side, quantity, entry_price, stop_loss, status, pnl, created_at, executed_at
        FROM trades 
        ORDER BY id DESC 
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    trades = []
    for row in rows:
        trades.append({
            "id": row[0],
            "symbol": row[1],
            "side": row[2],
            "quantity": row[3],
            "entry": row[4],
            "stop": row[5],
            "status": row[6],
            "pnl": row[7],
            "created": row[8],
            "executed": row[9]
        })
    
    return {"trades": trades, "count": len(trades)}