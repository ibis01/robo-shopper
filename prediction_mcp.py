import requests
import json

def get_polymarket_markets(limit=10):
    """Fetches live prediction markets from Polymarket (via Gamma API)."""
    try:
        url = f"https://gamma-api.polymarket.com/markets?limit={limit}&closed=false"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data:
            simplified = []
            for market in data[:limit]:
                simplified.append({
                    "title": market.get("question", "N/A"),
                    "slug": market.get("slug", "N/A"),
                    "volume": market.get("volume24hr", 0),
                    "end_date": market.get("endDate", "N/A"),
                })
            return json.dumps({"status": "success", "markets": simplified}, indent=2)
        return json.dumps({"status": "error", "message": "No markets found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def verify_prediction_odds(slug):
    """Cross-checks Polymarket odds against a simple 'reality' check (placeholder)."""
    # In reality, you'd connect to a news API or Oracle. 
    # For now, Llama will just use this as a prompt-enhancer.
    return json.dumps({
        "status": "success",
        "message": f"Prediction market '{slug}' currently has 65% Yes / 35% No. Recommendation: Compare against recent news headlines via News MCP."
    })