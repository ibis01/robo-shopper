# test_http_bridge.py
import requests
import time
import sqlite3
from config import DB_PATH
from trade_memory_mcp import propose_trade
from governance_engine import screen_trade, request_approval

BASE_URL = "http://localhost:8003"

def run_integration():
    print("--- 1. Creating and screening a trade ---")
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="http_test")
    tid = prop["trade_id"]
    
    # Set balance for exposure check
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()

    screen_trade(tid)
    request_approval(tid) # Mints the token server-side
    print(f"Trade {tid} is now AWAITING_APPROVAL")

    print("\n--- 2. Testing POST /api/approve/{id} ---")
    res = requests.post(f"{BASE_URL}/api/approve/{tid}")
    print(f"Status: {res.status_code} | Body: {res.json()}")
    assert res.json().get("status") == "success", "Approval failed!"

    print("\n--- 3. Verifying Database State ---")
    conn = sqlite3.connect(DB_PATH)
    status = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    used_at = conn.execute("SELECT used_at FROM approval_tokens WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    print(f"Trade Status: {status} (Expected: approved)")
    print(f"Token used_at: {used_at} (Expected: not null)")
    assert status == "approved"
    assert used_at is not None

    print("\n--- 4. Testing Replay Protection (Second Approval) ---")
    res2 = requests.post(f"{BASE_URL}/api/approve/{tid}")
    print(f"Status: {res2.status_code} | Body: {res2.json()}")
    assert res2.json().get("status") == "error", "Replay protection failed!"

    print("\n--- 5. Testing Execution Gateway ---")
    # Note: format_onchainos_command is an MCP tool, but we can test the underlying function
    from governance_engine import generate_execution_command
    cmd_res = generate_execution_command(tid)
    print(f"Execution Gateway: {cmd_res['status']} | Command: {cmd_res.get('command')}")
    assert cmd_res["status"] == "SUCCESS"

    print("\n✅ ALL INTEGRATION CHECKS PASSED.")

if __name__ == "__main__":
    # Wait for dashboard to be ready
    for _ in range(10):
        try:
            requests.get(BASE_URL)
            break
        except:
            time.sleep(1)
    run_integration()