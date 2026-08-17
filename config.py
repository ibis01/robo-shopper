"""
Robo-Shopper V4 - Central Configuration (Sprint 5).
Single source of truth for database paths, constants, and shared settings.
"""
import os

# --- Project Root ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Database (UNIFIED) ---
# Every module MUST use this path. No more scattered databases.
DB_PATH = os.environ.get("ROBO_SHOPPER_DB", os.path.join(BASE_DIR, "data", "trades.db"))

# --- Ensure the data directory exists ---
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# --- Risk Constants (Standardised: DECIMAL format) ---
MAX_RISK_PER_TRADE = 0.02      # 2%
MAX_DAILY_DRAWDOWN = 0.05      # 5%
MAX_OPEN_EXPOSURE = 0.20       # 20%
CORE_ASSETS = ["BTC", "ETH", "SOL"]

def ensure_schema():
    """Ensures all columns for the state machine exist."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(trades)")
    existing = [row[1] for row in cursor.fetchall()]
    
    new_cols = {
        "proposal_hash": "TEXT",
        "last_modified_by": "TEXT",
        "transition_metadata": "TEXT",
        "approval_requested_at": "TIMESTAMP",
        "last_modified_at": "TIMESTAMP",
    }
    
    for col, col_type in new_cols.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
    
    conn.commit()
    conn.close()
