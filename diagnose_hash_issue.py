#!/usr/bin/env python3
"""
Diagnostic script to identify the execute_trade rejection issue.
"""
import sqlite3
from config import DB_PATH
import trade_memory_mcp
from governance_engine import screen_trade, request_approval, approve_trade, execute_trade, _read_trade_from_db

# Clean slate
conn = sqlite3.connect(DB_PATH)
conn.execute("DELETE FROM trades")
conn.execute("DELETE FROM approval_tokens")
conn.commit()
conn.close()

# Create a trade
print("=== Creating trade ===")
prop_result = trade_memory_mcp.propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="test")
trade_id = prop_result["trade_id"]
print(f"Trade ID: {trade_id}")

# Screen and request approval
print("\n=== Screening and requesting approval ===")
screen_result = screen_trade(trade_id)
print(f"Screen result: {screen_result}")

approval_result = request_approval(trade_id)
print(f"Approval result status: {approval_result['status']}")

# Approve the trade
print("\n=== Approving trade ===")
approve_result = approve_trade(approval_result["approval_token"])
print(f"Approve result: {approve_result}")

# Check state after approval
trade_after_approve = _read_trade_from_db(trade_id)
print(f"Status in DB after approve: {trade_after_approve['status']}")

# Now try to execute
print("\n=== Executing trade ===")
execute_result = execute_trade(trade_id, execution_price=60100)
print(f"Execute result: {execute_result}")

# Check state after execution attempt
trade_after_exec = _read_trade_from_db(trade_id)
print(f"Status in DB after execute attempt: {trade_after_exec['status']}")