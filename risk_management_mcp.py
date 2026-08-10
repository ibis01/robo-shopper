import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("robo_shopper.risk_management")
logging.basicConfig(level=logging.INFO)

DEFAULT_PORTFOLIO_BALANCE = 10000.0
MAX_RISK_PER_TRADE_PCT = 0.02  # 2% max risk rule

def _get_portfolio_balance() -> float:
    # Mocked at $10,000 as requested
    return DEFAULT_PORTFOLIO_BALANCE

def _calculate_position_size(
    portfolio_balance: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float
) -> Dict[str, Any]:
    """Calculates exact position size based on stop loss distance and max risk %."""
    if entry_price <= 0 or stop_loss_price <= 0:
        return {"ok": False, "error": "Prices must be > 0"}
    
    risk_amount = portfolio_balance * risk_pct
    price_risk = abs(entry_price - stop_loss_price)
    
    if price_risk == 0:
        return {"ok": False, "error": "Entry and stop loss cannot be the same"}
        
    position_size = risk_amount / price_risk
    position_value = position_size * entry_price
    
    # Cap position size at 100% of portfolio (no leverage for now)
    if position_value > portfolio_balance:
        position_size = portfolio_balance / entry_price
        position_value = portfolio_balance
        
    return {
        "ok": True,
        "tool": "calculate_position_size",
        "portfolio_balance": portfolio_balance,
        "max_risk_amount": round(risk_amount, 2),
        "position_size": round(position_size, 6),
        "position_value": round(position_value, 2),
        "risk_pct": risk_pct
    }

def _evaluate_trade_risk(
    side: str,
    technicals: Dict[str, Any],
    proposed_amount: float,
    entry_price: float,
    stop_loss_price: Optional[float] = None,
    portfolio_balance: Optional[float] = None
) -> Dict[str, Any]:
    """Evaluates a trade against the Rulebook V2 governance engine."""
    portfolio = portfolio_balance if portfolio_balance is not None else _get_portfolio_balance()
    side = side.lower()
    
    risk_flags = []
    requires_extra_confirmation = False
    rejected = False
    rejection_reason = ""
    
    # 1. Check RSI > 70 for Buys (Overbought)
    rsi = technicals.get("rsi_14", 50.0)
    signal = technicals.get("signal", "Neutral")
    
    if side == "buy" and rsi > 70.0:
        risk_flags.append("RSI_OVERBOUGHT_BUY")
        requires_extra_confirmation = True
        
    if side == "sell" and rsi < 30.0:
        risk_flags.append("RSI_OVERSOLD_SELL")
        requires_extra_confirmation = True
        
    # 2. Check Portfolio limits
    position_value = proposed_amount * entry_price
    if position_value > portfolio:
        rejected = True
        rejection_reason = f"Position value (${position_value:.2f}) exceeds total portfolio balance (${portfolio:.2f})."
        risk_flags.append("EXCEEDS_PORTFOLIO")
        
    # 3. Check 2% Risk Rule (if stop loss is provided)
    if stop_loss_price and not rejected:
        price_risk = abs(entry_price - stop_loss_price)
        potential_loss = proposed_amount * price_risk
        max_allowed_loss = portfolio * MAX_RISK_PER_TRADE_PCT
        
        if potential_loss > max_allowed_loss:
            rejected = True
            rejection_reason = f"Potential loss (${potential_loss:.2f}) exceeds 2% max risk limit (${max_allowed_loss:.2f})."
            risk_flags.append("EXCEEDS_2_PERCENT_RISK")
            
    # Determine final decision
    if rejected:
        decision = "REJECTED"
    elif requires_extra_confirmation:
        decision = "REQUIRES_EXTRA_CONFIRMATION"
    else:
        decision = "APPROVED"
        
    return {
        "ok": True,
        "tool": "evaluate_trade_risk",
        "decision": decision,
        "side": side,
        "rsi_14": rsi,
        "signal": signal,
        "risk_flags": risk_flags,
        "rejection_reason": rejection_reason,
        "portfolio_balance": portfolio,
        "max_risk_allowed": round(portfolio * MAX_RISK_PER_TRADE_PCT, 2),
        "message": _generate_risk_message(decision, risk_flags, rejection_reason)
    }

def _generate_risk_message(decision: str, flags: list, reason: str) -> str:
    if decision == "REJECTED":
        return f"🛑 TRADE REJECTED: {reason}"
    elif decision == "REQUIRES_EXTRA_CONFIRMATION":
        return f"⚠️ HIGH RISK: Trade flagged with {', '.join(flags)}. Human must explicitly confirm to proceed."
    return "✅ Trade meets all risk parameters. Approved for execution."

def register_risk_management_tools(mcp: Any) -> None:
    @mcp.tool()
    def get_portfolio_balance() -> Dict[str, Any]:
        """Get the current mocked portfolio balance."""
        return {"ok": True, "tool": "get_portfolio_balance", "balance": _get_portfolio_balance()}

    @mcp.tool()
    def calculate_position_size(
        entry_price: float, 
        stop_loss_price: float, 
        risk_pct: float = MAX_RISK_PER_TRADE_PCT,
        portfolio_balance: Optional[float] = None
    ) -> Dict[str, Any]:
        """Calculate the exact position size based on dynamic risk management (max 2% risk)."""
        port = portfolio_balance if portfolio_balance is not None else _get_portfolio_balance()
        return _calculate_position_size(port, risk_pct, entry_price, stop_loss_price)

    @mcp.tool()
    def evaluate_trade_risk(
        side: str,
        technicals: Dict[str, Any],
        proposed_amount: float,
        entry_price: float,
        stop_loss_price: Optional[float] = None,
        portfolio_balance: Optional[float] = None
    ) -> Dict[str, Any]:
        """Evaluate a trade against the Rulebook V2 (2% risk limit, RSI overbought/oversold checks)."""
        return _evaluate_trade_risk(side, technicals, proposed_amount, entry_price, stop_loss_price, portfolio_balance)

if __name__ == "__main__":
    import json
    
    # Test 1: Safe trade
    techs_safe = {"rsi_14": 55.0, "signal": "Neutral"}
    print("Test 1 (Safe):", json.dumps(_evaluate_trade_risk("buy", techs_safe, 0.01, 60000, 59000), indent=2))
    
    # Test 2: Overbought buy (RSI > 70)
    techs_ob = {"rsi_14": 75.0, "signal": "Overbought"}
    print("\nTest 2 (Overbought):", json.dumps(_evaluate_trade_risk("buy", techs_ob, 0.01, 60000, 59000), indent=2))
    
    # Test 3: Exceeds 2% risk limit
    print("\nTest 3 (Too much risk):", json.dumps(_evaluate_trade_risk("buy", techs_safe, 1.0, 60000, 50000), indent=2))
