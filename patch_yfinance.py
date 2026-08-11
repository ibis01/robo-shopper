import re

with open("market_intelligence_mcp.py", "r") as f:
    text = f.read()

# Patch 1: analyze_technicals (OHLCV candles)
old_ohlcv = """        result = await gateway.fetch(
            "ohlcv",
            symbol,
            timeframe=resolved_timeframe,
            limit=safe_limit,
        )
        payload = result["payload"]"""

new_ohlcv = """        try:
            result = await gateway.fetch(
                "ohlcv",
                symbol,
                timeframe=resolved_timeframe,
                limit=safe_limit,
            )
            payload = result["payload"]
        except MarketDataError:
            logger.warning("Crypto exchanges blocked. Falling back to Yahoo Finance.")
            import yfinance as yf
            base = symbol.split('/')[0]
            df = yf.Ticker(f"{base}-USD").history(period="7d", interval="1h")
            if df.empty:
                raise MarketDataError("yfinance returned no data")
            payload = [
                [int(row.Index.timestamp() * 1000), float(row.Open), float(row.High), float(row.Low), float(row.Close), float(row.Volume)]
                for row in df.itertuples()
            ]
            result = {"exchange": "yahoo_finance", "symbol": symbol, "payload": payload}"""

# Patch 2: get_spot_quote (Ticker)
old_ticker = """    try:
        result = await gateway.fetch("ticker", symbol)
        ticker = result["payload"]"""

new_ticker = """    try:
        try:
            result = await gateway.fetch("ticker", symbol)
            ticker = result["payload"]
        except MarketDataError:
            logger.warning("Crypto exchanges blocked for ticker. Falling back to Yahoo Finance.")
            import yfinance as yf
            base = symbol.split('/')[0]
            tk = yf.Ticker(f"{base}-USD")
            info = tk.fast_info
            ticker = {"last": info.last_price, "bid": info.last_price, "ask": info.last_price, "quoteVolume": info.three_month_average_volume}
            result = {"exchange": "yahoo_finance", "symbol": symbol, "payload": ticker}"""

if old_ohlcv in text:
    text = text.replace(old_ohlcv, new_ohlcv)
    print("✅ Patched OHLCV")
else:
    print("❌ Could not find OHLCV block")

if old_ticker in text:
    text = text.replace(old_ticker, new_ticker)
    print("✅ Patched Ticker")
else:
    print("❌ Could not find Ticker block")

with open("market_intelligence_mcp.py", "w") as f:
    f.write(text)
