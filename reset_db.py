#!/usr/bin/env python3
"""
Robo-Shopper - Database Schema Reset Script.
Drops and recreates all tables with the correct schema for the current codebase.
"""
import sqlite3
import os
from config import DB_PATH

def reset_database():
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    # Delete existing database to clear old schema
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"🗑️  Deleted old database: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("🔨 Creating trades table...")
    cursor.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL,
            quantity REAL NOT NULL,
            portfolio_balance REAL DEFAULT 10000.0,
            risk_percent REAL,
            risk_amount REAL,
            pnl REAL,
            status TEXT DEFAULT 'proposed',
            reasoning TEXT,
            proposal_hash TEXT,
            policy_version TEXT,
            proposal_expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            executed_at TEXT,
            closed_at TEXT,
            execution_price REAL
        )
    """)
    
    print("🔨 Creating approval_tokens table...")
    cursor.execute("""
        CREATE TABLE approval_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            token TEXT,
            token_hash TEXT NOT NULL,
            policy_version TEXT,
            requested_by TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            used_at TEXT
        )
    """)
    
    print("🔨 Creating treasury table...")
    cursor.execute("""
        CREATE TABLE treasury (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            current_balance REAL DEFAULT 10000.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("INSERT INTO treasury (current_balance) VALUES (10000.0)")
    
    conn.commit()
    conn.close()
    print("✅ Database schema reset successfully. You can now run 'python verify_p0.py'.")

if __name__ == "__main__":
    reset_database()