#!/usr/bin/env python3
"""
Live integration test for Robo-Shopper.
Assumes all services are running (dashboard on 8003, MCP server accessible).
"""
import requests
import sqlite3
import time
import sys
from config import DB_PATH
from trade_memory_mcp import propose_trade
from governance_engine import screen_trade, request_approval, generate_execution_command

BASE_URL = "http://localhost:8003"
session = requests.Session()

def check_server():
    """Check if the dashboard server is reachable."""
    try:
        resp = requests.get(f"{BASE_URL}/login", timeout=2)
        if resp.status_code == 200:
            return True
    except requests.exceptions.ConnectionError:
        pass
    print("\n❌ Dashboard server is not running!")
    print("   Start it in another terminal:")
    print("   cd ~/robo-shopper && export DEV_MODE=1 && python dashboard.py\n")
    return False

def login():
    print("🔐 Logging in...")
    # Use a fresh session to avoid any stale cookies
    global session
    session = requests.Session()
    resp = session.post(
        f"{BASE_URL}/api/login",
        json={"username": "operator", "password": "operator123"}
    )
    print(f"   Login response: {resp.status_code} {resp.text}")
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    # Verify the session cookie is set
    assert 'session' in session.cookies.get_dict(), "No session cookie set"
    print("✅ Logged in.")

def test_pending_trades():
    print("📋 Fetching pending trades...")
    resp = session.get(f"{BASE_URL}/api/pending_trades")
    print(f"   Response: {resp.status_code} {resp.text[:200]}")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    trades = resp.json()
    print(f"   Found {len(trades)} pending trades.")
    return trades

def test_full_pipeline():
    print("🧪 Running full governance pipeline...")
    # 1. Propose trade
    prop = propose_trade("BTC", "long", 0.01, 60000, 59500, reasoning="integration_test")
    tid = prop["trade_id"]
    print(f"   Trade proposed: {tid}")

    # 2. Screen
    screen_result = screen_trade(tid)
    assert screen_result["status"] == "SUCCESS", f"Screening failed: {screen_result}"
    print("   Screen passed.")

    # 3. Request approval (idempotent)
    req1 = request_approval(tid)
    assert req1["status"] == "success", f"Request failed: {req1}"
    token = req1["approval_token"]
    print(f"   Approval token created: {token[:8]}...")

    # 4. Request approval again (should reuse token)
    req2 = request_approval(tid)
    assert req2["status"] == "success"
    assert req2["approval_token"] == token, "Idempotency failed: different token."
    print("   Idempotency: token reused.")

    # 5. Approve via dashboard API
    time.sleep(1)
    pending = test_pending_trades()
    assert any(t["id"] == tid for t in pending), "Trade not in pending list."

    # 6. Approve
    approve_resp = session.post(f"{BASE_URL}/api/approve/{tid}")
    assert approve_resp.status_code == 200, f"Approval failed: {approve_resp.status_code}"
    approve_data = approve_resp.json()
    assert approve_data["status"] == "SUCCESS", f"Approval returned error: {approve_data}"
    print("   Dashboard approval succeeded.")

    # 7. Verify state
    conn = sqlite3.connect(DB_PATH)
    status = conn.execute("SELECT status FROM trades WHERE id = ?", (tid,)).fetchone()[0]
    conn.close()
    assert status == "approved", f"Trade status is {status}, expected approved."
    print("   Trade status now APPROVED.")

    # 8. Execution gateway
    cmd_res = generate_execution_command(tid)
    assert cmd_res["status"] == "SUCCESS", f"Gateway failed: {cmd_res}"
    assert "onchainos --dry-run" in cmd_res["command"], f"Unexpected command: {cmd_res['command']}"
    print(f"   Execution command: {cmd_res['command']}")

    # 9. Replay protection – approve again should fail
    approve_replay = session.post(f"{BASE_URL}/api/approve/{tid}")
    assert approve_replay.json().get("status") == "REJECTED", "Replay not prevented."
    print("   Replay prevented.")

    # 10. Tamper test – modify quantity and try to execute again
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET quantity = 999.0 WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    cmd_tamper = generate_execution_command(tid)
    assert cmd_tamper["status"] == "REJECTED", "Tampered trade not rejected."
    assert "Hash mismatch" in cmd_tamper["reason"], "Wrong rejection reason."
    print("   Tampered proposal rejected.")

    # 11. Expired token test – create a new trade, expire the token manually
    prop2 = propose_trade("ETH", "short", 0.5, 3000, 3100, reasoning="expiry_test")
    tid2 = prop2["trade_id"]
    screen_trade(tid2)
    req_exp = request_approval(tid2)
    token_exp = req_exp["approval_token"]
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE approval_tokens SET expires_at = datetime('now', '-1 hour') WHERE token = ?", (token_exp,))
    conn.commit()
    conn.close()
    approve_exp = session.post(f"{BASE_URL}/api/approve/{tid2}")
    assert approve_exp.json().get("status") == "REJECTED", "Expired token should be rejected."
    print("   Expired token rejected.")

    # 12. Rejected trade cannot execute
    prop3 = propose_trade("SOL", "long", 10, 150, 140, reasoning="reject_test")
    tid3 = prop3["trade_id"]
    screen_trade(tid3)
    request_approval(tid3)
    reject_resp = session.post(f"{BASE_URL}/api/reject/{tid3}")
    assert reject_resp.status_code == 200, "Reject failed."
    cmd_reject = generate_execution_command(tid3)
    assert cmd_reject["status"] == "REJECTED", "Rejected trade should not execute."
    print("   Rejected trade blocked.")

    # 13. Unauthorized endpoints test
    # Logout
    logout_resp = session.post(f"{BASE_URL}/api/logout")
    assert logout_resp.status_code == 200, "Logout failed."
    # Try unauthorized access
    for endpoint in ["/api/pending_trades", "/api/approve/1", "/api/reject/1", "/api/trace/1"]:
        resp = session.get(endpoint)
        assert resp.status_code == 401, f"Endpoint {endpoint} not protected (status {resp.status_code})"
    print("   Unauthorized endpoints blocked.")

    print("\n✅ ALL INTEGRATION TESTS PASSED.\n")

if __name__ == "__main__":
    print("\n🚀 Starting live integration test against running Robo-Shopper...")
    if not check_server():
        sys.exit(1)
    try:
        login()
        test_full_pipeline()
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise