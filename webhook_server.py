"""Robo-Shopper V4 - TradingView webhook ingest (Sprint 8)."""
import os
import sqlite3
from datetime import datetime, timezone

import telegram_notify  # also loads .env
from fastapi import FastAPI, HTTPException, Request

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "trades.db")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "robo-shopper-dev-secret")

app = FastAPI()


def _conn():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS webhook_alerts "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, "
                "price REAL, note TEXT, received_at TEXT, processed INTEGER DEFAULT 0)")
    return con


@app.post("/webhook")
async def webhook(request: Request):
    ctype = request.headers.get("content-type", "")
    body = await request.json() if "json" in ctype else {}
    secret = request.headers.get("X-Webhook-Secret", "") or (body.get("secret", "") if isinstance(body, dict) else "")
    if secret != WEBHOOK_SECRET:
        raise HTTPException(403, "bad secret")
    symbol = str(body.get("symbol", "BTCUSDT"))
    side = str(body.get("side", "buy"))
    price = float(body.get("price", 0) or body.get("close", 0))
    note = str(body.get("note", "TradingView alert"))
    con = _conn()
    con.execute("INSERT INTO webhook_alerts(symbol, side, price, note, received_at) VALUES (?,?,?,?,?)",
                (symbol, side, price, note, datetime.now(timezone.utc).isoformat()))
    con.commit()
    telegram_notify.send_alert(f"📈 TradingView trigger: {side.upper()} {symbol} @ {price} — {note}. Ask the agent to evaluate it.")
    return {"status": "logged"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
