"""Robo-Shopper V4 - Read-only dashboard with Decision Dossier API."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import threading

# Import DB_PATH from config, with fallback
try:
    from config import DB_PATH
except ImportError:
    BASE = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE, "data", "trades.db")

# ------------------------------------------------------------------
# APP INITIALIZATION
# ------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Robo-Shopper Dashboard", version="4.0.0")

# Enable CORS for demo flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection pool with thread safety
_db_lock = threading.Lock()

def _get_db_connection():
    """Get a thread-safe database connection with WAL mode for better concurrency."""
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    con.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s for locks
    return con

def _env(key: str, default: str = "") -> str:
    """Read environment variable or .env file fallback."""
    try:
        env_path = os.path.join(BASE, ".env")
        if os.path.exists(env_path):
            for ln in open(env_path):
                if ln.startswith(key + "="):
                    return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.getenv(key, default)

def _ensure_tables():
    """Ensure required tables exist with proper schema."""
    try:
        os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
        con = _get_db_connection()
        cursor = con.cursor()
        
        # Create trades table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL,
                quantity REAL NOT NULL,
                proposed_amount REAL,
                proposed_price REAL,
                actual_entry_price REAL,
                actual_exit_price REAL,
                portfolio_balance REAL DEFAULT 10000.0,
                risk_percent REAL,
                risk_amount REAL,
                pnl REAL,
                status TEXT DEFAULT 'proposed',
                reasoning TEXT,
                proposal_hash TEXT,
                policy_version TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                executed_at TEXT,
                closed_at TEXT,
                execution_price REAL
            )
        """)
        
        # Create approval_tokens table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approval_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                trade_id INTEGER NOT NULL,
                proposal_hash TEXT,
                policy_version TEXT,
                requested_by TEXT DEFAULT 'ai',
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """)
        
        # Create treasury_yield table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS treasury_yield (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount_usd REAL,
                apy REAL,
                deployed_at TEXT,
                protocol TEXT,
                chain TEXT,
                active INTEGER DEFAULT 1
            )
        """)
        
        # Create treasury table if not exists (for tax collection)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS treasury (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tax_amount REAL,
                collected_at TEXT DEFAULT (datetime('now'))
            )
        """)
        
        con.commit()
        con.close()
        return True
    except Exception as e:
        print(f"Warning: Could not ensure tables: {e}")
        return False

# Initialize tables on startup
_ensure_tables()

# ------------------------------------------------------------------
# API ENDPOINTS
# ------------------------------------------------------------------

@app.get("/api/summary")
def summary():
    """Portfolio summary with P&L, exposure, and recent trades."""
    try:
        with _db_lock:  # Thread-safe database access
            con = _get_db_connection()
            cursor = con.cursor()
            
            # 1. Total closed trades, wins, lifetime P&L
            try:
                cursor.execute(
                    "SELECT COUNT(*) as total, "
                    "COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0) as wins, "
                    "COALESCE(SUM(pnl),0) as pnl "
                    "FROM trades WHERE status='closed'"
                )
                row = cursor.fetchone()
                total = row["total"] if row and row["total"] else 0
                wins = row["wins"] if row and row["wins"] else 0
                pnl = row["pnl"] if row and row["pnl"] else 0.0
            except sqlite3.OperationalError:
                total, wins, pnl = 0, 0, 0.0
            
            # 2. 24h P&L
            try:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                cursor.execute(
                    "SELECT COALESCE(SUM(pnl),0) as daily_pnl FROM trades WHERE status='closed' AND closed_at>=?",
                    (cutoff,)
                )
                daily_row = cursor.fetchone()
                daily = daily_row["daily_pnl"] if daily_row and daily_row["daily_pnl"] else 0.0
            except sqlite3.OperationalError:
                daily = 0.0
            
            # 3. Tax collected from treasury
            tax = 0.0
            try:
                cursor.execute("SELECT COALESCE(SUM(tax_amount),0) as tax FROM treasury")
                tax_row = cursor.fetchone()
                tax = tax_row["tax"] if tax_row and tax_row["tax"] else 0.0
            except sqlite3.OperationalError:
                tax = 0.0
            
            # 4. Yield deployed
            yield_deployed = 0.0
            yield_count = 0
            try:
                cursor.execute(
                    "SELECT COALESCE(SUM(amount_usd),0) as deployed, COUNT(*) as count FROM treasury_yield WHERE active=1"
                )
                yield_row = cursor.fetchone()
                yield_deployed = yield_row["deployed"] if yield_row and yield_row["deployed"] else 0.0
                yield_count = yield_row["count"] if yield_row and yield_row["count"] else 0
            except sqlite3.OperationalError:
                yield_deployed, yield_count = 0.0, 0
            
            # 5. Open notional exposure
            open_notional = 0.0
            try:
                cursor.execute(
                    "SELECT COALESCE(SUM(proposed_amount*COALESCE(actual_entry_price,proposed_price,0)),0) as exposure "
                    "FROM trades WHERE status NOT IN ('closed','proposed','rejected')"
                )
                exposure_row = cursor.fetchone()
                open_notional = exposure_row["exposure"] if exposure_row and exposure_row["exposure"] else 0.0
            except sqlite3.OperationalError:
                open_notional = 0.0
            
            # 6. Recent trades (last 8)
            recent = []
            try:
                cursor.execute(
                    "SELECT id, symbol, side, status, COALESCE(pnl,0) as pnl FROM trades ORDER BY id DESC LIMIT 8"
                )
                recent_rows = cursor.fetchall()
                recent = [
                    dict(id=r["id"], symbol=r["symbol"], side=r["side"], status=r["status"], pnl=r["pnl"] or 0.0) 
                    for r in recent_rows
                ]
            except sqlite3.OperationalError:
                recent = []
            
            con.close()
        
        # Calculate win rate safely
        win_rate = round((wins / total * 100) if total > 0 else 0.0, 1)
        
        # Determine circuit breaker state
        breaker = "TRIPPED" if (daily or 0) <= -500 else "ARMED"
        
        return {
            "total_closed": int(total),
            "wins": int(wins),
            "win_rate": win_rate,
            "lifetime_pnl": float(pnl) if pnl is not None else 0.0,
            "daily_pnl": float(daily) if daily is not None else 0.0,
            "breaker": breaker,
            "open_notional": float(open_notional) if open_notional is not None else 0.0,
            "tax_collected": float(tax) if tax is not None else 0.0,
            "yield_deployed": float(yield_deployed) if yield_deployed is not None else 0.0,
            "yield_positions": int(yield_count) if yield_count is not None else 0,
            "agent_wallet": _env("AGENT_WALLET_ADDRESS", "0x8d65...c1cc"),
            "recent": recent
        }
        
    except Exception as e:
        import traceback
        error_msg = f"Summary error: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        # Return safe defaults instead of 500 error
        return {
            "total_closed": 0,
            "wins": 0,
            "win_rate": 0.0,
            "lifetime_pnl": 0.0,
            "daily_pnl": 0.0,
            "breaker": "ARMED",
            "open_notional": 0.0,
            "tax_collected": 0.0,
            "yield_deployed": 0.0,
            "yield_positions": 0,
            "agent_wallet": _env("AGENT_WALLET_ADDRESS", "0x8d65...c1cc"),
            "recent": [],
            "error": error_msg
        }


@app.get("/api/trace/{trade_id}")
def get_trade_trace(trade_id: int):
    """
    Exposes the canonical Decision Dossier for a specific trade.
    Flow: Agent -> Tools -> Evidence -> Risk -> Governance -> Human Approval -> Audit
    """
    try:
        if not os.path.exists(DB_PATH):
            raise HTTPException(status_code=404, detail="Database not found")
            
        with _db_lock:
            con = _get_db_connection()
            
            # 1. Fetch core trade record
            trade = con.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if not trade:
                con.close()
                raise HTTPException(status_code=404, detail="Trade not found")
                
            # 2. Fetch associated approval token info (if any)
            token_info = con.execute(
                "SELECT token, expires_at, used_at, policy_version FROM approval_tokens WHERE trade_id = ?", 
                (trade_id,)
            ).fetchone()
            
            con.close()
        
        # 3. Construct the Decision Dossier
        dossier = {
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
            "agent_reasoning": trade["reasoning"] or "",
            "governance": {
                "proposal_hash": trade["proposal_hash"],
                "policy_version": trade["policy_version"] or (token_info["policy_version"] if token_info else None),
                "approval_token_issued": bool(token_info),
                "token_expires_at": token_info["expires_at"] if token_info else None,
                "token_used_at": token_info["used_at"] if token_info else None,
            },
            "audit_trail": {
                "created_at": trade.get("created_at"),
                "updated_at": trade.get("updated_at"),
                "execution_price": trade.get("execution_price"),
            }
        }
        
        return {"status": "success", "dossier": dossier}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trace error: {str(e)}")


# ------------------------------------------------------------------
# HTML DASHBOARD
# ------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Robo-Shopper Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e27;
            color: #e0e6ed;
            padding: 2rem;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { 
            color: #00d4ff; 
            margin-bottom: 2rem;
            font-size: 2rem;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .card {
            background: #1a1f3a;
            border: 1px solid #2a3050;
            border-radius: 12px;
            padding: 1.5rem;
        }
        .card h3 {
            color: #8b95b0;
            font-size: 0.875rem;
            text-transform: uppercase;
            margin-bottom: 0.5rem;
        }
        .card .value {
            font-size: 2rem;
            font-weight: 700;
            color: #00d4ff;
        }
        .card .value.positive { color: #00ff88; }
        .card .value.negative { color: #ff4466; }
        .breaker {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.875rem;
            font-weight: 600;
        }
        .breaker.ARMED { background: #00ff8820; color: #00ff88; }
        .breaker.TRIPPED { background: #ff446620; color: #ff4466; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #2a3050;
        }
        th {
            color: #8b95b0;
            font-size: 0.875rem;
            text-transform: uppercase;
        }
        .status {
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .status.closed { background: #00ff8820; color: #00ff88; }
        .status.proposed { background: #00d4ff20; color: #00d4ff; }
        .status.rejected { background: #ff446620; color: #ff4466; }
        .status.executed { background: #ffa50020; color: #ffa500; }
        .status.approved { background: #00ff8820; color: #00ff88; }
        .status.awaiting_approval { background: #00d4ff20; color: #00d4ff; }
        .loading { text-align: center; padding: 2rem; color: #8b95b0; }
        .error { 
            background: #ff446620; 
            color: #ff4466; 
            padding: 1rem; 
            border-radius: 8px; 
            text-align: center;
        }
        .warning {
            background: #ffa50020;
            color: #ffa500;
            padding: 0.5rem;
            border-radius: 4px;
            font-size: 0.875rem;
            margin-bottom: 1rem;
        }
        .trade-link {
            color: #00d4ff;
            text-decoration: none;
            font-weight: 600;
        }
        .trade-link:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ Robo-Shopper Dashboard</h1>
        <div id="content" class="loading">Loading portfolio data...</div>
    </div>

    <script>
        let refreshInterval;
        
        async function loadDashboard() {
            try {
                const res = await fetch('/api/summary');
                if (!res.ok) {
                    throw new Error(`Server responded with ${res.status}`);
                }
                const data = await res.json();
                
                // Show warning if there's an error in the response
                let warningHtml = '';
                if (data.error) {
                    warningHtml = `<div class="warning">⚠️ ${data.error}</div>`;
                }
                
                // Defensive: ensure all values exist
                const lifetimePnl = data.lifetime_pnl || 0;
                const dailyPnl = data.daily_pnl || 0;
                const winRate = data.win_rate || 0;
                const openNotional = data.open_notional || 0;
                const yieldDeployed = data.yield_deployed || 0;
                
                document.getElementById('content').innerHTML = `
                    ${warningHtml}
                    <div class="grid">
                        <div class="card">
                            <h3>Lifetime P&L</h3>
                            <div class="value ${lifetimePnl >= 0 ? 'positive' : 'negative'}">
                                $${Number(lifetimePnl).toLocaleString()}
                            </div>
                        </div>
                        <div class="card">
                            <h3>24h P&L</h3>
                            <div class="value ${dailyPnl >= 0 ? 'positive' : 'negative'}">
                                $${Number(dailyPnl).toLocaleString()}
                            </div>
                        </div>
                        <div class="card">
                            <h3>Win Rate</h3>
                            <div class="value">${Number(winRate).toFixed(1)}%</div>
                        </div>
                        <div class="card">
                            <h3>Open Exposure</h3>
                            <div class="value">$${Number(openNotional).toLocaleString()}</div>
                        </div>
                        <div class="card">
                            <h3>Circuit Breaker</h3>
                            <div class="breaker ${data.breaker || 'ARMED'}">${data.breaker || 'ARMED'}</div>
                        </div>
                        <div class="card">
                            <h3>Yield Deployed</h3>
                            <div class="value">$${Number(yieldDeployed).toLocaleString()}</div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>Recent Trades</h3>
                        ${(data.recent && data.recent.length > 0) ? `
                        <table>
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Asset</th>
                                    <th>Side</th>
                                    <th>Status</th>
                                    <th>P&L</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.recent.map(t => `
                                    <tr>
                                        <td><a href="/trace/${t.id}" target="_blank" class="trade-link">#${t.id || '?'}</a></td>
                                        <td>${t.symbol || 'N/A'}</td>
                                        <td>${t.side || 'N/A'}</td>
                                        <td><span class="status ${t.status || 'unknown'}">${t.status || 'unknown'}</span></td>
                                        <td class="${(t.pnl || 0) >= 0 ? 'positive' : 'negative'}" style="color: ${(t.pnl || 0) >= 0 ? '#00ff88' : '#ff4466'}">
                                            $${Number(t.pnl || 0).toFixed(2)}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                        ` : '<p style="color: #8b95b0; padding: 1rem; text-align: center;">No trades yet</p>'}
                    </div>
                    
                    <div class="card" style="margin-top: 1.5rem;">
                        <h3>Agent Wallet</h3>
                        <div style="font-family: monospace; color: #8b95b0;">${data.agent_wallet || 'Not configured'}</div>
                    </div>
                `;
            } catch (err) {
                document.getElementById('content').innerHTML = 
                    `<div class="error">Error loading dashboard: ${err.message}</div>`;
            }
        }
        
        // Load immediately, then refresh every 30 seconds
        loadDashboard();
        refreshInterval = setInterval(loadDashboard, 30000);
        
        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            if (refreshInterval) clearInterval(refreshInterval);
        });
    </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def page():
    """Serve the main dashboard HTML."""
    return PAGE


@app.get("/trace/{trade_id}", response_class=HTMLResponse)
def trace_page(trade_id: int):
    """Render a human-readable Decision Dossier for the judge demo."""
    try:
        if not os.path.exists(DB_PATH):
            return HTMLResponse("<h1>Database not found</h1>", status_code=404)
            
        with _db_lock:
            con = _get_db_connection()
            
            trade = con.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if not trade:
                con.close()
                return HTMLResponse("<h1>Trade not found</h1>", status_code=404)
                
            token_info = con.execute(
                "SELECT token, expires_at, used_at, policy_version FROM approval_tokens WHERE trade_id = ?", 
                (trade_id,)
            ).fetchone()
            con.close()

        # Build HTML Dossier
        html = f"""<!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Decision Dossier: Trade #{trade_id}</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0e27; color: #e0e6ed; padding: 2rem; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                h1 {{ color: #00d4ff; border-bottom: 1px solid #2a3050; padding-bottom: 1rem; margin-bottom: 1.5rem; }}
                .section {{ background: #1a1f3a; padding: 1.5rem; border-radius: 8px; margin-bottom: 1.5rem; border: 1px solid #2a3050; }}
                .section h2 {{ color: #8b95b0; font-size: 0.875rem; text-transform: uppercase; margin-bottom: 1rem; letter-spacing: 0.5px; }}
                .row {{ display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid #2a3050; }}
                .row:last-child {{ border-bottom: none; }}
                .label {{ color: #8b95b0; font-size: 0.9rem; }}
                .value {{ font-family: 'SF Mono', Monaco, monospace; color: #00ff88; font-size: 0.9rem; }}
                .status {{ padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }}
                .status.executed {{ background: #ffa50020; color: #ffa500; }}
                .status.rejected {{ background: #ff446620; color: #ff4466; }}
                .status.approved {{ background: #00ff8820; color: #00ff88; }}
                .status.proposed {{ background: #00d4ff20; color: #00d4ff; }}
                .status.awaiting_approval {{ background: #00d4ff20; color: #00d4ff; }}
                .hash {{ word-break: break-all; font-size: 0.75rem; color: #8b95b0; font-family: 'SF Mono', Monaco, monospace; background: #0a0e27; padding: 0.5rem; border-radius: 4px; margin-top: 0.5rem; display: block; }}
                a {{ color: #00d4ff; text-decoration: none; font-weight: 600; }}
                a:hover {{ text-decoration: underline; }}
                .back-link {{ display: inline-block; margin-bottom: 1.5rem; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="/" class="back-link">← Back to Dashboard</a>
                <h1>️ Decision Dossier: Trade #{trade_id}</h1>
                
                <div class="section">
                    <h2>1. Proposal Details</h2>
                    <div class="row"><span class="label">Asset / Side</span><span class="value">{trade['symbol']} / {trade['side'].upper()}</span></div>
                    <div class="row"><span class="label">Entry / Stop</span><span class="value">${trade['entry_price']} / ${trade['stop_loss']}</span></div>
                    <div class="row"><span class="label">Quantity</span><span class="value">{trade['quantity']}</span></div>
                    <div class="row"><span class="label">Status</span><span class="value"><span class="status {trade['status']}">{trade['status'].upper()}</span></span></div>
                </div>

                <div class="section">
                    <h2>2. Deterministic Risk Engine</h2>
                    <div class="row"><span class="label">Portfolio Balance</span><span class="value">${trade['portfolio_balance'] or 'N/A'}</span></div>
                    <div class="row"><span class="label">Risk Amount</span><span class="value">${trade['risk_amount'] or 'N/A'}</span></div>
                    <div class="row"><span class="label">Risk Percent</span><span class="value">{trade['risk_percent'] or 'N/A'}%</span></div>
                </div>

                <div class="section">
                    <h2>3. Agent Reasoning</h2>
                    <p style="color: #e0e6ed; line-height: 1.6; font-size: 0.95rem;">{trade['reasoning'] or 'No reasoning provided.'}</p>
                </div>

                <div class="section">
                    <h2>4. Governance & Authorization</h2>
                    <div class="row"><span class="label">Policy Version</span><span class="value">{trade['policy_version'] or 'N/A'}</span></div>
                    <div class="row"><span class="label">Token Issued</span><span class="value">{'Yes' if token_info else 'No'}</span></div>
                    <div class="row"><span class="label">Token Used At</span><span class="value">{token_info['used_at'] if token_info and token_info['used_at'] else 'Pending'}</span></div>
                    <div class="row" style="display:block;">
                        <span class="label">Proposal Hash (Tamper-Evident)</span>
                        <span class="hash">{trade['proposal_hash'] or 'N/A'}</span>
                    </div>
                </div>
            </div>
        </body>
        </html>"""
        return HTMLResponse(content=html)
        
    except Exception as e:
        return HTMLResponse(f"<h1>Error loading trace</h1><p>{str(e)}</p>", status_code=500)


# ------------------------------------------------------------------
# ENTRYPOINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Robo-Shopper Dashboard on http://localhost:8003")
    print(f"📊 Database: {DB_PATH}")
    uvicorn.run(app, host="0.0.0.0", port=8003)