import sqlite3
import os
from config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Forcefully drop the old table
cursor.execute("DROP TABLE IF EXISTS approval_tokens")

# Recreate with the correct schema
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
conn.commit()
conn.close()
print("✅ Schema fixed. Run 'python verify_p0.py' now.")