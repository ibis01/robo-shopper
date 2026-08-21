#!/usr/bin/env python3
"""
Robo-Shopper V4 - Institutional Desk Dashboard (Secured).
"""
import os
import sqlite3
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import DB_PATH
from schemas import TradeStatus

app = FastAPI(title="Robo-Shopper Institutional Desk")

# Simple local operator authorization
DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "robo-shopper-local-dev")

# SECURITY FIX 2: Restrict CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8003"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_dashboard_auth(request: Request):
    """Verify auth via HttpOnly cookie."""
    if request.cookies.get("robo_auth") != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request):
    response = HTMLResponse(content="""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Robo-Shopper Institutional Desk</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f4f5f7; color: #172b4d; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .trade-card { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin: 15px 0; }
            .metric { background: #f4f5f7; padding: 10px; border-radius: 4px; }
            .metric-label { font-size: 0.8em; color: #5e6c84; }
            .metric-value { font-weight: bold; word-break: break-all; }
            button { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; margin-right: 10px; }
            .btn-approve { background: #36b37e; color: white; }
            .btn-reject { background: #ff5630; color: white; }
        </style>
    </head>
    <body>
    <div class="container">
        <h1>Robo-Shopper Institutional Desk</h1>
        <div id="pending-trades">Loading...</div>
    </div>
    <script>
        // SECURITY FIX 1: No hardcoded API key. Uses HttpOnly cookies via credentials: 'include'
        async function loadTrades() {
            const res = await fetch('/api/pending_trades', { credentials: 'include' });
            if (res.status === 401) { document.getElementById('pending-trades').innerHTML = 'Unauthorized'; return; }
            const data = await res.json();
            const container = document.getElementById('pending-trades');
            if (data.trades.length === 0) { container.innerHTML = 'No trades awaiting approval.'; return; }
            
            container.innerHTML = data.trades.map(t => {
                const card = document.createElement('div');
                card.className = 'trade-card';
                
                const header = document.createElement('div');
                header.innerHTML = `<h3>Trade #${t.id}: ${t.symbol} ${t.side.toUpperCase()}</h3>`;
                card.appendChild(header);

                const metrics = document.createElement('div');
                metrics.className = 'metrics';
                metrics.innerHTML = `
                    <div class="metric"><div class="metric-label">Qty</div><div class="metric-value">${t.quantity}</div></div>
                    <div class="metric"><div class="metric-label">Entry</div><div class="metric-value">$${t.entry_price}</div></div>
                    <div class="metric"><div class="metric-label">Stop</div><div class="metric-value">$${t.stop_loss}</div></div>
                    <div class="metric"><div class="metric-label">Risk %</div><div class="metric-value">${(t.risk_percent * 100).toFixed(2)}%</div></div>
                    <div class="metric"><div class="metric-label">Hash</div><div class="metric-value">${t.proposal_hash || 'N/A'}</div></div>
                `;
                card.appendChild(metrics);

                // SECURITY FIX 4: Safe rendering of reasoning (prevents XSS)
                if (t.reasoning) {
                    const reasonDiv = document.createElement('div');
                    reasonDiv.className = 'metric';
                    const label = document.createElement('div');
                    label.className = 'metric-label';
                    label.textContent = 'Agent Reasoning';
                    const val = document.createElement('div');
                    val.className = 'metric-value';
                    val.style.fontWeight = 'normal';
                    val.textContent = t.reasoning; // Safe assignment
                    reasonDiv.appendChild(label);
                    reasonDiv.appendChild(val);
                    card.appendChild(reasonDiv);
                }

                const actions = document.createElement('div');
                actions.innerHTML = `
                    <button class="btn-approve" onclick="approveTrade(${t.id})">Approve</button>
                    <button class="btn-reject" onclick="rejectTrade(${t.id})">Reject</button>
                `;
                card.appendChild(actions);
                return card.outerHTML;
            }).join('');
        }
        async function approveTrade(id) {
            const res = await fetch(`/api/approve/${id}`, { method: 'POST', credentials: 'include' });
            const data = await res.json();
            alert(data.status === 'success' ? 'Approved!' : 'Error: ' + data.reason);
            loadTrades();
        }
        async function rejectTrade(id) {
            const res = await fetch(`/api/reject/${id}`, { method: 'POST', credentials: 'include' });
            const data = await res.json();
            alert(data.status === 'success' ? 'Rejected.' : 'Error: ' + data.reason);
            loadTrades();
        }
        loadTrades();
        setInterval(loadTrades, 3000);
    </script>
    </body>
    </html>
    """)
    # SECURITY FIX 1: Set HttpOnly cookie instead of exposing key to JS
    response.set_cookie(key="robo_auth", value=DASHBOARD_API_KEY, httponly=True, samesite="strict")
    return response

@app.get("/api/pending_trades")
def get_pending_trades(request: Request):
    verify_dashboard_auth(request)
    ALLOWED_FIELDS = ["id", "symbol", "side", "entry_price", "stop_loss", "quantity", "risk_percent", "reasoning", "proposal_hash"]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE status = 'awaiting_approval' ORDER BY id DESC")
    trades = [{k: v for k, v in dict(row).items() if k in ALLOWED_FIELDS} for row in cursor.fetchall()]
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

# SECURITY FIX 3: Protect trace endpoint
@app.get("/api/trace/{trade_id}")
def get_trade_trace(trade_id: int, request: Request):
    verify_dashboard_auth(request)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
    trade = dict(cursor.fetchone() or {})
    conn.close()
    if not trade: raise HTTPException(status_code=404, detail="Trade not found")
    return {"status": "success", "dossier": trade}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)