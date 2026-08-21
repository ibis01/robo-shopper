import requests
import sqlite3
import time
from config import DB_PATH
from trade_memory_mcp import propose_trade
from governance_engine import screen_trade, request_approval

BASE = "http://localhost:8003"

def run():
    print("=== 1. CREATING & SCREENING TRADE ===")
    prop = propose_trade("ETH", "long", 0.5, 3000, 2900, reasoning="verify_p0")
    tid = prop["trade_id"]
    print(f"Created Trade ID: {tid}")
    
    # Ensure treasury has balance
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO treasury (id, current_balance) VALUES (1, 10000.0)")
    conn.execute("UPDATE treasury SET current_balance = 10000.0 WHERE id = 1")
    conn.commit()
    conn.close()
    
    print("\n--- Running screen_trade ---")
    screen_res = screen_trade(tid)
    print(f"Screen Result: {screen_res}")
    
    if screen_res.get("status") != "SUCCESS":
        print("❌ Screening failed. Stopping.")
        return

    print("\n--- Running request_approval ---")
    req_res = request_approval(tid)
    print(f"Request Result: {req_res}")
    
    if req_res.get("status") != "success":
        print("❌ Approval request failed. Stopping.")
        return

    # Check DB Before
    conn = sqlite3.connect(DB_PATH)
    status_before = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    token_count = conn.execute("SELECT COUNT(*) FROM approval_tokens WHERE trade_id = ?", (tid,)).fetchone()[0]
    print(f"\nDB Status Before HTTP: {status_before}")
    print(f"Tokens in DB for trade {tid}: {token_count}")
    conn.close()

    print("\n=== 2. POST /api/approve/{id} ===")
    res = requests.post(f"{BASE}/api/approve/{tid}", cookies={"robo_auth": "robo-shopper-local-dev"})
    print(f"HTTP Response: {res.json()}")

    print("\n=== 3. VERIFYING DATABASE & TOKEN ===")
    conn = sqlite3.connect(DB_PATH)
    status_after = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    token_row = conn.execute("SELECT used_at FROM approval_tokens WHERE trade_id = ?", (tid,)).fetchone()
    token_used = token_row[0] if token_row else None
    print(f"DB Status After: {status_after}")
    print(f"Token Consumed (used_at): {token_used is not None}")
    conn.close()

    print("\n=== 4. REPLAY PROTECTION ===")
    res2 = requests.post(f"{BASE}/api/approve/{tid}", cookies={"robo_auth": "robo-shopper-local-dev"})
    print(f"Second Attempt Response: {res2.json()}")

if __name__ == "__main__":
    time.sleep(2)
    run()