import requests
import json
import pandas as pd

def get_deribit_summary(currency="BTC"):
    """Fetches BTC or ETH option summaries from Deribit (real listed contracts)."""
    try:
        url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={currency}&kind=option"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if "result" in data and data["result"]:
            # Filter for near-term (7-30 days) and ATM-ish
            df = pd.DataFrame(data["result"])
            # Return top 5 contracts by volume
            top_contracts = df.nlargest(5, 'volume').to_dict('records')
            return json.dumps({
                "status": "success",
                "currency": currency,
                "top_contracts": top_contracts,
                "underlying_price": df['underlying_price'].iloc[0] if not df.empty else None
            }, indent=2)
        return json.dumps({"status": "error", "message": "No option data found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

def suggest_option_strategy(currency="BTC", sentiment="neutral"):
    """
    Simple strategy suggester based on volatility (IV) and sentiment.
    Llama will call this to get a human-readable strategy.
    """
    # In production, you'd compute IV from the summary. For now, a mock logic.
    return json.dumps({
        "strategies": [
            f"Covered Call: If you own {currency}, sell OTM calls to generate yield (neutral/bearish).",
            f"Cash-Secured Put: If you want to buy {currency} at a discount, sell ATM puts (bullish).",
            "Straddle: Buy both ATM call and put if you expect massive volatility (earnings/FOMC)."
        ]
    })