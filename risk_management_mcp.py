import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "trades.db")

def _get_real_portfolio_balance():
    """Fetches actual balance from the treasury table or falls back to env var."""
    try:
        con = sqlite3.connect(DB_PATH)
        # Assuming a 'treasury' table exists with current_balance
        res = con.execute("SELECT current_balance FROM treasury ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        if res and res[0] > 0:
            return float(res[0])
    except:
        pass
    # Fallback to environment variable for safety
    return float(os.getenv("PORTFOLIO_BALANCE", "10000.0"))

def calculate_position_size(entry: float, stop: float, portfolio_balance: float = None):
    if portfolio_balance is None:
        portfolio_balance = _get_real_portfolio_balance()
    
    risk_percent = 0.02  # 2% hard cap
    risk_amount = portfolio_balance * risk_percent
    risk_per_unit = abs(entry - stop)
    
    if risk_per_unit == 0:
        return {"error": "Stop loss cannot equal entry price."}
    
    position_size = risk_amount / risk_per_unit
    
    return {
        "portfolio_balance": portfolio_balance,
        "max_risk_percent": risk_percent * 100,
        "risk_amount_usd": round(risk_amount, 2),
        "position_size": round(position_size, 4),
        "stop_loss": stop,
        "entry": entry
    }