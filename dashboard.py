"""
Robo-Shopper V4 - Read-only dashboard with local operator authentication.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from typing import Dict, Any

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "trades.db")
OPERATOR_PASSWORD = os.getenv("OPERATOR_PASSWORD", "operator123")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev_secret_rotate_me")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# ------------------------------------------------------------------
# DATABASE HELPERS
# ------------------------------------------------------------------
def _get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ------------------------------------------------------------------
# AUTHENTICATION DEPENDENCY
# ------------------------------------------------------------------
def get_current_operator(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# ------------------------------------------------------------------
# LOGIN / LOGOUT
# ------------------------------------------------------------------
@app.post("/api/login")
async def login(request: Request, username: str = None, password: str = None):
    # Support both form data and JSON
    if request.headers.get("content-type") == "application/json":
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
    else:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
    
    if password == OPERATOR_PASSWORD:
        request.session["authenticated"] = True
        return {"status": "success", "message": "Logged in"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"status": "success", "message": "Logged out"}

# ------------------------------------------------------------------
# API ENDPOINTS (Protected)
# ------------------------------------------------------------------
@app.get("/api/pending_trades", dependencies=[Depends(get_current_operator)])
async def pending_trades():
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, symbol, side, quantity, entry_price, stop_loss, created_at FROM trades WHERE status = 'awaiting_approval'"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/approve/{trade_id}", dependencies=[Depends(get_current_operator)])
async def api_approve(trade_id: int):
    from governance_engine import dashboard_approve_trade
    result = dashboard_approve_trade(trade_id)
    return result

@app.post("/api/reject/{trade_id}", dependencies=[Depends(get_current_operator)])
async def api_reject(trade_id: int):
    from governance_engine import dashboard_reject_trade
    result = dashboard_reject_trade(trade_id)
    return result

@app.get("/api/trace/{trade_id}", dependencies=[Depends(get_current_operator)])
async def api_trace(trade_id: int):
    conn = _get_db()
    trade = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return dict(trade)

@app.get("/api/summary", dependencies=[Depends(get_current_operator)])
async def summary():
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) FROM trades WHERE status='closed'").fetchone()[0]
    wins = conn.execute("SELECT COUNT(*) FROM trades WHERE status='closed' AND pnl > 0").fetchone()[0]
    pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='closed'").fetchone()[0]
    conn.close()
    return {
        "total_closed": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "lifetime_pnl": round(pnl, 2)
    }

# ------------------------------------------------------------------
# LOGIN PAGE (HTML)
# ------------------------------------------------------------------
LOGIN_PAGE = """
<!doctype html>
<html>
<head>
    <title>Robo-Shopper — Login</title>
    <style>
        body { background: #0d1117; color: #e6edf3; font-family: monospace; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .box { background: #161b22; padding: 40px; border-radius: 12px; border: 1px solid #30363d; width: 320px; }
        h1 { color: #00c2ff; margin-top: 0; }
        input { width: 100%; padding: 10px; margin: 8px 0; border-radius: 6px; border: 1px solid #30363d; background: #0d1117; color: #e6edf3; }
        button { width: 100%; padding: 10px; background: #00c2ff; color: #0d1117; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }
        .error { color: #f85149; margin-top: 10px; display: none; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🤖 Robo-Shopper</h1>
        <p>Operator Login</p>
        <form id="loginForm">
            <input type="password" id="password" placeholder="Enter operator password" autofocus>
            <button type="submit">Login</button>
            <div id="error" class="error">Invalid password</div>
        </form>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const pwd = document.getElementById('password').value;
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: 'operator', password: pwd })
            });
            if (res.ok) {
                window.location.href = '/';
            } else {
                document.getElementById('error').style.display = 'block';
            }
        });
    </script>
