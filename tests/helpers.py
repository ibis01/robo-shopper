"""
Shared test helpers for Robo-Shopper governance tests.
"""
import sqlite3
from config import DB_PATH
from schemas import TradeStatus
from trade_memory_mcp import propose_trade, get_trade

def create_awaiting_trade(symbol="BTC", side="long", quantity=0.4, entry=60000, stop=59500):
    """Propose a trade and set status to AWAITING_APPROVAL via SQL."""
    prop = propose_trade(symbol, side, quantity, entry, stop, reasoning="test")
    tid = prop["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET status = ? WHERE id = ?", (TradeStatus.AWAITING_APPROVAL.value, tid))
    conn.commit()
    conn.close()
    # Verify it's now AWAITING_APPROVAL
    trade = get_trade(tid)
    assert trade["status"] == TradeStatus.AWAITING_APPROVAL.value
    return tid