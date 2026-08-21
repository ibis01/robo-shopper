import requests
import sqlite3
import time
from config import DB_PATH
from trade_memory_mcp import propose_trade
from governance_engine import screen_trade, request_approval

BASE = "http://localhost:8003"
API_KEY = "robo-shopper-local-dev"

def run():
    # 1. Setup Trade
    print("=== 1. CREATING & SCREENING TRADE ===")
    prop = propose_trade("ETH", "long", 0.5, 3000, 2900, reasoning="verify_p0")
    tid = prop["trade_id"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET portfolio_balance = 10000.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    
    screen_trade(tid)
    request_approval(tid)
    
    # Check DB Before
    conn = sqlite3.connect(DB_PATH)
    status_before = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    print(f"DB Status Before: {status_before}")
    conn.close()

    # 2. HTTP Approve
    print("\n=== 2. POST /api/approve/{id} ===")
    res = requests.post(f"{BASE}/api/approve/{tid}", cookies={"robo_auth": API_KEY})
    print(f"HTTP Response: {res.json()}")

    # 3. Check DB After
    print("\n=== 3. VERIFYING DATABASE & TOKEN ===")
    conn = sqlite3.connect(DB_PATH)
    status_after = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    token_used = conn.execute("SELECT used_at FROM approval_tokens WHERE trade_id = ?", (tid,)).fetchone()[0]
    print(f"DB Status After: {status_after}")
    print(f"Token Consumed (used_at): {token_used is not None}")
    conn.close()

    # 4. Replay Protection
    print("\n=== 4. REPLAY PROTECTION ===")
    res2 = requests.post(f"{BASE}/api/approve/{tid}", cookies={"robo_auth": API_KEY})
    print(f"Second Attempt Response: {res2.json()}")

if __name__ == "__main__":
    time.sleep(2) # Wait for dashboard
    run()