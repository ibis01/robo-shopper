"""
Robo-Shopper V4 - Trade Memory MCP (Sprint 5).
Manages the SQLite ledger. 
State mutations are delegated to state_machine.py.
"""
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any

from config import DB_PATH
from schemas import TradeStatus
from state_machine import transition_trade, ActorType

# ------------------------------------------------------------------
# PROPOSE A TRADE (creates initial PROPOSED state)
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
    """Logs a new trade proposal with status = PROPOSED."""
    if not symbol or not side or quantity <= 0 or entry_price <= 0 or stop_loss <= 0:
        raise ValueError("Invalid trade parameters.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, side TEXT, quantity REAL,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            reasoning TEXT, portfolio_balance REAL,
            status TEXT, created_at TIMESTAMP
        )
    """)
    
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
        "message": f"Trade {trade_id} proposed.",
        "current_status": TradeStatus.PROPOSED.value
    }

# ------------------------------------------------------------------
# GET A TRADE
# ------------------------------------------------------------------
def get_trade(trade_id: int) -> Optional[Dict[str, Any]]:
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
# GET TRADE HISTORY
# ------------------------------------------------------------------
def get_trade_history(limit: int = 10) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, symbol, side, quantity, entry_price, stop_loss, status, pnl, created_at, executed_at
        FROM trades ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    trades = []
    for row in rows:
        trades.append({
            "id": row[0], "symbol": row[1], "side": row[2],
            "quantity": row[3], "entry": row[4], "stop": row[5],
            "status": row[6], "pnl": row[7], "created": row[8], "executed": row[9]
        })
    return {"trades": trades, "count": len(trades)}

# ------------------------------------------------------------------
# DEPRECATED: record_execution (kept for backward compatibility, but now uses state_machine)
# ------------------------------------------------------------------
def record_execution(trade_id: int, execution_price: float, feedback: Optional[str] = None):
    """Deprecated: Use execute_trade() from governance_engine instead."""
    # Redirect to the state machine
    result = transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.EXECUTION_GATEWAY,
        {"execution_price": execution_price, "feedback": feedback},
        require_approval_hash="legacy"  # This will fail if not properly approved
    )
    return result