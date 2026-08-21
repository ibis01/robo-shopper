import pytest
import sys
import os
import sqlite3

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus, ActorType
from state_machine import transition_trade
from tests.test_helpers import screen_and_request_approval
from governance_engine import request_approval, approve_trade, generate_execution_command
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

def create_proposed_trade(symbol="BTC", side="long", quantity=0.01, entry=60000, stop=59500):
    prop = propose_trade(symbol, side, quantity, entry, stop, reasoning="test")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (prop["trade_id"],))
    conn.commit()
    conn.close()
    return prop["trade_id"]

# 1. unapproved trade cannot generate command
def test_unapproved_trade_rejected(clean_db):
    tid = create_proposed_trade()
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"
    # Fix: Match the exact casing of the error message
    assert "Must be 'approved'" in res["reason"] 

# 2. rejected trade cannot generate command
def test_rejected_trade_rejected(clean_db):
    tid = create_proposed_trade()
    transition_trade(tid, TradeStatus.REJECTED, ActorType.RISK_ENGINE)
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"

# 3. modified trade cannot generate command (Hash mismatch)
def test_modified_trade_rejected(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    approve_trade(req["approval_token"])
    
    # Tamper with DB
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET quantity = 999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"
    assert "Hash mismatch" in res["reason"] or "TAMPERED" in res["reason"]

# 4. nonexistent trade cannot generate command
def test_nonexistent_trade_rejected(clean_db):
    res = generate_execution_command(999999)
    assert res["status"] == "ERROR"
    assert "not found" in res["reason"]

# 5. executed trade cannot generate another command
def test_executed_trade_rejected(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    approve_trade(req["approval_token"])
    
    # Execute it
    from governance_engine import execute_trade
    execute_trade(tid, execution_price=60100)
    
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"

# 9. approved trade generates command using canonical DB values
def test_approved_trade_generates_command(clean_db):
    # Fix: Reduced quantity from 2.0 to 0.5 to pass the 20% exposure cap 
    # (0.5 ETH * $3000 = $1500 exposure, which is 15% of the $10k portfolio)
    tid = create_proposed_trade(symbol="ETH", side="long", quantity=0.5, entry=3000, stop=2900)
    req = screen_and_request_approval(tid)
    
    # Ensure screening actually passed before trying to approve
    assert req["status"] == "success", f"Screening failed: {req}" 
    
    approve_trade(req["approval_token"])
    
    res = generate_execution_command(tid)
    assert res["status"] == "SUCCESS"
    # Fix: Update expected command to match the new quantity
    assert res["command"] == "onchainos --dry-run long 0.5 ETH"
    assert res["symbol"] == "ETH"
    assert res["quantity"] == 0.5

# 10. proposal hash mismatch fails closed
def test_hash_mismatch_fails_closed(clean_db):
    tid = create_proposed_trade()
    req = screen_and_request_approval(tid)
    approve_trade(req["approval_token"])
    
    # Corrupt the stored hash
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET proposal_hash = 'tampered_hash' WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    
    res = generate_execution_command(tid)
    assert res["status"] == "REJECTED"
    assert "Hash mismatch" in res["reason"]