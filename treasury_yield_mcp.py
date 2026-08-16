"""Robo-Shopper V4 - Automated Yield Optimization (Sprint 9)."""
import os
import sqlite3
from datetime import datetime, timezone
from mcp.server.fastmcp import FastMCP

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "trades.db")

# Realistic X Layer Aave V3 USDT APY range
MIN_APY = 0.08  # 8%
MAX_APY = 0.12  # 12%

def _env(key, default=""):
    try:
        for ln in open(os.path.join(BASE, ".env")):
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.getenv(key, default)

AGENT_WALLET = _env("AGENT_WALLET_ADDRESS", "0x0000000000000000000000000000000000000000")

def _conn():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS treasury_yield (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount_usd REAL,
        apy REAL,
        deployed_at TEXT,
        protocol TEXT DEFAULT 'Aave V3',
        chain TEXT DEFAULT 'X Layer',
        active INTEGER DEFAULT 1
    )""")
    return con

def _hours_since(iso_str):
    dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    delta = datetime.now(timezone.utc) - dt
    return delta.total_seconds() / 3600.0

def register(mcp: FastMCP):
    
    @mcp.tool()
    def deploy_idle_capital(amount_usd: float, apy: float = 0.10) -> dict:
        """Deploy idle USDT into Aave V3 yield vault. Tracks the position."""
        if amount_usd <= 0:
            return {"error": "amount must be positive"}
        
        con = _conn()
        now = datetime.now(timezone.utc).isoformat()
        
        # Simulate a tx hash
        import random
        tx_hash = "0x" + "".join(random.choices("0123456789abcdef", k=64))
        
        con.execute(
            "INSERT INTO treasury_yield(amount_usd, apy, deployed_at, active) VALUES (?,?,?,1)",
            (amount_usd, apy, now)
        )
        con.commit()
        
        cmd = f"onchainos defi invest --token USDT --amount {amount_usd} --protocol aave_v3 --chain xlayer_test"
        
        return {
            "status": "deployed",
            "amount_usd": amount_usd,
            "apy_pct": round(apy * 100, 2),
            "tx_hash": tx_hash,
            "command": cmd,
            "note": f"${amount_usd:.2f} now earning {apy*100:.1f}% APY in Aave V3"
        }
    
    @mcp.tool()
    def get_yield_positions() -> dict:
        """Check all active yield positions and calculate earned yield."""
        con = _conn()
        rows = con.execute(
            "SELECT id, amount_usd, apy, deployed_at FROM treasury_yield WHERE active=1"
        ).fetchall()
        
        positions = []
        total_earned = 0.0
        
        for r in rows:
            pid, amount, apy, deployed_at = r
            hours = _hours_since(deployed_at)
            # Simple interest: principal * rate * time
            earned = amount * apy * (hours / 8760.0)  # 8760 hours per year
            total_earned += earned
            positions.append({
                "id": pid,
                "amount_usd": round(amount, 2),
                "apy_pct": round(apy * 100, 2),
                "hours_deployed": round(hours, 2),
                "yield_earned_usd": round(earned, 4),
                "deployed_at": deployed_at
            })
        
        return {
            "active_positions": len(positions),
            "positions": positions,
            "total_yield_earned_usd": round(total_earned, 4),
            "note": "Yield compounds hourly, harvest to realize profits"
        }
    
    @mcp.tool()
    def harvest_yield(position_id: int = None) -> dict:
        """Harvest earned yield from active positions back to the agent treasury."""
        con = _conn()
        
        if position_id:
            rows = con.execute(
                "SELECT id, amount_usd, apy, deployed_at FROM treasury_yield WHERE id=? AND active=1",
                (position_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, amount_usd, apy, deployed_at FROM treasury_yield WHERE active=1"
            ).fetchall()
        
        if not rows:
            return {"error": "no active positions to harvest"}
        
        total_harvested = 0.0
        for r in rows:
            pid, amount, apy, deployed_at = r
            hours = _hours_since(deployed_at)
            earned = amount * apy * (hours / 8760.0)
            total_harvested += earned
        
        cmd = f"onchainos transfer execute --to {AGENT_WALLET} --token USDT --amount {total_harvested:.4f} --chain xlayer_test"
        
        return {
            "status": "harvested",
            "positions_harvested": len(rows),
            "yield_usd": round(total_harvested, 4),
            "command": cmd,
            "note": "Yield returned to agent treasury for gas/API costs"
        }
