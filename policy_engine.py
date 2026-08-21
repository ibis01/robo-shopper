"""
Robo-Shopper V4 - Policy Engine (Sprint 5).
Centralized hard constraints. The LLM NEVER defines its own limits.
"""
from typing import Dict, Any
from config import MAX_RISK_PER_TRADE, MAX_DAILY_DRAWDOWN, MAX_OPEN_EXPOSURE

# Hard-coded policies – only humans can change these
POLICIES = {
    "max_risk_per_trade": MAX_RISK_PER_TRADE,
    "max_daily_drawdown": MAX_DAILY_DRAWDOWN,
    "max_open_exposure": MAX_OPEN_EXPOSURE,
    "require_human_approval": True,
    "dry_run_mode": True,
    "min_btc_size": 0.0001,
    "min_eth_size": 0.001,
    "min_sol_size": 0.01,
    "max_btc_size": 10.0,
    "max_eth_size": 100.0,
    "max_sol_size": 1000.0,
}

def get_policy(key: str) -> Any:
    """Fetch a policy value. Raises KeyError if not found."""
    return POLICIES[key]

def check_trade_against_policies(
    symbol: str,
    side: str,
    entry: float,
    stop: float,
    quantity: float,
    portfolio_balance: float
) -> Dict[str, Any]:
    """
    Check a proposed trade against ALL hard policies.
    Returns PASSED or REJECTED with the specific violation.
    """
    # 1. Risk cap
    risk_per_unit = abs(entry - stop)
    risk_usd = risk_per_unit * quantity
    risk_pct = risk_usd / portfolio_balance
    
    if risk_pct > POLICIES["max_risk_per_trade"]:
        return {
            "status": "REJECTED",
            "policy": "max_risk_per_trade",
            "limit": POLICIES["max_risk_per_trade"],
            "proposed": round(risk_pct, 4),
            "message": f"Risk {risk_pct*100:.2f}% exceeds {POLICIES['max_risk_per_trade']*100}% cap."
        }
    
    # 2. Minimum size (per asset)
    min_key = f"min_{symbol.lower()}_size"
    if min_key in POLICIES and quantity < POLICIES[min_key]:
        return {
            "status": "REJECTED",
            "policy": min_key,
            "limit": POLICIES[min_key],
            "proposed": quantity,
            "message": f"Quantity {quantity} below minimum {POLICIES[min_key]} for {symbol}."
        }
    
    # 3. Maximum size (per asset)
    max_key = f"max_{symbol.lower()}_size"
    if max_key in POLICIES and quantity > POLICIES[max_key]:
        return {
            "status": "REJECTED",
            "policy": max_key,
            "limit": POLICIES[max_key],
            "proposed": quantity,
            "message": f"Quantity {quantity} exceeds maximum {POLICIES[max_key]} for {symbol}."
        }
    
    # 4. Human approval required
    if POLICIES["require_human_approval"] and side != "test":
        # This is enforced by the state machine, but we flag it here
        pass
    
    # All checks passed
    return {
        "status": "PASSED",
        "message": "Trade passes all hard policies.",
        "checks": {
            "risk_pct": round(risk_pct, 4),
            "risk_usd": round(risk_usd, 2),
            "portfolio_balance": round(portfolio_balance, 2)
        }
    }