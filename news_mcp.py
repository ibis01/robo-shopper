import requests
import json

def get_crypto_sentiment(coin="BTC"):
    """Fetches latest crypto news and returns a sentiment summary."""
    try:
        # Using CryptoPanic free API (no key required for limited public requests, but register for one later)
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token=YOUR_PUBLIC_TOKEN&currencies={coin}&filter=hot"
        # Hardcoded mock for immediate testing. Replace with real API.
        mock_news = [
            f"{coin} whales accumulate 10k tokens amid market dip.",
            f"Regulatory clarity boosts {coin} institutional adoption.",
            f"{coin} miners selling reserves, creating short-term selling pressure."
        ]
        return json.dumps({
            "status": "success",
            "coin": coin,
            "headlines": mock_news,
            "overall_sentiment": "mixed" if len(mock_news) > 1 else "bullish"
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})