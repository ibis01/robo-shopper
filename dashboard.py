"""Robo-Shopper V4 - Read-only dashboard (Sprint 2)."""
import os, sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "trades.db")
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
    total, wins, pnl = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0), COALESCE(SUM(pnl),0) "
        "FROM trades WHERE status='closed'").fetchone()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    daily = con.execute("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='closed' AND closed_at>=?",
                        (cutoff,)).fetchone()[0]
    tax = con.execute("SELECT COALESCE(SUM(tax_amount),0) FROM treasury").fetchone()[0]
    open_notional = con.execute(
        "SELECT COALESCE(SUM(proposed_amount*COALESCE(actual_entry_price,proposed_price,0)),0) "
        "FROM trades WHERE status NOT IN ('closed','proposed','rejected')").fetchone()[0]
    recent = [dict(id=r[0], symbol=r[1], side=r[2], status=r[3], pnl=r[4]) for r in con.execute(
        "SELECT id, symbol, side, status, pnl FROM trades ORDER BY id DESC LIMIT 8")]
    return {"total_closed": total, "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "lifetime_pnl": round(pnl, 2), "daily_pnl": round(daily, 2),
            "breaker": "TRIPPED" if daily <= -500 else "ARMED",
            "open_notional": round(open_notional, 2), "tax_collected": round(tax, 2),
            "agent_wallet": _env("AGENT_WALLET_ADDRESS", ""), "recent": recent}

PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Robo-Shopper V4</title>
<style>
body{background:#0d1117;color:#e6edf3;font-family:ui-monospace,monospace;margin:0;padding:24px}
h1{color:#00c2ff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card b{display:block;font-size:22px;margin-top:6px}
.green{color:#3fb950}.red{color:#f85149}.amber{color:#d29922}
table{width:100%;border-collapse:collapse;margin-top:16px}
td,th{padding:6px 8px;border-bottom:1px solid #30363d;text-align:left}
</style></head><body>
<h1>🤖 Robo-Shopper V4 — Governed Copilot</h1>
<div class=grid id=cards></div>
<table><thead><tr><th>#</th><th>Symbol</th><th>Side</th><th>Status</th><th>PnL</th></tr></thead>
<tbody id=rows></tbody></table>
<script>
async function tick(){
  const d = await (await fetch('/api/summary')).json();
  const c = [
    ['Win rate', d.win_rate+'%', ''],
    ['Lifetime PnL', '$'+d.lifetime_pnl, d.lifetime_pnl>=0?'green':'red'],
    ['24h PnL', '$'+d.daily_pnl, d.daily_pnl>=0?'green':'red'],
    ['Breaker', d.breaker, d.breaker=='ARMED'?'green':'red'],
    ['Open exposure', '$'+d.open_notional, 'amber'],
    ['Agent tax bank', '$'+d.tax_collected, 'green'],
  ];
  document.getElementById('cards').innerHTML =
    c.map(x=>'<div class=card>'+x[0]+'<b class="'+x[2]+'">'+x[1]+'</b></div>').join('');
  document.getElementById('rows').innerHTML =
    d.recent.map(r=>'<tr><td>'+r.id+'</td><td>'+r.symbol+'</td><td>'+r.side+'</td><td>'+r.status+'</td><td>'+(r.pnl??'')+'</td></tr>').join('');
}
tick(); setInterval(tick, 5000);
</script></body></html>"""

@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
