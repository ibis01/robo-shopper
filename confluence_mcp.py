"""Robo-Shopper V4 - Multi-timeframe confluence + regime detection (Sprint 3)."""
import json
import statistics
import urllib.request
from mcp.server.fastmcp import FastMCP

def _base(symbol):
    return symbol.replace("USDT", "").replace("USD", "").split("-")[0].upper()

def _fetch_chart(base):
    cg_id = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}.get(base.upper(), base.lower())
    # CoinGecko market_chart for last 60 days (gives us hourly data)
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=60"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["prices"]  # [[timestamp_ms, price], ...]
    except Exception as e:
        print(f"CoinGecko failed: {e}")
        return []

def _bucket(prices, mins):
    if not prices: return []
    candles = []
    bucket = []
    # Align bucket start to the nearest interval
    bucket_start = (prices[0][0] // (mins * 60000)) * (mins * 60000)
    for ts, p in prices:
        if ts >= bucket_start + (mins * 60000):
            if bucket:
                # O, H, L, C
                candles.append((bucket[0][1], max(x[1] for x in bucket), min(x[1] for x in bucket), bucket[-1][1]))
            bucket_start += (mins * 60000)
            bucket = []
        bucket.append((ts, p))
    if bucket:
        candles.append((bucket[0][1], max(x[1] for x in bucket), min(x[1] for x in bucket), bucket[-1][1]))
    return candles

def _closes(candles):
    return [c[3] for c in candles]

def _rsi(closes, period=14):
    if len(closes) < period + 1: return None
    d = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(x, 0) for x in d]
    losses = [max(-x, 0) for x in d]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0: return 100.0
    return round(100 - 100 / (1 + ag / al), 2)

def _ema_series(vals, span):
    k = 2 / (span + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def _macd_hist(closes):
    if len(closes) < 35: return None
    m = [a - b for a, b in zip(_ema_series(closes, 12), _ema_series(closes, 26))]
    sig = _ema_series(m, 9)
    return round(m[-1] - sig[-1], 6)

def _sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None

def _regime(closes):
    s20, s50 = _sma(closes, 20), _sma(closes, 50)
    if s20 is None or s50 is None: return "unknown"
    if closes[-1] > s20 > s50: return "trending-up"
    if closes[-1] < s20 < s50: return "trending-down"
    return "ranging"

def _vol(closes):
    r = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(max(1, len(closes)-30), len(closes))]
    return round(statistics.stdev(r) * 100, 3) if len(r) > 2 else None

def register(mcp: FastMCP):
    @mcp.tool()
    def confluence_report(symbol: str = "BTC") -> dict:
        """Scan 1h/4h/1d via CoinGecko for RSI+MACD+regime confluence."""
        base = _base(symbol)
        prices = _fetch_chart(base)
        if not prices:
            return {"error": "CoinGecko failed to return price data"}
        
        # Bucket the hourly stream into 1h, 4h, and 1d candles
        per = {
            "1h": _bucket(prices, 60),
            "4h": _bucket(prices, 240),
            "1d": _bucket(prices, 1440)
        }
        
        out = {}
        for tf, candles in per.items():
            closes = _closes(candles)
            out[tf] = {"rsi": _rsi(closes), "macd_hist": _macd_hist(closes),
                       "regime": _regime(closes), "vol_pct": _vol(closes)}
        
        oversold = [t for t, d in out.items() if d["rsi"] is not None and d["rsi"] < 35]
        overbought = [t for t, d in out.items() if d["rsi"] is not None and d["rsi"] > 65]
        bull = [t for t, d in out.items() if (d["macd_hist"] or 0) > 0]
        up = [t for t, d in out.items() if d["regime"] == "trending-up"]
        down = [t for t, d in out.items() if d["regime"] == "trending-down"]

        if len(oversold) >= 2 and not down:
            verdict = "MEAN-REVERSION LONG confluence"
        elif len(bull) == 3 and len(up) >= 2:
            verdict = "MOMENTUM LONG confluence"
        elif len(overbought) >= 2 and not up:
            verdict = "OVERBOUGHT - take profit / stand aside"
        else:
            verdict = "NO CONFLUENCE - stand down"

        return {"symbol": base, "timeframes": out, "verdict": verdict,
                "confidence": round(max(len(oversold), len(bull), len(overbought)) / 3.0, 2),
                "note": "Powered by CoinGecko (market_chart)"}
