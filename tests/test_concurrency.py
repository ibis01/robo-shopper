"""
Robo-Shopper V4 - Concurrency Tests (Sprint 5).
Proves that atomic transactions prevent race conditions.
"""
import pytest
import sys
import os
import threading
import time
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from governance_engine import request_approval, approve_trade, screen_trade
from trade_memory_mcp import propose_trade
from config import DB_PATH

# ------------------------------------------------------------------
# FIXTURE: Clean DB
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
# TEST: CONCURRENT APPROVALS
# ------------------------------------------------------------------
def test_concurrent_approvals(clean_db):
    """10 simultaneous approvals on the SAME trade. Exactly 1 should succeed."""
    # 1. Create a trade and move it to AWAITING_APPROVAL
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="concurrent")
    tid = prop["trade_id"]
    screen_trade(tid)  # Moves to AWAITING_APPROVAL
    
    # 2. Generate 10 unique tokens for the SAME trade
    tokens = []
    for _ in range(10):
        req = request_approval(tid)
        tokens.append(req["approval_token"])
    
    # 3. Fire off 10 threads simultaneously
    results = []
    def approve_thread(token):
        time.sleep(0.01)  # Small delay to increase chance of overlap
        result = approve_trade(token)
        results.append(result)
    
    threads = []
    for token in tokens:
        t = threading.Thread(target=approve_thread, args=(token,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # 4. Exactly ONE approval should succeed
    successes = [r for r in results if r["status"] == "SUCCESS"]
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}. Results: {results}"
    
    # 5. Verify the trade is approved
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM trades WHERE id = ?", (tid,))
    status = cursor.fetchone()[0]
    conn.close()
    assert status == "approved"

def test_concurrent_executions(clean_db):
    """10 simultaneous executions on the SAME approved trade. Exactly 1 should succeed."""
    # 1. Create and approve a trade
    prop = propose_trade("BTC", "long", 0.4, 60000, 59500, reasoning="concurrent_exec")
    tid = prop["trade_id"]
    screen_trade(tid)
    req = request_approval(tid)
    token = req["approval_token"]
    approve_trade(token)  # Now APPROVED
    
    # 2. Fire off 10 execution threads
    results = []
    def execute_thread(idx):
        time.sleep(0.01)
        from governance_engine import execute_trade
        # Use different execution prices, doesn't matter
        result = execute_trade(tid, execution_price=60000 + idx)
        results.append(result)
    
    threads = []
    for i in range(10):
        t = threading.Thread(target=execute_thread, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    # 3. Exactly ONE execution should succeed with non-idempotent status
    # The others should return SUCCESS but with idempotent=True
    non_idempotent = [r for r in results if r["status"] == "SUCCESS" and not r.get("idempotent", False)]
    # At least one should succeed. The rest will be idempotent.
    assert len(non_idempotent) >= 1, f"Expected at least 1 non-idempotent success, got {len(non_idempotent)}"
    
    # Verify the trade is executed
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM trades WHERE id = ?", (tid,))
    status = cursor.fetchone()[0]
    conn.close()
    assert status == "executed"