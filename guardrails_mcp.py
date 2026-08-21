"""
Robo-Shopper V4 - Portfolio Guardrails (Sprint 5).
Enforces circuit breakers, exposure limits, and correlation checks.
USES THE SAME SOURCE OF TRUTH for portfolio balance as the risk engine.
"""
import os
import sqlite3
from typing import Dict, Any, List, Optional

# --- IMPORT THE REAL BALANCE FETCHER (NO MOCKS) ---
from risk_management_mcp import _get_real_portfolio_balance

# Constants (using DECIMAL convention: 0.02 = 2%)
MAX_DAILY_DRAWDOWN = 0.05      # 5%
MAX_OPEN_EXPOSURE = 0.20       # 20%
CORE_ASSETS = ["BTC", "ETH", "SOL"]

def _get_open_positions() -> List[Dict[str, Any]]:
    """Fetches currently open positions from the trades ledger."""
    db_path = os.path.join(os.path.dirname(__file__), "data", "trades.db")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol, side, entry_price, position_size 
            FROM trades 
            WHERE status NOT IN ('closed', 'rejected', 'proposed')
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"symbol": r[0], "side": r[1], "entry": r[2], "size": r[3]} for r in rows]
    except:
        return []

def check_circuit_breaker() -> Dict[str, Any]:
    """
    Checks if the daily drawdown exceeds 5%.
    Uses the REAL portfolio balance.
    """
    try:
        balance = _get_real_portfolio_balance()
        db_path = os.path.join(os.path.dirname(__file__), "data", "trades.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get today's P&L
        cursor.execute("""
            SELECT COALESCE(SUM(pnl), 0) 
            FROM trades 
            WHERE status='closed' AND date(closed_at) = date('now')
        """)
        daily_pnl = cursor.fetchone()[0] or 0.0
        conn.close()
        
        daily_loss_pct = abs(daily_pnl) / balance if balance > 0 else 0
        
        if daily_loss_pct >= MAX_DAILY_DRAWDOWN:
            return {
                "status": "TRIPPED",
                "reason": f"Daily drawdown of {daily_loss_pct*100:.2f}% exceeds {MAX_DAILY_DRAWDOWN*100}% limit.",
                "daily_pnl": daily_pnl,
                "portfolio_balance": balance
            }
        return {
            "status": "ARMED",
            "reason": f"Daily drawdown {daily_loss_pct*100:.2f}% is within limit.",
            "daily_pnl": daily_pnl,
            "portfolio_balance": balance
        }
    except Exception as e:
        return {"status": "ERROR", "reason": f"Cannot check circuit breaker: {e}"}

def check_exposure_limit(proposed_size: float, proposed_entry: float) -> Dict[str, Any]:
    """
    Ensures total open exposure does not exceed 20% of portfolio.
    Uses REAL portfolio balance.
    """
    try:
        balance = _get_real_portfolio_balance()
        open_positions = _get_open_positions()
        
        # Calculate current exposure in USD
        current_exposure = sum([p["size"] * p["entry"] for p in open_positions])
        proposed_exposure = proposed_size * proposed_entry
        total_exposure = current_exposure + proposed_exposure
        
        exposure_pct = total_exposure / balance if balance > 0 else 0
        
        if exposure_pct > MAX_OPEN_EXPOSURE:
            return {
                "status": "REJECTED",
                "reason": f"Total exposure {exposure_pct*100:.2f}% exceeds {MAX_OPEN_EXPOSURE*100}% cap.",
                "current_exposure_usd": round(current_exposure, 2),
                "proposed_exposure_usd": round(proposed_exposure, 2),
                "total_exposure_usd": round(total_exposure, 2),
                "portfolio_balance": balance
            }
        return {
            "status": "PASSED",
            "reason": f"Total exposure {exposure_pct*100:.2f}% is within cap.",
            "current_exposure_usd": round(current_exposure, 2),
            "total_exposure_usd": round(total_exposure, 2),
            "portfolio_balance": balance
        }
    except Exception as e:
        return {"status": "ERROR", "reason": f"Cannot check exposure: {e}"}

def check_circuit_breaker() -> Dict[str, Any]:
    try:
        balance = _get_real_portfolio_balance()
        # ... check logic
    except Exception as e:
        return {
            "status": "ERROR",
            "reason": f"Circuit breaker unavailable: {e}",
            "recommendation": "HARD STOP - no trades until resolved."
        }
        
def check_correlation_risk(proposed_symbol: str) -> Dict[str, Any]:
    """
    Warns if trying to open a correlated position (e.g., BTC and ETH).
    """
    if proposed_symbol not in CORE_ASSETS:
        return {"status": "PASSED", "reason": "Asset not in core correlation set."}
    
    open_positions = _get_open_positions()
    open_symbols = [p["symbol"] for p in open_positions]
    
    # If we already have BTC open and propose ETH, flag it.
    for asset in CORE_ASSETS:
        if asset != proposed_symbol and asset in open_symbols:
            return {
                "status": "WARNING",
                "reason": f"Correlated asset {asset} is already open. Adding {proposed_symbol} increases correlated risk."
            }
    return {"status": "PASSED", "reason": "No correlation conflicts detected."}