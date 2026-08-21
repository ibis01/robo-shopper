import pytest
import sys
import os
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus
from governance_engine import screen_trade, dashboard_approve_trade, dashboard_reject_trade, generate_execution_command
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
    
def create_and_screen_trade():
    """Helper to create a trade, screen it, AND mint an approval token."""
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (prop["trade_id"],))
    conn.commit()
    conn.close()
    
    # Screen the trade (moves to AWAITING_APPROVAL)
    screen_res = screen_trade(prop["trade_id"])
    assert screen_res["status"] == "SUCCESS", f"Screening failed: {screen_res}"
    
    # CRITICAL FIX: Mint the approval token (this is what dashboard_approve_trade needs)
    from governance_engine import request_approval
    req = request_approval(prop["trade_id"])
    assert req["status"] == "success", f"Request approval failed: {req}"
    
    return prop["trade_id"]

# 1. pending trade appears in dashboard (simulated via DB query logic)
def test_pending_trade_in_db(clean_db):
    tid = create_and_screen_trade()
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.AWAITING_APPROVAL.value

# 2. approval invokes governance
def test_dashboard_approve_invokes_governance(clean_db):
    tid = create_and_screen_trade()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "SUCCESS"
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.APPROVED.value

# 3. approval cannot directly mutate state (bypasses token validation)
def test_approval_requires_token(clean_db):
    tid = create_and_screen_trade()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM approval_tokens WHERE trade_id = ?", (tid,))
    conn.commit()
    conn.close()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "ERROR"
    assert "No active approval token" in res["reason"]

# 4. invalid approval fails (expired token)
def test_invalid_approval_fails(clean_db):
    tid = create_and_screen_trade()
    from datetime import datetime, timedelta, timezone
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE approval_tokens SET expires_at = ? WHERE trade_id = ?", 
                 ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), tid))
    conn.commit()
    conn.close()
    res = dashboard_approve_trade(tid)
    assert res["status"] == "REJECTED"

# 8. rejection works
def test_dashboard_reject_works(clean_db):
    tid = create_and_screen_trade()
    res = dashboard_reject_trade(tid)
    assert res["status"] == "SUCCESS"
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.REJECTED.value

# 9. rejected trade cannot generate execution command
def test_rejected_trade_no_execution(clean_db):
    tid = create_and_screen_trade()
    dashboard_reject_trade(tid)
    cmd_res = generate_execution_command(tid)
    assert cmd_res["status"] == "REJECTED"

# 10. approved trade can generate execution command
def test_approved_trade_can_execute(clean_db):
    tid = create_and_screen_trade()
    dashboard_approve_trade(tid)
    cmd_res = generate_execution_command(tid)
    assert cmd_res["status"] == "SUCCESS"
    assert "onchainos --dry-run" in cmd_res["command"]

# 11. arbitrary trade parameters from UI are ignored
def test_ui_ignores_arbitrary_params(clean_db):
    import inspect
    from governance_engine import dashboard_approve_trade
    sig = inspect.signature(dashboard_approve_trade)
    assert "trade_id" in sig.parameters
    assert "symbol" not in sig.parameters