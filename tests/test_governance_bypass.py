"""Test that request_approval() cannot bypass risk screening."""
import pytest
from governance_engine import request_approval, screen_trade
from tests.test_security import create_proposed_trade, clean_db
from schemas import TradeStatus
from trade_memory_mcp import get_trade

def test_request_approval_rejects_unscreened_trade(clean_db):
    """request_approval() must reject trades that haven't been screened."""
    tid = create_proposed_trade()
    
    # Trade is PROPOSED (not yet screened)
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.PROPOSED.value
    
    # request_approval should REJECT because trade hasn't been screened
    result = request_approval(tid)
    assert result["status"] == "REJECTED"
    assert "screen_trade" in result["reason"].lower() or "awaiting_approval" in result["reason"].lower()

def test_request_approval_works_after_screening(clean_db):
    """request_approval() works after screen_trade() passes."""
    tid = create_proposed_trade()
    
    # Screen the trade (runs risk/exposure/breaker checks)
    screen_result = screen_trade(tid)
    
    # Debug: if screening fails, show why
    if screen_result.get("status") != "SUCCESS":
        print(f"Screen failed: {screen_result}")
    
    assert screen_result["status"] == "SUCCESS", f"Screening failed: {screen_result}"
    
    # Now trade should be AWAITING_APPROVAL
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.AWAITING_APPROVAL.value
    
    # request_approval should now succeed
    result = request_approval(tid)
    assert result["status"] == "success"
    assert "approval_token" in result

