import pytest
import sys
import os
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade
from config import DB_PATH

@pytest.fixture
def clean_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM approval_tokens")
    cursor.execute("DELETE FROM treasury")
    cursor.execute("INSERT INTO treasury (current_balance) VALUES (10000.0)")
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM treasury")
    conn.commit()
    conn.close()

def test_propose_trade_accepts_any_valid_input(clean_db):
    result = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    assert result["status"] == "success"
    assert result["trade_id"] > 0

def test_screen_trade_rejects_high_risk_proposals(clean_db):
    # 0.5 BTC with $500 stop distance = $250 risk. 2% of 10k = $200. Should reject.
    result = propose_trade("BTC", "long", 0.5, 60000, 59500, reasoning="test")
    screen_res = screen_trade(result["trade_id"])
    assert screen_res["status"] == "REJECTED"

def test_risk_amount_calculation_is_deterministic(clean_db):
    result1 = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    trade1 = get_trade(result1["trade_id"])
    
    result2 = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    trade2 = get_trade(result2["trade_id"])
    
    assert trade1["risk_amount"] == trade2["risk_amount"]
    assert trade1["risk_percent"] == trade2["risk_percent"]

def test_propose_trade_always_sets_status_proposed(clean_db):
    result = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    trade = get_trade(result["trade_id"])
    assert trade["status"] == "proposed"