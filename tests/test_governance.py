import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_memory_mcp import propose_trade, record_execution, approve_trade
from schemas import TradeStatus

def test_cannot_execute_without_approval():
    """Prove that PROPOSED → EXECUTED is impossible."""
    # Propose a trade
    result = propose_trade(
        symbol="BTC", side="long", quantity=0.4, 
        entry_price=60000, stop_loss=59500, 
        reasoning="Test"
    )
    trade_id = result["trade_id"]
    
    # Try to execute directly (should FAIL)
    with pytest.raises(ValueError, match="ILLEGAL STATE TRANSITION"):
        record_execution(trade_id, execution_price=60000)
    
    # Now approve it properly
    approve_trade(trade_id)
    
    # Now execution should work
    exec_result = record_execution(trade_id, execution_price=60000)
    assert exec_result["new_status"] == TradeStatus.EXECUTED.value