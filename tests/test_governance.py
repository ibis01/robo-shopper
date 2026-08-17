import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade, request_approval, approve_trade, execute_trade
from schemas import TradeStatus

def test_full_governance_pipeline():
    """End-to-end: PROPOSE → SCREEN → REQUEST → APPROVE → EXECUTE"""
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
    
    # 3. Request approval
    req_result = request_approval(trade_id, requested_by="pytest")
    assert req_result["status"] == "success"
    token = req_result["approval_token"]
    stored_hash = req_result["proposal_hash"]
    
    # 4. Approve (atomic token consumption)
    approve_result = approve_trade(token, approved_by="pytest_human")
    assert approve_result["status"] == "SUCCESS"
    assert approve_result["new_status"] == TradeStatus.APPROVED.value
    
    # 5. Execute
    exec_result = execute_trade(trade_id, execution_price=60100, executed_by="pytest")
    assert exec_result["status"] == "SUCCESS"
    assert exec_result["new_status"] == TradeStatus.EXECUTED.value
    
    # 6. Verify final state
    trade = get_trade(trade_id)
    assert trade["status"] == TradeStatus.EXECUTED.value
    assert trade["execution_price"] == 60100.0
    assert trade["proposal_hash"] == stored_hash