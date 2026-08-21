import pytest
import sys
import os
import sqlite3
import inspect
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus, ActorType
from state_machine import transition_trade
from governance_engine import (
    screen_trade, request_approval, approve_trade, 
    dashboard_approve_trade, dashboard_reject_trade, 
    generate_execution_command
)
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

def create_screened_and_requested_trade():
    """Helper: propose -> screen -> request_approval (mints token)"""
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    # Ensure portfolio balance is set for exposure checks
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (prop["trade_id"],))
    conn.commit()
    conn.close()
    
    screen_res = screen_trade(prop["trade_id"])
    assert screen_res["status"] == "SUCCESS", f"Screening failed: {screen_res}"
    
    req = request_approval(prop["trade_id"])
    assert req["status"] == "success", f"Request approval failed: {req}"
    
    return prop["trade_id"]

# 1. screened trade -> request_approval -> awaiting_approval
def test_screened_to_awaiting(clean_db):
    tid = create_screened_and_requested_trade()
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.AWAITING_APPROVAL.value

# 2. dashboard approve -> cryptographic governance -> APPROVED
def test_dashboard_approve(clean_db):
    tid = create_screened_and_requested_trade()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "SUCCESS"
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.APPROVED.value

# 3. dashboard reject -> REJECTED
def test_dashboard_reject(clean_db):
    tid = create_screened_and_requested_trade()
    res = dashboard_reject_trade(tid)
    assert res["status"] == "SUCCESS"
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.REJECTED.value

# 4. invalid trade_id -> failure
def test_invalid_trade_id(clean_db):
    res = dashboard_approve_trade(999999)
    assert res["status"] == "ERROR"
    res = dashboard_reject_trade(999999)
    assert res["status"] == "ERROR"

# 5. already approved -> failure
def test_already_approved(clean_db):
    tid = create_screened_and_requested_trade()
    dashboard_approve_trade(tid)
    res = dashboard_approve_trade(tid)
    assert res["status"] != "SUCCESS"

# 6. expired authorization -> failure
def test_expired_authorization(clean_db):
    tid = create_screened_and_requested_trade()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE approval_tokens SET expires_at = ? WHERE trade_id = ?", 
                 ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), tid))
    conn.commit()
    conn.close()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "REJECTED"

# 7. replay -> failure
def test_replay(clean_db):
    tid = create_screened_and_requested_trade()
    dashboard_approve_trade(tid)
    res = dashboard_approve_trade(tid)
    assert res["status"] != "SUCCESS"

# 8. modified proposal -> hash failure
def test_modified_proposal(clean_db):
    tid = create_screened_and_requested_trade()
    dashboard_approve_trade(tid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET quantity = 999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"
    assert "Hash mismatch" in res["reason"] or "TAMPERED" in res["reason"]

# 9. policy mismatch -> failure
def test_policy_mismatch(clean_db):
    tid = create_screened_and_requested_trade()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET policy_version = 'tampered' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "REJECTED"

# 10. approved trade -> execution gateway works
def test_approved_execution(clean_db):
    tid = create_screened_and_requested_trade()
    dashboard_approve_trade(tid)
    res = generate_execution_command(tid)
    assert res["status"] == "SUCCESS"

# 11. awaiting_approval -> execution gateway rejects
def test_awaiting_execution_rejects(clean_db):
    tid = create_screened_and_requested_trade()
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"

# 12. rejected -> execution gateway rejects
def test_rejected_execution_rejects(clean_db):
    tid = create_screened_and_requested_trade()
    dashboard_reject_trade(tid)
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"

# 13. browser cannot supply arbitrary trade parameters
def test_browser_no_arbitrary_params(clean_db):
    sig = inspect.signature(dashboard_approve_trade)
    assert "trade_id" in sig.parameters
    assert "symbol" not in sig.parameters
    assert "quantity" not in sig.parameters

# 14. browser cannot supply arbitrary portfolio balance
def test_browser_no_arbitrary_balance(clean_db):
    sig = inspect.signature(dashboard_approve_trade)
    assert "portfolio_balance" not in sig.parameters

# 15. approve endpoint cannot directly mutate status
def test_no_direct_mutation(clean_db):
    tid = create_screened_and_requested_trade()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM approval_tokens WHERE trade_id = ?", (tid,))
    conn.commit()
    conn.close()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "ERROR"
    trade = get_trade(tid)
    assert trade["status"] != TradeStatus.APPROVED.value