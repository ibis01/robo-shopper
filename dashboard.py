#!/usr/bin/env python3
"""
Robo-Shopper V4 - Institutional Desk Dashboard.
Professional UI for human authorization and audit trails.
"""
import os
import sqlite3
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import DB_PATH
from schemas import TradeStatus

app = FastAPI(title="Robo-Shopper Institutional Desk")

# Simple local operator authorization for hackathon
DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "robo-shopper-local-dev")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_dashboard_auth(request: Request):
    """Simple API key verification for dashboard endpoints."""
    auth_header = request.headers.get("X-API-Key", "")
    if auth_header != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- INSTITUTIONAL DESK UI ---
@app.get("/", response_class=HTMLResponse)
def dashboard_home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Robo-Shopper Institutional Desk</title>
        <style>
            :root { --bg: #f4f5f7; --card: #ffffff; --text: #172b4d; --muted: #5e6c84; --primary: #0052cc; --success: #36b37e; --danger: #ff5630; --border: #dfe1e6; }
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            header { border-bottom: 2px solid var(--primary); padding-bottom: 15px; margin-bottom: 30px; }
            h1 { margin: 0; font-size: 1.8em; }
            .subtitle { color: var(--muted); font-size: 0.9em; margin-top: 5px; }
            .trade-card { background: var(--card); border-radius: 8px; padding: 25px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid var(--border); }
            .trade-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 20px; }
            .trade-id { font-size: 1.3em; font-weight: bold; color: var(--primary); }
            .status-badge { padding: 6px 12px; border-radius: 12px; font-size: 0.8em; font-weight: bold; background: #ff991f; color: white; text-transform: uppercase; }
            .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 20px; }
            .metric { background: var(--bg); padding: 12px; border-radius: 6px; }
            .metric-label { font-size: 0.8em; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
            .metric-value { font-size: 1.1em; font-weight: bold; margin-top: 4px; word-break: break-all; }
            .actions { display: flex; gap: 15px; margin-top: 25px; }
            button { padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 1em; transition: opacity 0.2s; }
            button:hover { opacity: 0.9; }
            .btn-approve { background: var(--success); color: white; flex: 1; }
            .btn-reject { background: var(--danger); color: white; flex: 1; }
            .empty-state { text-align: center; color: var(--muted); padding: 40px; font-size: 1.1em; }
        </style>
    </head>
    <body>
    <div class="container">
        <header>
            <h1>Robo-Shopper Institutional Desk</h1>
            <div class="subtitle">AI recommends. The system verifies. The human authorizes.</div>
        </header>
        <div id="pending-trades"><div class="empty-state">Loading pending approvals...</div></div>
    </div>
    <script>
        const API_KEY = "robo-shopper-local-dev";
        const headers = { "X-API-Key": API_KEY, "Content-Type": "application/json" };

        async function loadTrades() {
            const res = await fetch('/api/pending_trades', { headers });
            if (res.status === 401) { document.getElementById('pending-trades').innerHTML = '<div class="empty-state">Unauthorized. Check API Key.</div>'; return; }
            const data = await res.json();
            const container = document.getElementById('pending-trades');
            if (data.trades.length === 0) {
                container.innerHTML = '<div class="empty-state">No trades awaiting approval.</div>';
                return;
            }
            container.innerHTML = data.trades.map(t => `
                <div class="trade-card">
                    <div class="trade-header">
                        <span class="trade-id">Trade #${t.id}: ${t.symbol} ${t.side.toUpperCase()}</span>
                        <span class="status-badge">Awaiting Approval</span>
                    </div>
                    <div class="metrics-grid">
                        <div class="metric"><div class="metric-label">Quantity</div><div class="metric-value">${t.quantity}</div></div>
                        <div class="metric"><div class="metric-label">Entry Price</div><div class="metric-value">$${t.entry_price}</div></div>
                        <div class="metric"><div class="metric-label">Stop Loss</div><div class="metric-value">$${t.stop_loss}</div></div>
                        <div class="metric"><div class="metric-label">Risk %</div><div class="metric-value">${(t.risk_percent * 100).toFixed(2)}%</div></div>
                        <div class="metric"><div class="metric-label">Risk Amount</div><div class="metric-value">$${t.risk_amount.toFixed(2)}</div></div>
                        <div class="metric"><div class="metric-label">Portfolio Balance</div><div class="metric-value">$${t.portfolio_balance.toFixed(2)}</div></div>
                    </div>
                    <div class="metrics-grid">
                        <div class="metric"><div class="metric-label">Proposal Hash</div><div class="metric-value">${t.proposal_hash || 'N/A'}</div></div>
                        <div class="metric"><div class="metric-label">Policy Version</div><div class="metric-value">${t.policy_version || 'N/A'}</div></div>
                        <div class="metric"><div class="metric-label">Expires At</div><div class="metric-value">${t.proposal_expires_at ? new Date(t.proposal_expires_at).toLocaleString() : 'N/A'}</div></div>
                    </div>
                    ${t.reasoning ? `<div class="metric" style="margin-bottom:20px"><div class="metric-label">Agent Reasoning</div><div class="metric-value" style="font-weight:normal; font-size:0.95em">${t.reasoning}</div></div>` : ''}
                    <div class="actions">
                        <button class="btn-approve" onclick="approveTrade(${t.id})">Cryptographically Approve</button>
                        <button class="btn-reject" onclick="rejectTrade(${t.id})">Reject Trade</button>
                    </div>
                </div>
            `).join('');
        }
        async function approveTrade(id) {
            if(!confirm('Cryptographically approve Trade #' + id + '?')) return;
            const res = await fetch(`/api/approve/${id}`, { method: 'POST', headers });
            const data = await res.json();
            alert(data.status === 'success' ? '✅ Trade Approved Successfully!' : '❌ Error: ' + data.reason);
            loadTrades();
        }
        async function rejectTrade(id) {
            if(!confirm('Reject Trade #' + id + '?')) return;
            const res = await fetch(`/api/reject/${id}`, { method: 'POST', headers });
            const data = await res.json();
            alert(data.status === 'success' ? '✅ Trade Rejected.' : '❌ Error: ' + data.reason);
            loadTrades();
        }
        loadTrades();
        setInterval(loadTrades, 3000);
    </script>
    </body>
    </html>
    """

@app.get("/api/pending_trades")
def get_pending_trades(request: Request):
    verify_dashboard_auth(request)
    
    # Allowlisted fields only
    ALLOWED_FIELDS = [
        "id", "symbol", "side", "entry_price", "stop_loss", "take_profit",
        "quantity", "risk_percent", "risk_amount", "portfolio_balance",
        "reasoning", "proposal_hash", "policy_version", "proposal_expires_at",
        "created_at"
    ]
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE status = 'awaiting_approval' ORDER BY id DESC")
    
    trades = []
    for row in cursor.fetchall():
        trade_dict = dict(row)
        filtered_trade = {k: v for k, v in trade_dict.items() if k in ALLOWED_FIELDS}
        trades.append(filtered_trade)
    
    conn.close()
    return {"trades": trades}

@app.post("/api/approve/{trade_id}")
def api_approve_trade(trade_id: int, request: Request):
    verify_dashboard_auth(request)
    from governance_engine import dashboard_approve_trade
    result = dashboard_approve_trade(trade_id)
    if result.get("status") == "SUCCESS":
        return {"status": "success", "message": "Trade approved."}
    return {"status": "error", "reason": result.get("reason", "Unknown error")}

@app.post("/api/reject/{trade_id}")
def api_reject_trade(trade_id: int, request: Request):
    verify_dashboard_auth(request)
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