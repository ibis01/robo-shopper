import pytest
import sys
import os
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus
from governance_engine import (
    screen_trade, request_approval, dashboard_approve_trade, 
    dashboard_reject_trade, generate_execution_command
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

def create_screened_trade():
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (prop["trade_id"],))
    conn.commit()
    conn.close()
    screen_trade(prop["trade_id"])
    return prop["trade_id"]

# 1. APPROVED cannot be rejected
def test_approved_cannot_be_rejected(clean_db):
    tid = create_screened_trade()
    request_approval(tid)
    dashboard_approve_trade(tid) # Moves to APPROVED
    
    res = dashboard_reject_trade(tid)
    assert res["status"] == "ERROR"
    assert "must be awaiting_approval" in res["reason"]

# 2. EXECUTED cannot be rejected (Simulate execution state)
def test_executed_cannot_be_rejected(clean_db):
    tid = create_screened_trade()
    request_approval(tid)
    dashboard_approve_trade(tid)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET status = 'executed' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    
    res = dashboard_reject_trade(tid)
    assert res["status"] == "ERROR"

# 3. REJECTED cannot be approved
def test_rejected_cannot_be_approved(clean_db):
    tid = create_screened_trade()
    dashboard_reject_trade(tid) # Moves to REJECTED
    
    res = dashboard_approve_trade(tid)
    assert res["status"] == "ERROR"
    assert "must be awaiting_approval" in res["reason"]

# 4. REJECTED cannot execute
def test_rejected_cannot_execute(clean_db):
    tid = create_screened_trade()
    dashboard_reject_trade(tid)
    
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"