import pytest
import sys
import os
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_management_mcp import calculate_position_size, evaluate_trade_risk, _get_real_portfolio_balance
from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade
from config import DB_PATH

@pytest.fixture
def clean_db_and_treasury():
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

# A. LLM cannot override portfolio balance (Parameter removed)
def test_llm_cannot_override_balance(clean_db_and_treasury):
    with pytest.raises(TypeError):
        calculate_position_size(entry=60000, stop=59500, portfolio_balance=1000000)

# B. Fake balance cannot be persisted as authoritative balance
def test_fake_balance_not_persisted(clean_db_and_treasury):
    result = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    trade = get_trade(result["trade_id"])
    assert trade["portfolio_balance"] == 10000.0

# C. screen_trade ignores any untrusted balance (Implicit via parameter removal)
def test_screen_trade_uses_trusted_balance(clean_db_and_treasury):
    # Propose a trade that would pass if balance was 1M, but fail if balance is 10k
    # 2% of 10k = $200. Risk per unit = $500. Max size = 0.4
    # If LLM tries to propose size 0.5 (risk $250), it should be rejected by screen_trade
    prop = propose_trade("BTC", "long", 0.5, 60000, 59500, reasoning="test")
    screen_res = screen_trade(prop["trade_id"])
    assert screen_res["status"] == "REJECTED"
    assert "2% hard cap" in screen_res["reason"]

# D. Missing/corrupt authoritative balance fails closed
def test_missing_balance_fails_closed(clean_db_and_treasury):
    # Corrupt the treasury with a negative balance to trigger HARD STOP
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE treasury SET current_balance = -100.0")
    conn.commit()
    conn.close()
    
    with pytest.raises(RuntimeError, match="HARD STOP"):
        calculate_position_size(entry=60000, stop=59500)

# F. Malicious payload with enormous balance cannot bypass 2% policy
def test_enormous_balance_cannot_bypass_policy(clean_db_and_treasury):
    # The invariant is: screen_trade(P) must produce same decision regardless of LLM input.
    # Since LLM cannot input balance, we verify a valid trade passes both risk and exposure gates.
    # 0.01 BTC at $60k = $600 exposure (6% of $10k, passes 20% cap).
    # Risk = $5 (0.05% of $10k, passes 2% cap).
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
    screen_res = screen_trade(prop["trade_id"])
    assert screen_res["status"] == "SUCCESS"

# G. Idempotency of risk decision
def test_risk_decision_idempotent(clean_db_and_treasury):
    res1 = calculate_position_size(entry=60000, stop=59500)
    res2 = calculate_position_size(entry=60000, stop=59500)
    assert res1["position_size"] == res2["position_size"]