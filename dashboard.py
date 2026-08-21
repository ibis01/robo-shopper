#!/usr/bin/env python3
"""
Robo-Shopper V4 - Institutional Desk Dashboard.
Provides a professional UI for human authorization and audit trails.
"""
import sqlite3
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

from config import DB_PATH
from schemas import TradeStatus  
from governance_engine import dashboard_approve_trade, dashboard_reject_trade


app = FastAPI(title="Robo-Shopper Institutional Desk")

# Ensure tables exist (simplified for dashboard context)
def _ensure_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, side TEXT NOT NULL,
            entry_price REAL NOT NULL, stop_loss REAL NOT NULL,
            take_profit REAL, quantity REAL NOT NULL,
            portfolio_balance REAL DEFAULT 10000.0,
            risk_percent REAL, risk_amount REAL,
            pnl REAL, status TEXT DEFAULT 'proposed',
            reasoning TEXT, proposal_hash TEXT, policy_version TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            executed_at TEXT, closed_at TEXT, execution_price REAL,
            proposal_expires_at TEXT
        )
    """)
    conn.commit()
    conn.close()

_ensure_tables()

# --- INSTITUTIONAL DESK UI ---
@app.get("/", response_class=HTMLResponse)
def dashboard_home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Robo-Shopper Institutional Desk</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f5f7; color: #172b4d; margin: 0; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            h1 { border-bottom: 2px solid #0052cc; padding-bottom: 10px; }
            .trade-card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .trade-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #dfe1e6; padding-bottom: 10px; margin-bottom: 15px; }
            .trade-id { font-size: 1.2em; font-weight: bold; color: #0052cc; }
            .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 15px; }
            .metric { background: #f4f5f7; padding: 10px; border-radius: 4px; }
            .metric-label { font-size: 0.85em; color: #5e6c84; }
            .metric-value { font-size: 1.1em; font-weight: bold; }
            .actions { display: flex; gap: 10px; margin-top: 15px; }
            button { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 1em; }
            .btn-approve { background: #36b37e; color: white; }
            .btn-approve:hover { background: #2d9669; }
            .btn-reject { background: #ff5630; color: white; }
            .btn-reject:hover { background: #de350b; }
            .status-badge { padding: 5px 10px; border-radius: 12px; font-size: 0.85em; font-weight: bold; background: #ff991f; color: white; }
        </style>
    </head>
    <body>
    <div class="container">
        <h1>Robo-Shopper Institutional Desk</h1>
        <div id="pending-trades">Loading pending approvals...</div>
    </div>
    <script>
        async function loadTrades() {
            const res = await fetch('/api/pending_trades');
            const data = await res.json();
            const container = document.getElementById('pending-trades');
            if (data.trades.length === 0) {
                container.innerHTML = '<p style="color:#5e6c84;">No trades awaiting approval.</p>';
                return;
            }
            container.innerHTML = data.trades.map(t => `
                <div class="trade-card">
                    <div class="trade-header">
                        <span class="trade-id">Trade #${t.id}: ${t.symbol} ${t.side.toUpperCase()}</span>
                        <span class="status-badge">AWAITING APPROVAL</span>
                    </div>
                    <div class="metrics">
                        <div class="metric"><div class="metric-label">Quantity</div><div class="metric-value">${t.quantity}</div></div>
                        <div class="metric"><div class="metric-label">Entry Price</div><div class="metric-value">$${t.entry_price}</div></div>
                        <div class="metric"><div class="metric-label">Stop Loss</div><div class="metric-value">$${t.stop_loss}</div></div>
                        <div class="metric"><div class="metric-label">Risk %</div><div class="metric-value">${(t.risk_percent * 100).toFixed(2)}%</div></div>
                        <div class="metric"><div class="metric-label">Risk Amount</div><div class="metric-value">$${t.risk_amount.toFixed(2)}</div></div>
                        <div class="metric"><div class="metric-label">Portfolio Balance</div><div class="metric-value">$${t.portfolio_balance.toFixed(2)}</div></div>
                    </div>
                    <div class="metrics">
                        <div class="metric"><div class="metric-label">Proposal Hash</div><div class="metric-value" style="font-size:0.8em; word-break:break-all;">${t.proposal_hash || 'N/A'}</div></div>
                        <div class="metric"><div class="metric-label">Expires At</div><div class="metric-value">${t.proposal_expires_at ? new Date(t.proposal_expires_at).toLocaleString() : 'N/A'}</div></div>
                    </div>
                    <div class="actions">
                        <button class="btn-approve" onclick="approveTrade(${t.id})">Cryptographically Approve</button>
                        <button class="btn-reject" onclick="rejectTrade(${t.id})">Reject Trade</button>
                    </div>
                </div>
            `).join('');
        }
        async function approveTrade(id) {
            if(!confirm('Cryptographically approve Trade #' + id + '?')) return;
            const res = await fetch(`/api/approve/${id}`, {method: 'POST'});
            const data = await res.json();
            alert(data.status === 'success' ? 'Trade Approved Successfully!' : 'Error: ' + data.reason);
            loadTrades();
        }
        async function rejectTrade(id) {
            if(!confirm('Reject Trade #' + id + '?')) return;
            const res = await fetch(`/api/reject/${id}`, {method: 'POST'});
            const data = await res.json();
            alert(data.status === 'success' ? 'Trade Rejected.' : 'Error: ' + data.reason);
            loadTrades();
        }
        loadTrades();
        setInterval(loadTrades, 3000); // Auto-refresh every 3s
    </script>
    </body>
    </html>
    """

@app.get("/api/pending_trades")
def get_pending_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE status = 'awaiting_approval' ORDER BY id DESC")
    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"trades": trades}

@app.post("/api/approve/{trade_id}")
def api_approve_trade(trade_id: int):
    from governance_engine import dashboard_approve_trade
    result = dashboard_approve_trade(trade_id)
    if result.get("status") == "SUCCESS":
        return {"status": "success", "message": "Trade approved."}
    return {"status": "error", "reason": result.get("reason", "Unknown error")}

@app.post("/api/reject/{trade_id}")
def api_reject_trade(trade_id: int):
    from governance_engine import dashboard_reject_trade
    result = dashboard_reject_trade(trade_id)
    if result.get("status") == "SUCCESS":
        return {"status": "success", "message": "Trade rejected."}
    return {"status": "error", "reason": result.get("reason", "Unknown error")}

@app.get("/api/trace/{trade_id}")
def get_trade_trace(trade_id: int):
    """Exposes the canonical Decision Dossier for a specific trade."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    trade = dict(cursor.fetchone() or {})
    conn.close()
    
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
        
    return {
        "status": "success",
        "dossier": {
            "trade_id": trade["id"],
            "status": trade["status"],
            "asset": trade["symbol"],
            "side": trade["side"],
            "entry_price": trade["entry_price"],
            "stop_loss": trade["stop_loss"],
            "quantity": trade["quantity"],
            "risk_percent": trade["risk_percent"],
            "risk_amount": trade["risk_amount"],
            "portfolio_balance": trade["portfolio_balance"],
            "agent_reasoning": trade.get("reasoning", ""),
            "governance": {
                "proposal_hash": trade.get("proposal_hash"),
                "policy_version": trade.get("policy_version"),
            },
            "audit_trail": {
                "created_at": trade.get("created_at"),
                "updated_at": trade.get("updated_at"),
            }
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)