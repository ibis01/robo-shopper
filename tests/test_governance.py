"""
Robo-Shopper V4 - Governance Integration Test (Sprint 5).
Full end-to-end pipeline.
"""
import pytest
import sys
import os
import sqlite3
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import TradeStatus, ActorType
from state_machine import transition_trade
from governance_engine import request_approval, approve_trade, execute_trade
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


def create_proposed_trade(symbol="BTC", side="long", quantity=0.4, entry=60000, stop=59500):
    prop = propose_trade(symbol, side, quantity, entry, stop, reasoning="test")
    return prop["trade_id"]


def test_full_governance_pipeline(clean_db):
    tid = create_proposed_trade()
    req = request_approval(tid)
    assert req["status"] == "success"
    token = req["approval_token"]
    
    approve_result = approve_trade(token)
    assert approve_result["status"] == "SUCCESS"
    assert approve_result["new_status"] == TradeStatus.APPROVED.value
    
    exec_result = execute_trade(tid, execution_price=60100)
    assert exec_result["status"] == "SUCCESS"
    assert exec_result["new_status"] == TradeStatus.EXECUTED.value
    
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.EXECUTED.value
    assert trade["execution_price"] == 60100.0