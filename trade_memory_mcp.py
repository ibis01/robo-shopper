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
    
    # Create table if not exists
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
            executed_at TIMESTAMP,
            closed_at TIMESTAMP,
            pnl REAL,
            feedback TEXT
        )
    """)
    
    # Insert the proposal
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
# 2. RECORD EXECUTION (WITH HARD STATE ENFORCEMENT)
# ------------------------------------------------------------------
def record_execution(trade_id: int, execution_price: float, feedback: Optional[str] = None) -> Dict[str, Any]:
    """
    Records the execution of a trade.
    🔒 HARD STOP: Trade MUST be in APPROVED status. Cannot execute otherwise.
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
    
    # 3. Update to EXECUTED
    cursor.execute("""
        UPDATE trades 
        SET status = ?, executed_at = ?, feedback = ?
        WHERE id = ?
    """, (TradeStatus.EXECUTED.value, datetime.utcnow().isoformat(), feedback, trade_id))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "message": f"Trade {trade_id} executed at ${execution_price:.2f}.",
        "new_status": TradeStatus.EXECUTED.value
    }

# ------------------------------------------------------------------
# 3. APPROVE A TRADE (State: AWAITING_APPROVAL → APPROVED)
# ------------------------------------------------------------------
def approve_trade(trade_id: int) -> Dict[str, Any]:
    """Moves a trade from AWAITING_APPROVAL to APPROVED."""
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
        SET status = ?, approved_at = ?
        WHERE id = ?
    """, (TradeStatus.APPROVED.value, datetime.utcnow().isoformat(), trade_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "trade_id": trade_id, "new_status": TradeStatus.APPROVED.value}