# test_e2e_bridge.py
import requests
import time
import sqlite3
from config import DB_PATH
from trade_memory_mcp import propose_trade
from governance_engine import screen_trade, request_approval, generate_execution_command

BASE_URL = "http://localhost:8003"

def run_e2e_test():
    print("=== 1. CREATING AND SCREENING TRADE ===")
    # FIX: Reduced quantity from 2.0 to 0.5 to pass the 20% exposure cap 
    # (0.5 ETH * $3000 = $1500 exposure, which is 15% of the $10k portfolio)
    prop = propose_trade("ETH", "long", 0.5, 3000, 2900, reasoning="e2e_test")
    tid = prop["trade_id"]
    
    # Set balance for exposure check
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()

    screen_res = screen_trade(tid)
    print(f"Screening Result: {screen_res['status']}")
    assert screen_res["status"] == "SUCCESS", f"Screening failed: {screen_res}"

    req_res = request_approval(tid) # Mints the token server-side
    print(f"Request Approval Result: {req_res['status']}")
    assert req_res["status"] == "success", f"Request approval failed: {req_res}"
    
    print(f"Trade {tid} is now AWAITING_APPROVAL")

    print("\n=== 2. TESTING POST /api/approve/{id} ===")
    res = requests.post(f"{BASE_URL}/api/approve/{tid}")
    print(f"HTTP Status: {res.status_code} | Body: {res.json()}")
    assert res.json().get("status") == "success", "Approval failed!"

    print("\n=== 3. VERIFYING DATABASE STATE ===")
    conn = sqlite3.connect(DB_PATH)
    status = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    used_at = conn.execute("SELECT used_at FROM approval_tokens WHERE trade_id = ?", (tid,)).fetchone()[0]
    conn.close()
    print(f"Trade DB Status: {status} (Expected: approved)")
    print(f"Token used_at: {used_at} (Expected: not null)")
    assert status == "approved"
    assert used_at is not None

    print("\n=== 4. TESTING REPLAY PROTECTION ===")
    res2 = requests.post(f"{BASE_URL}/api/approve/{tid}")
    print(f"HTTP Status: {res2.status_code} | Body: {res2.json()}")
    assert res2.json().get("status") == "error", "Replay protection failed!"

    print("\n=== 5. TESTING EXECUTION GATEWAY ===")
    cmd_res = generate_execution_command(tid)
    print(f"Gateway Status: {cmd_res['status']} | Command: {cmd_res.get('command')}")
    assert cmd_res["status"] == "SUCCESS"

    print("\n=== 6. TESTING REJECTION FLOW ===")
    prop2 = propose_trade("SOL", "long", 10.0, 150, 140, reasoning="e2e_reject")
    tid2 = prop2["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid2,))
    conn.commit()
    conn.close()
    
    screen_trade(tid2)
    request_approval(tid2)
    
    res3 = requests.post(f"{BASE_URL}/api/reject/{tid2}")
    print(f"Reject HTTP Status: {res3.status_code} | Body: {res3.json()}")
    assert res3.json().get("status") == "success"
    
    # Verify execution gateway rejects rejected trade
    cmd_res2 = generate_execution_command(tid2)
    print(f"Gateway on Rejected Trade: {cmd_res2['status']}")
    assert cmd_res2["status"] == "REJECTED"

    print("\n✅ ALL E2E INTEGRATION CHECKS PASSED.")

if __name__ == "__main__":
    for _ in range(10):
        try:
            requests.get(BASE_URL)
            break
        except:
            time.sleep(1)
    run_e2e_test()