"""Test helpers that follow the correct governance flow."""
from governance_engine import screen_trade, request_approval, approve_trade, execute_trade
from schemas import TradeStatus, ActorType
from state_machine import transition_trade


def screen_and_request_approval(tid: int):
    """
    Proper governance flow:
    PROPOSED → screen_trade() → RISK_CHECKED → AWAITING_APPROVAL → request_approval() → TOKEN
    
    This is the ONLY way to get a token in production.
    """
    screen_result = screen_trade(tid)
    if screen_result.get("status") != "SUCCESS":
        return screen_result  # Return the screening failure
    
    return request_approval(tid)


def create_screened_trade(symbol="BTC", side="long", quantity=0.01, entry=60000, stop=59500, portfolio_balance=10000.0):
    """
    End-to-end helper: create a trade with realistic sizing, screen it, request approval.
    
    Default: 0.01 BTC × $60,000 = $600 position (6% of $10k portfolio)
    This passes all gates: 2% risk cap, 20% exposure cap, circuit breaker.
    """
    from tests.test_security import create_proposed_trade
    tid = create_proposed_trade(symbol, side, quantity, entry, stop)
    
    # Ensure portfolio_balance is set (needed for exposure calculation)
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE trades SET portfolio_balance = ? WHERE id = ?",
        (portfolio_balance, tid)
    )
    conn.commit()
    conn.close()
    
    result = screen_and_request_approval(tid)
    return tid, result
