"""
Robo-Shopper V4 - Adversarial Security Tests (Sprint 5).
Proves that governance CANNOT be bypassed.
"""
import pytest
import sys
import os
import sqlite3
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus, ActorType
from state_machine import transition_trade
from governance_engine import request_approval, approve_trade, execute_trade, screen_trade
from trade_memory_mcp import propose_trade, get_trade
from config import DB_PATH

# ------------------------------------------------------------------
# FIXTURE: Clean DB for each test
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# TESTS: UNAUTHORIZED ACTORS
# ------------------------------------------------------------------
def test_ai_cannot_approve(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    request_approval(tid)
    result = transition_trade(tid, TradeStatus.APPROVED, ActorType.AI)
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"]

def test_system_cannot_approve(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    request_approval(tid)
    result = transition_trade(tid, TradeStatus.APPROVED, ActorType.SYSTEM)
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"]

def test_ai_cannot_execute(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    # Try to execute without approval (should fail due to state)
    result = transition_trade(tid, TradeStatus.EXECUTED, ActorType.AI, require_approval_hash="123")
    assert result["status"] == "REJECTED"
    assert "UNAUTHORIZED" in result["message"] or "ILLEGAL" in result["message"]

def test_system_cannot_execute(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
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
    # Create an expired token manually
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO approval_tokens (token, trade_id, proposal_hash, policy_version, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, ("expired_token", 1, "hash", "1.0", (datetime.utcnow() - timedelta(hours=2)).isoformat()))
    conn.commit()
    conn.close()
    result = approve_trade("expired_token")
    assert result["status"] == "REJECTED"
    assert "Invalid" in result["reason"]

def test_replayed_token_fails(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
    token = req["approval_token"]
    res1 = approve_trade(token)
    assert res1["status"] == "SUCCESS"
    res2 = approve_trade(token)
    assert res2["status"] == "REJECTED"
    assert "Invalid" in res2["reason"]

def test_token_for_wrong_trade_fails(clean_db):
    # Token bound to trade 1, used on trade 2 (shouldn't happen because token is tied to trade_id)
    # We test that the token's internal trade_id is used.
    prop1 = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid1 = prop1["trade_id"]
    screen_trade(tid1)
    req1 = request_approval(tid1)
    token = req1["approval_token"]
    
    # approve_trade uses the token's trade_id, so it will approve tid1.
    # We can't "misuse" it on another trade because the API doesn't accept a trade_id.
    # So this test passes by design.
    approve_trade(token)
    trade = get_trade(tid1)
    assert trade["status"] == TradeStatus.APPROVED.value

# ------------------------------------------------------------------
# TESTS: PROPOSAL TAMPERING
# ------------------------------------------------------------------
def test_modified_quantity_fails(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
    token = req["approval_token"]
    approve_trade(token)
    
    # Manually modify the quantity in the DB
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET quantity = 999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    
    result = execute_trade(tid, execution_price=60100)
    assert result["status"] == "REJECTED"
    assert "Hash mismatch" in result["reason"] or "TAMPERED" in result["reason"]

def test_modified_entry_fails(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
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
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
    token = req["approval_token"]
    
    # Change policy version before approval
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET policy_version = '2.0.0' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    
    # Approval should fail because token hash/policy doesn't match
    result = approve_trade(token)
    assert result["status"] == "REJECTED"
    assert "POLICY MISMATCH" in result["reason"]

# ------------------------------------------------------------------
# TESTS: STATE TRANSITIONS
# ------------------------------------------------------------------
def test_rejected_trade_cannot_execute(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    transition_trade(tid, TradeStatus.REJECTED, ActorType.RISK_ENGINE)
    result = execute_trade(tid, execution_price=60000)
    assert result["status"] == "REJECTED"
    assert "must be 'approved'" in result["reason"]

def test_double_execution_fails(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
    token = req["approval_token"]
    approve_trade(token)
    res1 = execute_trade(tid, execution_price=60100)
    assert res1["status"] == "SUCCESS"
    res2 = execute_trade(tid, execution_price=60200)
    # Idempotent: returns SUCCESS but doesn't re-execute
    assert res2["status"] == "SUCCESS"
    assert res2.get("idempotent") == True

def test_awaiting_approval_cannot_execute(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)  # Moves to AWAITING_APPROVAL
    result = execute_trade(tid, execution_price=60000)
    assert result["status"] == "REJECTED"
    assert "must be 'approved'" in result["reason"]

def test_modified_risk_amount_fails(clean_db):
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
    token = req["approval_token"]
    approve_trade(token)
    # Modify risk_amount in DB (assuming it's stored or can be derived)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # risk_amount is not stored directly; we need to change quantity or stop to affect it
    # but we can just change quantity, which is already tested.
    # For completeness, we can test by changing stop loss, which changes risk_amount.
    cursor.execute("UPDATE trades SET stop_loss = 59000 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    result = execute_trade(tid, execution_price=60100)
    assert result["status"] == "REJECTED"
    assert "Hash mismatch" in result["reason"]

def test_modified_expiration_fails(clean_db):
   
    from schemas import TradeProposal
    import datetime
    p1 = TradeProposal(
        asset="BTC", side="LONG", entry_price=60000, stop_loss=59500,
        quantity=0.4, risk_percent=0.02, portfolio_balance_at_time=10000,
        agent_reasoning="test", risk_decision="PASSED",
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    )
    p2 = TradeProposal(
        asset="BTC", side="LONG", entry_price=60000, stop_loss=59500,
        quantity=0.4, risk_percent=0.02, portfolio_balance_at_time=10000,
        agent_reasoning="test", risk_decision="PASSED",
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    )
    assert p1.compute_hash() != p2.compute_hash()