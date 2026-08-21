#!/usr/bin/env python3
"""
Live demo: Propose → Screen → Approve → Execute
Shows the complete governance pipeline in action.
"""
import sys
sys.path.insert(0, '.')

from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade, request_approval, approve_trade, execute_trade
from schemas import TradeStatus

print("=" * 60)
print("ROBO-SHOPPER GOVERNANCE DEMO")
print("=" * 60)

# Step 1: Propose a trade
print("\n[1/5] Proposing trade...")
prop = propose_trade(
    symbol="BTC",
    side="long",
    quantity=0.01,
    entry_price=60000,
    stop_loss=59500,
    portfolio_balance=10000.0
)
trade_id = prop["trade_id"]
print(f"✅ Trade {trade_id} created in PROPOSED state")

# Check trade state after proposal
trade = get_trade(trade_id)
print(f"   Current status: {trade['status']}")

# Step 2: Screen the trade (runs risk/exposure/breaker checks)
print("\n[2/5] Screening trade...")
screen_result = screen_trade(trade_id)
print(f"✅ Screen result: {screen_result['status']}")

if screen_result['status'] == 'SUCCESS':
    print("   Passed: risk engine + exposure + circuit breaker")
    
    # Check trade state after screening
    trade = get_trade(trade_id)
    print(f"   Status after screening: {trade['status']}")
else:
    print(f"   Screen failed: {screen_result}")
    sys.exit(1)

# Step 3: Request approval token
print("\n[3/5] Requesting approval token...")
req_result = request_approval(trade_id)

if req_result.get('status') == 'success':
    print(f"✅ Token generated")
    token = req_result['approval_token']
    print(f"   Token: {token[:20]}...{token[-10:]}")
else:
    print(f"❌ Token generation failed: {req_result}")
    print(f"   Trade state: {get_trade(trade_id)}")
    sys.exit(1)

# Step 4: Human approves with token
print("\n[4/5] Human approving trade with token...")
approve_result = approve_trade(token)

if approve_result.get('status') == 'SUCCESS':
    print(f"✅ Approval successful")
    print(f"   New status: {approve_result.get('new_status')}")
else:
    print(f"❌ Approval failed: {approve_result}")
    sys.exit(1)

# Step 5: Execute the trade
print("\n[5/5] Executing trade...")
exec_result = execute_trade(trade_id, execution_price=60100)

if exec_result.get('status') == 'SUCCESS':
    print(f"✅ Execution successful")
    print(f"   New status: {exec_result.get('new_status')}")
    print(f"   Idempotent: {exec_result.get('idempotent', False)}")
else:
    print(f"❌ Execution failed: {exec_result}")
    sys.exit(1)

print("\n" + "=" * 60)
print("DEMO COMPLETE - Full governance pipeline executed successfully!")
print("=" * 60)
