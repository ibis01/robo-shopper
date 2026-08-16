"""Robo-Shopper V4 - TradingView trigger reader (Sprint 8)."""
import os
import sqlite3

from mcp.server.fastmcp import FastMCP

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "trades.db")


def register(mcp: FastMCP):
    @mcp.tool()
    def get_webhook_alerts(limit: int = 5) -> dict:
        """List recent TradingView webhook triggers awaiting evaluation."""
        con = sqlite3.connect(DB)
        con.execute("CREATE TABLE IF NOT EXISTS webhook_alerts "
                    "(id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, side TEXT, "
                    "price REAL, note TEXT, received_at TEXT, processed INTEGER DEFAULT 0)")
        rows = [dict(id=r[0], symbol=r[1], side=r[2], price=r[3], note=r[4], received_at=r[5])
                for r in con.execute(
                    "SELECT id, symbol, side, price, note, received_at "
                    "FROM webhook_alerts ORDER BY id DESC LIMIT ?", (limit,))]
        return {"alerts": rows,
                "note": "evaluate each trigger with the governance tools before proposing"}