</body>
</html>
"""

# ------------------------------------------------------------------
# DASHBOARD HOME (Protected)
# ------------------------------------------------------------------
@app.get("/", dependencies=[Depends(get_current_operator)])
async def dashboard_home():
    return HTMLResponse(DASHBOARD_PAGE)

@app.get("/login")
async def login_page():
    return HTMLResponse(LOGIN_PAGE)

# ------------------------------------------------------------------
# DASHBOARD HTML (Safe rendering with textContent)
# ------------------------------------------------------------------
DASHBOARD_PAGE = """
<!doctype html>
<html>
<head>
    <meta charset=utf-8>
    <meta name=viewport content="width=device-width,initial-scale=1">
    <title>Robo-Shopper V4</title>
    <style>
        body{background:#0d1117;color:#e6edf3;font-family:ui-monospace,monospace;margin:0;padding:24px}
        h1{color:#00c2ff}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
        .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
        .card b{display:block;font-size:22px;margin-top:6px}
        .green{color:#3fb950}.red{color:#f85149}.amber{color:#d29922}
        table{width:100%;border-collapse:collapse;margin-top:16px}
        td,th{padding:6px 8px;border-bottom:1px solid #30363d;text-align:left}
        .logout{float:right;color:#f85149;cursor:pointer;text-decoration:underline}
    </style>
</head>
<body>
    <h1>🤖 Robo-Shopper V4 <span class="logout" onclick="logout()">Logout</span></h1>
    <div class=grid id=cards></div>
    <h2>Pending Approvals</h2>
    <table><thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Action</th></tr></thead>
    <tbody id=pending></tbody></table>
    <h2>Recent Trades</h2>
    <table><thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Status</th><th>PnL</th></tr></thead>
    <tbody id=rows></tbody></table>
    <script>
        async function fetchWithAuth(url, opts={}) {
            const res = await fetch(url, opts);
            if (res.status === 401) { window.location.href = '/login'; return null; }
            return res;
        }

        async function logout() {
            await fetch('/api/logout', { method: 'POST' });
            window.location.href = '/login';
        }

        async function approve(id) {
            const res = await fetch('/api/approve/' + id, { method: 'POST' });
            if (res.ok) { tick(); } else { alert('Approval failed'); }
        }

        async function reject(id) {
            const res = await fetch('/api/reject/' + id, { method: 'POST' });
            if (res.ok) { tick(); } else { alert('Rejection failed'); }
        }

        function renderTable(rows, containerId) {
            const tbody = document.getElementById(containerId);
            tbody.innerHTML = '';
            rows.forEach(r => {
                const tr = document.createElement('tr');
                const fields = ['id','symbol','side','quantity','entry_price','stop_loss'];
                fields.forEach(f => {
                    const td = document.createElement('td');
                    td.textContent = r[f] ?? '';
                    tr.appendChild(td);
                });
                if (containerId === 'pending') {
                    const td = document.createElement('td');
                    const btnApprove = document.createElement('button');
                    btnApprove.textContent = '✅';
                    btnApprove.onclick = () => approve(r.id);
                    const btnReject = document.createElement('button');
                    btnReject.textContent = '❌';
                    btnReject.onclick = () => reject(r.id);
                    td.appendChild(btnApprove);
                    td.appendChild(btnReject);
                    tr.appendChild(td);
                }
                tbody.appendChild(tr);
            });
        }

        async function tick() {
            const res = await fetch('/api/pending_trades');
            if (!res.ok) return;
            const pending = await res.json();
            renderTable(pending, 'pending');

            const res2 = await fetch('/api/summary');
            if (!res2.ok) return;
            const d = await res2.json();
            const cards = [
                ['Win rate', d.win_rate+'%', ''],
                ['Lifetime PnL', '$'+d.lifetime_pnl, d.lifetime_pnl>=0?'green':'red'],
            ];
            document.getElementById('cards').innerHTML = cards.map(x =>
                '<div class=card>'+x[0]+'<b class="'+x[2]+'">'+x[1]+'</b></div>'
            ).join('');
        }
        tick();
        setInterval(tick, 5000);
    </script>
</body>
</html>
"""

# ------------------------------------------------------------------
# RUN
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)