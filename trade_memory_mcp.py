import os
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("robo_shopper.trade_memory")
logging.basicConfig(level=logging.INFO)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            proposed_amount REAL,
            proposed_price REAL,
            actual_entry_price REAL,
            exit_price REAL,
            status TEXT DEFAULT 'proposed',
            user_feedback TEXT,
            proposed_at TEXT NOT NULL,
            executed_at TEXT,
            closed_at TEXT,
            pnl REAL,
            hold_time_seconds REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def _propose_trade(symbol: str, side: str, amount: float, proposed_price: float) -> Dict[str, Any]:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO trades (symbol, side, proposed_amount, proposed_price, proposed_at) VALUES (?, ?, ?, ?, ?)",
        (symbol.upper(), side.lower(), amount, proposed_price, now)
    )
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "ok": True, 
        "tool": "propose_trade", 
        "trade_id": trade_id, 
        "status": "proposed", 
        "message": "Trade logged. Awaiting human approval and execution."
    }

def _record_execution(trade_id: int, actual_entry_price: float, user_feedback: str) -> Dict[str, Any]:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "UPDATE trades SET actual_entry_price = ?, user_feedback = ?, executed_at = ?, status = 'executed' WHERE id = ?",
        (actual_entry_price, user_feedback, now, trade_id)
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    
    if updated == 0:
        return {"ok": False, "tool": "record_execution", "error": f"Trade ID {trade_id} not found."}
        
    return {
        "ok": True, 
        "tool": "record_execution", 
        "trade_id": trade_id, 
        "status": "executed", 
        "message": "Execution, entry price, and feedback recorded."
    }

def _close_trade(trade_id: int, exit_price: float) -> Dict[str, Any]:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "tool": "close_trade", "error": f"Trade ID {trade_id} not found."}
        
    if row["status"] != "executed":
        conn.close()
        return {"ok": False, "tool": "close_trade", "error": f"Trade {trade_id} must be executed before closing."}
        
    entry = row["actual_entry_price"]
    side = row["side"]
    amount = row["proposed_amount"] or 1.0
    
    if side == "buy":
        pnl = (exit_price - entry) * amount
    else:
        pnl = (entry - exit_price) * amount
        
    executed_at = datetime.fromisoformat(row["executed_at"])
    closed_at = datetime.fromisoformat(now)
    hold_time = (closed_at - executed_at).total_seconds()
    
    conn.execute(
        "UPDATE trades SET exit_price = ?, closed_at = ?, status = 'closed', pnl = ?, hold_time_seconds = ? WHERE id = ?",
        (exit_price, now, pnl, hold_time, trade_id)
    )
    conn.commit()
    conn.close()
    
    return {
        "ok": True, 
        "tool": "close_trade", 
        "trade_id": trade_id, 
        "status": "closed", 
        "pnl": round(pnl, 4),
        "hold_time_seconds": round(hold_time, 2)
    }

def _get_trade_history(symbol: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    conn = get_db()
    
    total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    executed = conn.execute("SELECT COUNT(*) FROM trades WHERE status IN ('executed', 'closed')").fetchone()[0]
    wins = conn.execute("SELECT COUNT(*) FROM trades WHERE status='closed' AND pnl > 0").fetchone()[0]
    losses = conn.execute("SELECT COUNT(*) FROM trades WHERE status='closed' AND pnl <= 0").fetchone()[0]
    avg_hold = conn.execute("SELECT AVG(hold_time_seconds) FROM trades WHERE status='closed' AND hold_time_seconds IS NOT NULL").fetchone()[0]
    
    metrics = {
        "total_proposals": total,
        "executed_trades": executed,
        "wins": wins,
        "losses": losses,
        "win_loss_ratio": round(wins / losses, 2) if losses > 0 else float(wins),
        "average_hold_time_seconds": round(avg_hold, 2) if avg_hold else 0,
        "human_approval_rate": round(executed / total, 2) if total > 0 else 0
    }
    
    query = "SELECT * FROM trades"
    params = []
    if symbol:
        query += " WHERE symbol = ?"
        params.append(symbol.upper())
    query += " ORDER BY proposed_at DESC LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    recent_trades = [dict(row) for row in rows]
    
    return {
        "ok": True,
        "tool": "get_trade_history",
        "metrics": metrics,
        "recent_trades": recent_trades
    }

def register_trade_memory_tools(mcp: Any) -> None:
    @mcp.tool()
    def propose_trade(symbol: str, side: str, amount: float, proposed_price: float) -> Dict[str, Any]:
        """Log a proposed trade to the database before human approval."""
        return _propose_trade(symbol, side, amount, proposed_price)

    @mcp.tool()
    def record_execution(trade_id: int, actual_entry_price: float, user_feedback: str) -> Dict[str, Any]:
        """Record that the human approved and the trade was executed."""
        return _record_execution(trade_id, actual_entry_price, user_feedback)

    @mcp.tool()
    def close_trade(trade_id: int, exit_price: float) -> Dict[str, Any]:
        """Close an executed trade and calculate PnL and hold time."""
        return _close_trade(trade_id, exit_price)

    @mcp.tool()
    def get_trade_history(symbol: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Get past trade history, win/loss ratio, average hold time, and human approval rate."""
        return _get_trade_history(symbol, limit)

if __name__ == "__main__":
    import json
    print(json.dumps(_get_trade_history(), indent=2))
