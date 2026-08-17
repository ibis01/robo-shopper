import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade, approve_and_execute_trade
from schemas import TradeStatus

def test_full_governance_pipeline():
    """End-to-end: PROPOSE → SCREEN → APPROVE → EXECUTE"""
    # 1. Propose
    proposal = propose_trade(
        symbol="BTC", side="long", quantity=0.4,
        entry_price=60000, stop_loss=59500,
        reasoning="Test full pipeline"
    )
    trade_id = proposal["trade_id"]
    
    # 2. Screen
    screen_result = screen_trade(trade_id)
    assert screen_result["status"] == "PASSED"
    assert screen_result["new_status"] == TradeStatus.AWAITING_APPROVAL.value
    
    # 3. Approve + Execute
    exec_result = approve_and_execute_trade(
        trade_id=trade_id,
        execution_price=60100,
        approved_by="pytest"
    )
    assert exec_result["status"] == "success"
    
    # 4. Verify final state
    trade = get_trade(trade_id)
    assert trade["status"] == TradeStatus.EXECUTED.value
    assert trade["execution_price"] == 60100.0
    assert trade["approved_by"] == "pytest"