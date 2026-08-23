"""
Robo-Shopper V4 - Adversarial Security Tests (Sprint 5).
Proves that governance CANNOT be bypassed using the public API.
"""
import pytest
import sys
import os
import sqlite3
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus, ActorType, TradeSide
from state_machine import transition_trade
from tests.test_helpers import screen_and_request_approval
from governance_engine import request_approval, approve_trade, execute_trade
from trade_memory_mcp import propose_trade, get_trade
from config import DB_PATH


@pytest.fixture
def clean_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM approval_tokens")
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM approval_tokens")
    conn.commit()
    conn.close()


def create_proposed_trade(symbol="BTC", side="long", quantity=0.01, entry=60000, stop=59500, reasoning="test"):
    prop = propose_trade(symbol, side, quantity, entry, stop, reasoning=reasoning)
    
    # Set realistic portfolio_balance for exposure calculations
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?",
        (prop["trade_id"],)
    )
    conn.commit()
    conn.close()
    
    return prop["trade_id"]

    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?",
        (prop["trade_id"],)
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# TESTS: UNAUTHORIZED ACTORS
# ------------------------------------------------------------------
def test_ai_cannot_approve(clean_db):
    tid = create_proposed_trade()
    screen_and_request_approval(tid)  # proper governance flow
    result = transition_trade(tid, TradeStatus.APPROVED, ActorType.AI)
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"]

def test_system_cannot_approve(clean_db):
    tid = create_proposed_trade()
    screen_and_request_approval(tid)
    result = transition_trade(tid, TradeStatus.APPROVED, ActorType.SYSTEM)
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"]

def test_ai_cannot_execute(clean_db):
    tid = create_proposed_trade()
    result = transition_trade(tid, TradeStatus.EXECUTED, ActorType.AI, require_approval_hash="123")
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"] or "ILLEGAL" in result["message"]

def test_system_cannot_execute(clean_db):
    tid = create_proposed_trade()
    result = transition_trade(tid, TradeStatus.EXECUTED, ActorType.SYSTEM, require_approval_hash="123")
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"] or "ILLEGAL" in result["message"]

# ------------------------------------------------------------------
# TESTS: TOKEN VALIDATION
# ------------------------------------------------------------------
def test_wrong_token_fails(clean_db):
    result = approve_trade("invalid_token")
    assert result["status"] == "REJECTED"
    assert "Invalid" in result["reason"]

def test_expired_token_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    expired_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    cursor.execute("UPDATE approval_tokens SET expires_at = ? WHERE token = ?", (expired_time, token))
    conn.commit()
    conn.close()
    result = approve_trade(token)
    assert result["status"] == "REJECTED"
    assert "Invalid" in result["reason"]

def test_replayed_token_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    res1 = approve_trade(token)
    assert res1["status"] == "SUCCESS"
    res2 = approve_trade(token)
    assert res2["status"] == "REJECTED"
    assert "Invalid" in res2["reason"]

def test_token_for_wrong_trade_fails(clean_db):
    tid1 = create_proposed_trade()
    tid2 = create_proposed_trade(symbol="ETH", entry=3000, stop=2950)
    req1 = screen_and_request_approval(tid1)
    assert req1["status"] == "success"
    token1 = req1["approval_token"]
    approve_trade(token1)
    trade1 = get_trade(tid1)
    assert trade1["status"] == TradeStatus.APPROVED.value
    trade2 = get_trade(tid2)
    assert trade2["status"] == TradeStatus.PROPOSED.value  # never requested approval

# ------------------------------------------------------------------
# TESTS: PROPOSAL TAMPERING
# ------------------------------------------------------------------
def test_modified_quantity_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    approve_trade(token)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET quantity = 999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    result = execute_trade(tid, execution_price=60100)
    assert result["status"] == "REJECTED"
    assert "Hash mismatch" in result["reason"] or "TAMPERED" in result["reason"]

def test_modified_entry_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    approve_trade(token)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET entry_price = 99999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    result = execute_trade(tid, execution_price=60100)
    assert result["status"] == "REJECTED"
    assert "Hash mismatch" in result["reason"]

def test_modified_policy_version_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET policy_version = '2.0.0' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    result = approve_trade(token)
    assert result["status"] == "REJECTED"
    assert "POLICY MISMATCH" in result["reason"]

# ------------------------------------------------------------------
# TESTS: STATE TRANSITIONS
# ------------------------------------------------------------------
def test_rejected_trade_cannot_execute(clean_db):
    tid = create_proposed_trade()
    transition_trade(tid, TradeStatus.REJECTED, ActorType.RISK_ENGINE)
    result = execute_trade(tid, execution_price=60000)
    assert result["status"] == "REJECTED"
    assert "must be 'approved'" in result["reason"]

def test_double_execution_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    approve_trade(token)
    res1 = execute_trade(tid, execution_price=60100)
    assert res1["status"] == "SUCCESS"
    res2 = execute_trade(tid, execution_price=60200)
    assert res2["status"] == "SUCCESS"
    assert res2.get("idempotent") == True

def test_awaiting_approval_cannot_execute(clean_db):
    tid = create_proposed_trade()
    # Move to AWAITING_APPROVAL via request_approval but do not approve
    request_approval(tid)
    result = execute_trade(tid, execution_price=60000)
    assert result["status"] == "REJECTED"
    assert "must be 'approved'" in result["reason"]

def test_modified_risk_amount_fails(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    approve_trade(token)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET stop_loss = 59000 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    result = execute_trade(tid, execution_price=60100)
    assert result["status"] == "REJECTED"
    assert "Hash mismatch" in result["reason"]

def test_modified_expiration_fails(clean_db):
    from schemas import TradeProposal
    import datetime as dt
    expires_1 = dt.datetime.now(timezone.utc) + dt.timedelta(hours=1)
    expires_2 = dt.datetime.now(timezone.utc) + dt.timedelta(hours=2)
    p1 = TradeProposal(
        asset="BTC",
        side=TradeSide.LONG,
        entry_price=60000,
        stop_loss=59500,
        quantity=0.4,
        risk_percent=0.02,
        risk_amount=200.0,
        portfolio_balance_at_time=10000,
        agent_reasoning="test",
        risk_decision="PASSED",
        expires_at=expires_1
    )
    p2 = TradeProposal(
        asset="BTC",
        side=TradeSide.LONG,
        entry_price=60000,
        stop_loss=59500,
        quantity=0.4,
        risk_percent=0.02,
        risk_amount=200.0,
        portfolio_balance_at_time=10000,
        agent_reasoning="test",
        risk_decision="PASSED",
        expires_at=expires_2
    )
    assert p1.compute_hash() != p2.compute_hash()

def test_get_proposal_hash_fails_on_missing_balance(clean_db):
    """Invariant #1: _get_proposal_hash must fail closed when portfolio_balance is missing."""
    from governance_engine import _get_proposal_hash
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    trade = get_trade(prop["trade_id"])
    # Remove the portfolio_balance field to simulate corruption
    del trade["portfolio_balance"]
    with pytest.raises(KeyError):
        _get_proposal_hash(trade)

def test_approve_trade_rejects_post_token_trade_tampering(clean_db):
    """Invariant #3: approve_trade must independently recompute the hash and reject tampering."""
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    # Tamper with the trade after token minting
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET quantity = 999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    # Approval should fail due to hash mismatch
    result = approve_trade(token)
    assert result["status"] == "REJECTED"
    assert "PROPOSAL TAMPERED" in result["reason"]
    # Ensure the trade is still in AWAITING_APPROVAL (not approved)
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.AWAITING_APPROVAL.value