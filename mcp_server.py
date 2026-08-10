import json
import hashlib
import os
import httpx
from datetime import datetime, timezone
from fastmcp import FastMCP

mcp = FastMCP("Robo-Shopper-ASP")

# --- 📓 The Magic Diary ---
AUDIT_FILE = "audit.jsonl"
last_hash = "0" * 16
if os.path.exists(AUDIT_FILE):
    with open(AUDIT_FILE) as f:
        lines = f.read().strip().splitlines()
        if lines:
            last_hash = json.loads(lines[-1]).get("hash", last_hash)

def diary(event, details):
    global last_hash
    entry = {"time": datetime.now(timezone.utc).isoformat(),
             "event": event, "details": details, "prev": last_hash}
    last_hash = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]
    entry["hash"] = last_hash
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

# --- The Robot's Official Tools ---

@mcp.tool()
def get_btc_price() -> str:
    """Get the current live price of Bitcoin from the OKX public API."""
    try:
        r = httpx.get("https://www.okx.com/api/v5/market/ticker", 
                      params={"instId": "BTC-USDT"}, timeout=5.0).json()
        price = float(r['data'][0]['last'])
        diary("price_fetch", {"price": price})
        return f"The current live price of Bitcoin on OKX is ${price:,.2f}."
    except Exception as e:
        # Safety net if the network blocks the API
        diary("price_fetch_error", {"error": str(e)})
        return "Bitcoin is $105,420.50 (Using offline mock data due to network limits)."

@mcp.tool()
def get_option_expiries() -> str:
    """Get the next available expiration dates for Bitcoin options."""
    return "The next 3 option expiration dates are: Sept 27, Oct 25, and Nov 22."

@mcp.tool()
def propose_trade(contract: str, side: str, amount: float, user_confirmed: bool) -> str:
    """
    Propose a governed trade. 
    - If user_confirmed is False: Proposes the trade and waits for the 'Big Green Button'.
    - If user_confirmed is True: Executes the trade and records it in the Magic Diary.
    """
    MAX_AUTO_APPROVE = 500.0
    ABSOLUTE_LIMIT = 1000.0

    if amount > ABSOLUTE_LIMIT:
        diary("rejected_by_rulebook", {"contract": contract, "amount": amount})
        return "REJECTED: Amount exceeds absolute safety limit."

    if not user_confirmed:
        diary("proposal", {"contract": contract, "side": side, "amount": amount})
        return f"TRADE PROPOSED: {side} ${amount} of {contract}. Waiting for human approval."

    if amount > MAX_AUTO_APPROVE:
        diary("human_approved", {"contract": contract, "amount": amount})
    
    diary("executed", {"contract": contract, "side": side, "amount": amount})
    return f"SUCCESS: {side} ${amount} of {contract} executed and recorded in the diary."

if __name__ == "__main__":
    mcp.run(transport="sse")
