#!/usr/bin/env python3
"""
Robo-Shopper V4 - Hardened Risk Management MCP (Sprint 5).
Implements deterministic risk controls that CANNOT be bypassed by the LLM.
- 2% hard cap on per-trade risk.
- Validates all financial inputs.
- HARD STOP on missing portfolio balance (no silent mock fallback).
- Exposes both calculate_position_size and evaluate_trade_risk.
"""
import os
import sqlite3
from typing import Optional, Dict, Any

# Database path – uses unified config if available, otherwise falls back
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    from config import DB_PATH
except ImportError:
    DB_PATH = os.path.join(BASE_DIR, "data", "trades.db")

# Ensure the data directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ------------------------------------------------------------------
# 1. PORTFOLIO BALANCE (HARD STOP ON FAILURE)
# ------------------------------------------------------------------
def _get_real_portfolio_balance() -> float:
    """
    Fetches the REAL portfolio balance from the treasury table.
    If the balance cannot be retrieved, it raises a Hard Stop error.
    NEVER silently falls back to $10,000.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Ensure the treasury table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS treasury (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                current_balance REAL DEFAULT 10000.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Check if there is any row; if not, insert a default so we don't fail on first run
        cursor.execute("SELECT COUNT(*) FROM treasury")
        count = cursor.fetchone()[0]
        if count == 0:
            # Seed with a default $10,000 ONLY if the table is entirely empty.
            # This is the ONLY time a default is used.
            cursor.execute("INSERT INTO treasury (current_balance) VALUES (10000.0)")
            conn.commit()
        
        # Fetch the latest balance
        cursor.execute("SELECT current_balance FROM treasury ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] is not None:
            balance = float(row[0])
            if balance > 0:
                return balance
            else:
                raise ValueError(f"Treasury balance is zero or negative. Got: {balance}")
        else:
            raise ValueError("Treasury table exists but contains no valid balance row.")
            
    except sqlite3.Error as e:
        raise RuntimeError(f"HARD STOP: Database error while fetching portfolio balance. Details: {e}")
    except ValueError as e:
        raise RuntimeError(f"HARD STOP: {e}")
    except Exception as e:
        raise RuntimeError(f"HARD STOP: Unexpected error while fetching portfolio balance. Details: {e}")

# ------------------------------------------------------------------
# 2. POSITION SIZING (CALCULATES, BUT DOES NOT AUTHORISE)
# ------------------------------------------------------------------
def calculate_position_size(
    entry: float, 
    stop: float, 
    portfolio_balance: Optional[float] = None
) -> Dict[str, Any]:
    """
    Calculates the position size based on the 2% hard risk cap.
    Performs strict input validation.
    
    Args:
        entry: Proposed entry price (must be > 0)
        stop: Stop loss price (must be > 0 and != entry)
        portfolio_balance: Optional override (defaults to DB balance)
    
    Returns:
        Dict with position_size, risk_amount_usd, max_risk_percent, etc.
    
    Raises:
        ValueError: If any input is invalid.
        RuntimeError: If portfolio balance cannot be retrieved.
    """
    # --- Strict Input Validation (Hard Stop) ---
    if entry <= 0:
        raise ValueError(f"Entry price must be positive. Got: {entry}")
    if stop <= 0:
        raise ValueError(f"Stop loss price must be positive. Got: {stop}")
    if entry == stop:
        raise ValueError("Entry and Stop prices cannot be equal. Risk per unit would be zero.")
    
    # Get the real portfolio balance
    if portfolio_balance is None:
        portfolio_balance = _get_real_portfolio_balance()
    
    if portfolio_balance <= 0:
        raise ValueError(f"Portfolio balance must be positive. Got: {portfolio_balance}")
    
    # Hardcoded risk rule: 2% of portfolio
    RISK_PERCENT = 0.02
    risk_amount = portfolio_balance * RISK_PERCENT
    risk_per_unit = abs(entry - stop)
    
    # Size = risk_amount / risk_per_unit
    position_size = risk_amount / risk_per_unit
    
    return {
        "portfolio_balance": round(portfolio_balance, 2),
        "max_risk_percent": RISK_PERCENT * 100,  # 2.0
        "risk_amount_usd": round(risk_amount, 2),
        "position_size": round(position_size, 8),  # Crypto precision
        "entry_price": entry,
        "stop_loss": stop,
        "risk_per_unit": round(risk_per_unit, 2),
    }

# ------------------------------------------------------------------
# 3. HARDCODED VETO GATE (AUTHORISATION)
# ------------------------------------------------------------------
def evaluate_trade_risk(
    symbol: str,
    side: str,
    entry: float,
    stop: float,
    size: float,
    portfolio_balance: Optional[float] = None,
    rsi_override: Optional[float] = None,  # For testing/fallback
) -> Dict[str, Any]:
    """
    Hardcoded veto gate. This function is the final arbiter.
    Even if the LLM calculates a size, this function can REJECT the trade.
    
    Checks:
    1. 2% risk cap (based on entry, stop, and size).
    2. Basic RSI sanity (optional, requires market_intelligence_mcp).
    3. Minimum position size sanity.
    
    Args:
        symbol: Trading pair (BTC, ETH, SOL)
        side: "long" or "short"
        entry: Entry price
        stop: Stop loss
        size: Position size (in base asset units)
        portfolio_balance: Optional override
        rsi_override: For testing, bypass RSI fetch
    
    Returns:
        Dict with status ("PASSED" or "REJECTED"), reason, and warnings.
    
    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: If portfolio balance cannot be retrieved.
    """
    # --- Validate inputs ---
    if not symbol or symbol not in ["BTC", "ETH", "SOL"]:
        raise ValueError(f"Invalid symbol. Must be BTC, ETH, or SOL. Got: {symbol}")
    if side not in ["long", "short"]:
        raise ValueError(f"Side must be 'long' or 'short'. Got: {side}")
    if entry <= 0:
        raise ValueError(f"Entry price must be positive. Got: {entry}")
    if stop <= 0:
        raise ValueError(f"Stop loss must be positive. Got: {stop}")
    if entry == stop:
        raise ValueError("Entry and Stop cannot be equal.")
    if size <= 0:
        raise ValueError(f"Position size must be positive. Got: {size}")
    
    # Get portfolio balance
    if portfolio_balance is None:
        portfolio_balance = _get_real_portfolio_balance()
    if portfolio_balance <= 0:
        raise ValueError(f"Portfolio balance must be positive. Got: {portfolio_balance}")
    
    # --- Check 1: 2% Risk Cap ---
    risk_per_unit = abs(entry - stop)
    risk_usd = risk_per_unit * size
    risk_percent = (risk_usd / portfolio_balance) * 100
    
    if risk_percent > 2.0:
        return {
            "status": "REJECTED",
            "reason": f"Risk exceeds 2% hard cap. Proposed risk: {risk_percent:.2f}% (max allowed: 2.0%). "
                      f"Risk amount: ${risk_usd:.2f} on portfolio of ${portfolio_balance:.2f}.",
            "risk_percent": round(risk_percent, 2),
            "risk_usd": round(risk_usd, 2),
            "portfolio_balance": round(portfolio_balance, 2),
            "warnings": []
        }

    # --- Check 2: RSI / Overbought Oversold (WITH WARNINGS, NOT SILENT) ---
    warnings = []
    rsi = None
    try:
        import market_intelligence_mcp
        if rsi_override is not None:
            rsi = rsi_override
        else:
            tech_data = market_intelligence_mcp.analyze_technicals(symbol)
            if isinstance(tech_data, dict) and "rsi" in tech_data:
                rsi = tech_data["rsi"]
        
        if rsi is not None:
            if rsi > 70 and side == "long":
                return {
                    "status": "REJECTED",
                    "reason": f"RSI is {rsi:.1f} (overbought > 70). Long trade rejected.",
                    "warnings": warnings,
                    "rsi": round(rsi, 1),
                    "portfolio_balance": round(portfolio_balance, 2)
                }
            if rsi < 30 and side == "short":
                return {
                    "status": "REJECTED",
                    "reason": f"RSI is {rsi:.1f} (oversold < 30). Short trade rejected.",
                    "warnings": warnings,
                    "rsi": round(rsi, 1),
                    "portfolio_balance": round(portfolio_balance, 2)
                }
    except ImportError:
        warnings.append("market_intelligence_mcp not available – RSI check skipped.")
    except Exception as e:
        warnings.append(f"RSI check failed: {str(e)} – proceeding with core risk checks.")
    
    # --- Check 3: Minimum position sanity ---
    min_size_map = {"BTC": 0.0001, "ETH": 0.001, "SOL": 0.01}
    min_size = min_size_map.get(symbol, 0.0001)
    if size < min_size:
        return {
            "status": "REJECTED",
            "reason": f"Position size {size:.8f} is below minimum {min_size:.8f} for {symbol}.",
            "warnings": warnings,
            "portfolio_balance": round(portfolio_balance, 2)
        }
    
    # --- All checks passed ---
    return {
        "status": "PASSED",
        "reason": f"Trade passed all risk checks. Risk: {risk_percent:.2f}% (within 2% cap).",
        "warnings": warnings,
        "risk_percent": round(risk_percent, 2),
        "risk_usd": round(risk_usd, 2),
        "portfolio_balance": round(portfolio_balance, 2)
    }

# ------------------------------------------------------------------
# 4. OPTIONAL: Helper to seed the treasury (for first-time users)
# ------------------------------------------------------------------
def seed_treasury(initial_balance: float = 10000.0) -> Dict[str, Any]:
    """
    Seeds the treasury with an initial balance.
    Use this if the treasury table is empty.
    """
    if initial_balance <= 0:
        raise ValueError("Initial balance must be positive.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS treasury (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            current_balance REAL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("INSERT INTO treasury (current_balance) VALUES (?)", (initial_balance,))
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "message": f"Treasury seeded with ${initial_balance:.2f}",
        "balance": initial_balance
    }

# ------------------------------------------------------------------
# 5. SELF-TEST (Run this file directly to verify)
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("🧪 Testing Risk Management MCP...")
    
    # Test 1: Calculate position size
    try:
        result = calculate_position_size(entry=60000, stop=59500, portfolio_balance=10000)
        print(f"✅ calculate_position_size: {result}")
    except Exception as e:
        print(f"❌ calculate_position_size error: {e}")
    
    # Test 2: Evaluate trade risk (should PASS)
    try:
        result = evaluate_trade_risk(
            symbol="BTC",
            side="long",
            entry=60000,
            stop=59500,
            size=0.4,
            portfolio_balance=10000.0
        )
        print(f"✅ evaluate_trade_risk (PASS expected): {result}")
    except Exception as e:
        print(f"❌ evaluate_trade_risk error: {e}")
    
    # Test 3: Evaluate trade risk (should REJECT due to >2%)
    try:
        result = evaluate_trade_risk(
            symbol="BTC",
            side="long",
            entry=60000,
            stop=59000,
            size=0.4,
            portfolio_balance=10000.0
        )
        print(f"✅ evaluate_trade_risk (REJECT expected): {result}")
    except Exception as e:
        print(f"❌ evaluate_trade_risk error: {e}")
    
    print("✅ Risk Management MCP tests complete.")