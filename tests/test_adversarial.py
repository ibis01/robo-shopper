import pytest
from schemas import TradeStatus, ActorType
from state_machine import transition_trade

def test_ai_cannot_approve():
    """AI actor attempting to approve should be rejected."""
    # Create a trade in AWAITING_APPROVAL state (simulate this)
    result = transition_trade(
        trade_id=1,
        target_status=TradeStatus.APPROVED,
        actor=ActorType.AI,  # AI tries to approve
    )
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED ACTOR" in result["message"]

def test_ai_cannot_execute_without_approval():
    """AI cannot execute a trade not in APPROVED state."""
    result = transition_trade(
        trade_id=1,
        target_status=TradeStatus.EXECUTED,
        actor=ActorType.AI,
        require_approval_hash="fake_hash"
    )
    assert result["status"] == "REJECTED"