import pytest
import sqlite3
from config import DB_PATH
from schemas import TradeStatus, ActorType
from state_machine import transition_trade
from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade, request_approval, approve_trade, execute_trade

# ------------------------------------------------------------------
# HELPER: Create a trade directly in AWAITING_APPROVAL (bypass state machine)
# ------------------------------------------------------------------
def create_awaiting_trade(symbol="BTC", side="long", quantity=0.01, entry=60000, stop=59500):
    """Propose a trade and set status to AWAITING_APPROVAL via SQL (bypass state machine)."""
    prop = propose_trade(symbol, side, quantity, entry, stop, reasoning="test")
    tid = prop["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.execute("UPDATE trades SET status = 'awaiting_approval' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    return tid

# ------------------------------------------------------------------
# FIXTURE
# ------------------------------------------------------------------
@pytest.fixture
def clean_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM approval_tokens")
    cursor.execute("DELETE FROM trade_events")
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM approval_tokens")
    cursor.execute("DELETE FROM trade_events")
    conn.commit()
    conn.close()

# ------------------------------------------------------------------
# TESTS
# ------------------------------------------------------------------
def test_audit_event_created_on_successful_transition(clean_db):
    """Ensure every successful state transition creates exactly one audit event."""
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()

    screen_trade(tid)  # performs two transitions: PROPOSED→RISK_CHECKED→AWAITING_APPROVAL
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert count == 2, "Screening should create two audit events (two transitions)"

    request_approval(tid)  # does not change state
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert count == 2, "request_approval should not create an event"

    req = request_approval(tid)  # reuse token
    token = req["approval_token"]
    approve_trade(token)
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert count == 3, "Approval should create third event"

    execute_trade(tid, execution_price=60100)
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert count == 4, "Execution should create fourth event"

    # Rejection path
    prop2 = propose_trade("ETH", "short", 0.5, 3000, 3100, reasoning="reject_test")
    tid2 = prop2["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid2,))
    conn.commit()
    conn.close()
    screen_trade(tid2)
    conn = sqlite3.connect(DB_PATH)
    count2 = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid2,)).fetchone()[0]
    conn.close()
    assert count2 == 2, "Screening should create two events"
    request_approval(tid2)
    from governance_engine import dashboard_reject_trade
    dashboard_reject_trade(tid2)  # AWAITING_APPROVAL → REJECTED
    conn = sqlite3.connect(DB_PATH)
    count2 = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid2,)).fetchone()[0]
    conn.close()
    assert count2 == 3, "Rejection should create third event"

def test_audit_failure_rolls_back_state(clean_db, monkeypatch):
    """Simulate audit insertion failure -> state change must be rolled back."""
    from state_machine import _log_event
    def failing_log(*args, **kwargs):
        raise RuntimeError("Simulated audit failure")
    monkeypatch.setattr("state_machine._log_event", failing_log)

    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()

    # Attempt to transition PROPOSED → RISK_CHECKED (first step of screening)
    result = transition_trade(tid, TradeStatus.RISK_CHECKED, ActorType.RISK_ENGINE, {})
    assert result["status"] == "ERROR", "Audit failure should cause transaction rollback"
    # State must remain PROPOSED
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.PROPOSED.value, "State should not change on audit failure"
    # No audit event should exist
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert count == 0, "No audit event should exist"

def test_approve_trade_creates_audit_event(clean_db):
    """Approve_trade must create an audit event via transition_trade."""
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    tid = prop["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()

    screen_trade(tid)  # two transitions
    req = request_approval(tid)
    token = req["approval_token"]
    approve_trade(token)

    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    # Screening: 2 events (PROPOSED→RISK_CHECKED, RISK_CHECKED→AWAITING_APPROVAL)
    # Approval: 1 event (AWAITING_APPROVAL→APPROVED)
    assert count == 3, f"Expected 3 events, got {count}"

def test_audit_failure_rolls_back_external_connection(clean_db, monkeypatch):
    """Simulate audit failure on an external connection – the whole transaction rolls back."""
    from state_machine import _log_event
    def failing_log(*args, **kwargs):
        raise RuntimeError("Simulated audit failure")
    monkeypatch.setattr("state_machine._log_event", failing_log)

    # Use helper to bypass state machine so we don't trigger audit failure during screening
    tid = create_awaiting_trade()

    req = request_approval(tid)  # mints token (no state change)
    assert req["status"] == "success"
    token = req["approval_token"]

    # This will call transition_trade with an external connection.
    # The audit failure should roll back the approval transition.
    result = approve_trade(token)
    assert result["status"] == "ERROR", "Audit failure should cause error"
    # Trade should still be AWAITING_APPROVAL (not APPROVED)
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.AWAITING_APPROVAL.value, "State should not change on audit failure"
    # No audit event for the approval attempt
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert count == 0, "No audit events should exist (we bypassed screening)"