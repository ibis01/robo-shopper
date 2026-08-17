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