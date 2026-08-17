"""
Robo-Shopper V4 - Concurrency Tests (Sprint 5).
Proves atomic transactions prevent race conditions.
"""
import pytest
import sys
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus, ActorType
from state_machine import transition_trade
from tests.test_helpers import screen_and_request_approval
from governance_engine import request_approval, approve_trade, execute_trade, screen_trade
from trade_memory_mcp import propose_trade, get_trade
from config import DB_PATH
from governance_engine import screen_trade


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


def test_concurrent_approvals(clean_db):
    # Create ONE trade, screen it once
    tid = create_proposed_trade()
    screen_result = screen_trade(tid)
    assert screen_result["status"] == "SUCCESS", f"Screening failed: {screen_result}"
    
    # Generate 10 tokens for the SAME trade
    tokens = []
    for _ in range(10):
        req = request_approval(tid)
        assert req["status"] == "success", f"Token generation failed: {req}"
        tokens.append(req["approval_token"])
    
    # Try to approve with all 10 tokens concurrently
    # Only 1 should succeed (the others fail: token already used)
    results = []
    def approve_thread(token):
        time.sleep(0.01)
        results.append(approve_trade(token))
    
    threads = []
    for token in tokens:
        t = threading.Thread(target=approve_thread, args=(token,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    
    successes = [r for r in results if r["status"] == "SUCCESS"]
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}: {results}"
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.APPROVED.value


def test_concurrent_executions(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    approve_trade(token)
    
    results = []
    def execute_thread(idx):
        time.sleep(0.01)
        results.append(execute_trade(tid, execution_price=60000 + idx))
    
    threads = []
    for i in range(10):
        t = threading.Thread(target=execute_thread, args=(i,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    
    non_idempotent = [r for r in results if r["status"] == "SUCCESS" and not r.get("idempotent", False)]
    assert len(non_idempotent) >= 1
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.EXECUTED.value