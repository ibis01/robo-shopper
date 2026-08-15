"""Robo-Shopper V3 - Agentic Treasury."""
import os
import sqlite3
from datetime import datetime, timezone
from mcp.server.fastmcp import FastMCP
from web3 import Web3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "trades.db")

def _env(key, default=""):
    try:
        for ln in open(os.path.join(BASE, ".env")):
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except Exception: pass
    return os.getenv(key, default)

AGENT_WALLET = _env("AGENT_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000")

def _conn():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS treasury (id INTEGER PRIMARY KEY, trade_id INTEGER UNIQUE, pnl REAL, tax_amount REAL, collected_at TEXT)")
    return con

def register(mcp: FastMCP):
    @mcp.tool()
    def get_treasury_status() -> dict:
        """Check the agent's personal wallet balance and how much performance tax it has collected."""
        con = _conn()
        collected, n_tax = con.execute("SELECT COALESCE(SUM(tax_amount),0), COUNT(*) FROM treasury").fetchone()
        lifetime = con.execute("SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='closed'").fetchone()[0]
        return {
            "agent_wallet": AGENT_WALLET,
            "tax_collected_usdt": collected,
            "taxes_count": n_tax,
            "lifetime_realized_pnl": lifetime,
            "note": "The agent skims 2% of wins to pay its own API/gas. Losses are never taxed."
        }

    @mcp.tool()
    def collect_performance_tax(trade_id: int, tax_pct: float = 2.0) -> dict:
        """Skim a performance tax from a closed, profitable trade into the agent's wallet."""
        con = _conn()
        row = con.execute("SELECT symbol, pnl, status FROM trades WHERE id=?", (trade_id,)).fetchone()
        if not row: return {"error": f"trade {trade_id} not found"}
        symbol, pnl, status = row
        if status != "closed": return {"error": "tax applies only to closed trades"}
        if pnl is None or pnl <= 0: return {"error": "the agent only taxes wins"}
        if con.execute("SELECT 1 FROM treasury WHERE trade_id=?", (trade_id,)).fetchone():
            return {"error": "already taxed"}
        
        tax = round(pnl * tax_pct / 100.0, 2)
        cmd = f"onchainos transfer execute --to {AGENT_WALLET} --token USDT --amount {tax} --chain xlayer_test"
        con.execute("INSERT INTO treasury(trade_id,pnl,tax_amount,collected_at) VALUES (?,?,?,?)",
                    (trade_id, pnl, tax, datetime.now(timezone.utc).isoformat()))
        con.commit()
        return {"trade_id": trade_id, "tax_amount": tax, "command": cmd, "status": "recorded - human approval required to execute"}

    @mcp.tool()
    def propose_idle_sweep(idle_usd: float) -> dict:
        """Propose sweeping idle USDT into a safe X Layer yield vault while awaiting setups."""
        cmd = f"onchainos defi invest --token USDT --amount {idle_usd} --protocol aave_v3 --chain xlayer_test"
        return {
            "idle_usd": idle_usd,
            "target": "Aave V3 USDT vault (X Layer)",
            "command": cmd,
            "note": "Idle capital earns yield while waiting for the next approved setup."
        }
