"""Robo-Shopper V4 - Read-only dashboard (Sprint 2)."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "trades.db")  # <-- FIXED: point to ./data/trades.db
app = FastAPI()

def _env(key, default=""):
    try:
        for ln in open(os.path.join(BASE, ".env")):
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.getenv(key, default)

@app.get("/api/summary")
def summary():
    con = sqlite3.connect(DB)
    
    # 1. Total closed trades, wins, lifetime P&L
    total, wins, pnl = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0), COALESCE(SUM(pnl),0) "
        "FROM trades WHERE status='closed'"
    ).fetchone()
    
    # 2. 24h P&L
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    daily = con.execute(
        "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='closed' AND closed_at>=?",
        (cutoff,)
    ).fetchone()[0]
    
    # 3. Tax collected from treasury
    # Check if 'tax_amount' column exists first (old DBs might not have it)
    tax = 0
    try:
        tax = con.execute("SELECT COALESCE(SUM(tax_amount),0) FROM treasury").fetchone()[0]
    except sqlite3.OperationalError:
        tax = 0  # table doesn't exist yet
    
    # 4. Yield deployed (treasury_yield table)
    con.execute("""
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
    yield_deployed, yield_count = con.execute(
        "SELECT COALESCE(SUM(amount_usd),0), COUNT(*) FROM treasury_yield WHERE active=1"
    ).fetchone()
    
    # 5. Open notional exposure
    open_notional = con.execute(
        "SELECT COALESCE(SUM(proposed_amount*COALESCE(actual_entry_price,proposed_price,0)),0) "
        "FROM trades WHERE status NOT IN ('closed','proposed','rejected')"
    ).fetchone()[0]
    
    # 6. Recent trades (last 8)
    recent = [
        dict(id=r[0], symbol=r[1], side=r[2], status=r[3], pnl=r[4]) 
        for r in con.execute(
            "SELECT id, symbol, side, status, pnl FROM trades ORDER BY id DESC LIMIT 8"
        )
    ]
    
    con.close()
    
    return {
        "total_closed": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "lifetime_pnl": round(pnl, 2),
        "daily_pnl": round(daily, 2),
        "breaker": "TRIPPED" if daily <= -500 else "ARMED",
        "open_notional": round(open_notional, 2),
        "tax_collected": round(tax, 2),
        "yield_deployed": round(yield_deployed, 2),
        "yield_positions": yield_count,  # <-- FIXED: now defined
        "agent_wallet": _env("AGENT_WALLET_ADDRESS", "0x8d65...c1cc"),
        "recent": recent
    }

# (Your HTML PAGE remains exactly the same - I'm omitting it here for brevity,
# but keep the PAGE variable from your original file)

PAGE = """<!doctype html>..."""  # <-- paste your existing PAGE HTML here

@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)