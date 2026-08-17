"""
Robo-Shopper V4 - Trade Memory MCP (Sprint 5).
Manages the SQLite ledger. 
State mutations are delegated to state_machine.py.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from config import DB_PATH
from schemas import TradeStatus
from state_machine import transition_trade, ActorType

# ------------------------------------------------------------------
# PROPOSE A TRADE
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
    """Logs a new trade proposal with status = PROPOSED, storing risk and expiration."""
    if not symbol or not side or quantity <= 0 or entry_price <= 0 or stop_loss <= 0:
        raise ValueError("Invalid trade parameters.")
    
    # Compute risk metrics
    risk_per_unit = abs(entry_price - stop_loss)
    risk_amount = risk_per_unit * quantity
    risk_percent = risk_amount / portfolio_balance if portfolio_balance and portfolio_balance > 0 else 0.02
    
    # Expiration (24h from now) – use timezone-aware UTC
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO trades (
            symbol, side, quantity, entry_price, stop_loss, take_profit, 
            reasoning, portfolio_balance, risk_percent, risk_amount, proposal_expires_at,
            status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, side, quantity, entry_price, stop_loss, take_profit,
        reasoning, portfolio_balance, risk_percent, risk_amount, expires_at,
        TradeStatus.PROPOSED.value, datetime.now(timezone.utc).isoformat()
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
# DEPRECATED: record_execution
# ------------------------------------------------------------------
def record_execution(trade_id: int, execution_price: float, feedback: Optional[str] = None):
    """Deprecated: Use execute_trade() from governance_engine instead."""
    result = transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.EXECUTION_GATEWAY,
        {"execution_price": execution_price, "feedback": feedback},
        require_approval_hash="legacy"
    )
    return result