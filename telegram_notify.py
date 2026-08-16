"""Robo-Shopper V4 - Telegram Push Notifications (Sprint 7)."""
import os

def _load_env():
    try:
        for line in open(".env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass

_load_env()

import requests

def send_alert(text: str):
    """Sends a formatted message to the human's Telegram."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    # Telegram markdown is a bit strict, clean it up
    clean_text = text.replace("`", "").replace("**", "")
    
    payload = {
        "chat_id": chat_id,
        "text": f"🚨 *ROBO-SHOPPER PROPOSAL*\n\n{clean_text}\n\n_Awaiting terminal approval..._",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass # Silent fail if network is down
