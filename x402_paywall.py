"""Robo-Shopper V3 - x402 Memory Paywall.
Exposes the agent's trade history to the world, but demands payment via x402.
"""
import sqlite3
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

app = FastAPI()
DB = "trades.db"

@app.get("/stats")
async def get_stats(x_payment: str | None = Header(None)):
    # 1. Check for payment (Mocked for hackathon demo)
    if not x_payment:
        # HTTP 402 Payment Required - the core of x402!
        return JSONResponse(
            status_code=402,
            content={
                "error": "Payment Required",
                "message": "To query the Robo-Shopper memory bank, you must pay 0.05 USDC.",
                "payment_protocol": "x402",
                "recipient_address": "0x8d6538B16d8f7B1f4335f3874fc12bE377F7c1cc",
                "amount": "0.05",
                "asset": "USDC",
                "network": "X Layer"
            }
        )
        
    # Mock verification (in production, verify tx hash on-chain)
    if x_payment != "verified_mock_tx_hash":
         return JSONResponse(status_code=402, content={"error": "Invalid payment signature"})

    # 2. Payment accepted! Query the brain.
    con = sqlite3.connect(DB)
    total = con.execute("SELECT COUNT(*) FROM trades WHERE status='closed'").fetchone()[0]
    wins = con.execute("SELECT COUNT(*) FROM trades WHERE status='closed' AND pnl > 0").fetchone()[0]
    pnl = con.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='closed'").fetchone()[0]
    
    win_rate = (wins / total * 100) if total > 0 else 0
    
    return {
        "agent": "Robo-Shopper V3",
        "total_trades": total,
        "wins": wins,
        "win_rate_pct": round(win_rate, 2),
        "lifetime_pnl_usd": round(pnl, 2),
        "message": "Access granted. Welcome to the memory bank."
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
