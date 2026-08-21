# Paste the next Python block, then press Ctrl+D[201~from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd
import ccxt.async_support as ccxt_async

logger = logging.getLogger("robo_shopper.market_intelligence")
logging.basicConfig(level=logging.INFO)

MarketOperation = Literal["ticker", "order_book", "ohlcv"]


class MarketDataError(RuntimeError):
    def __init__(self, message: str, errors: Optional[List[Exception]] = None):
        super().__init__(message)
        self.errors = errors or []


@dataclass(frozen=True)
class MarketIntelligenceConfig:
    preferred_exchange: str = field(
        default_factory=lambda: os.getenv("ROBO_MARKET_EXCHANGE", "bybit").lower()
    )
    supported_exchanges: Tuple[str, ...] = ("bybit", "kucoin", "binance", "okx")
    default_quote_asset: str = "USDT"
    default_timeframe: str = "1h"
    rsi_period: int = 14
    min_candles: int = 50
    max_candles: int = 200
    max_order_book_levels: int = 50
    timeout_ms: int = 20_000

    @property
    def exchange_priority(self) -> List[str]:
        preferred = (
            self.preferred_exchange
            if self.preferred_exchange in self.supported_exchanges
            else self.supported_exchanges[0]
        )
        return [preferred] + [x for x in self.supported_exchanges if x != preferred]


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_round(value: Any, ndigits: int = 8) -> Optional[float]:
    number = _safe_float(value)
    if number is None:
        return None
    try:
        if pd.isna(number):
            return None
    except Exception:
        pass
    return round(number, ndigits)


def _error_payload(tool: str, symbol: Optional[str], exc: Exception, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "tool": tool,
        "symbol": symbol,
        "error": str(exc),
        "error_type": exc.__class__.__name__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(exc, MarketDataError) and exc.errors:
        payload["causes"] = [str(item) for item in exc.errors[:3]]
    payload.update(extra)
    return payload


class PublicExchangeGateway:
    def __init__(self, config: MarketIntelligenceConfig):
        self.config = config

    @staticmethod
    def normalize_symbol(symbol: str, default_quote: str) -> str:
        raw = (symbol or "").strip().upper()
        if not raw:
            raise MarketDataError("symbol is required")

        if "/" in raw:
            base, quote = raw.split("/", 1)
            return f"{base.strip()}/{quote.strip()}"

        if "-" in raw:
            base, quote = raw.split("-", 1)
            return f"{base.strip()}/{quote.strip()}"

        for suffix in ("USDT", "USDC", "USD"):
            if raw.endswith(suffix) and len(raw) > len(suffix):
                return f"{raw[: -len(suffix)]}/{suffix}"

        return f"{raw}/{default_quote.upper()}"

    def _client(self, exchange_id: str):
        exchange_class = getattr(ccxt_async, exchange_id)
        return exchange_class(
            {
                "enableRateLimit": True,
                "timeout": self.config.timeout_ms,
                "options": {"defaultType": "spot"},
            }
        )

    async def fetch(self, operation: MarketOperation, symbol: str, **params: Any) -> Dict[str, Any]:
        normalized_symbol = self.normalize_symbol(symbol, self.config.default_quote_asset)
        errors: List[Exception] = []

        for exchange_id in self.config.exchange_priority:
            client = None
            try:
                client = self._client(exchange_id)

                if operation == "ticker":
                    payload = await client.fetch_ticker(normalized_symbol)
                elif operation == "order_book":
                    payload = await client.fetch_order_book(
                        normalized_symbol,
                        limit=params.get("limit", 10),
                    )
                elif operation == "ohlcv":
                    payload = await client.fetch_ohlcv(
                        normalized_symbol,
                        timeframe=params.get("timeframe", self.config.default_timeframe),
                        limit=params.get("limit", self.config.min_candles),
                    )
                else:
                    raise MarketDataError(f"Unsupported operation: {operation}")

                return {
                    "exchange": exchange_id,
                    "symbol": normalized_symbol,
                    "payload": payload,
                }
            except Exception as exc:
                errors.append(exc)
                logger.warning(
                    "%s failed on %s for %s: %s",
                    operation,
                    exchange_id,
                    normalized_symbol,
                    exc,
                )
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass

        raise MarketDataError(
            f"All exchanges failed for {operation} {normalized_symbol}",
            errors=errors,
        )


def _rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rsi = pd.Series(50.0, index=closes.index)

    valid = avg_loss > 0
    rsi[valid] = 100.0 - (100.0 / (1.0 + (avg_gain[valid] / avg_loss[valid])))

    strong_gain = (avg_loss == 0) & (avg_gain > 0)
    rsi[strong_gain] = 100.0

    flat = (avg_loss == 0) & (avg_gain == 0)
    rsi[flat] = 50.0

    return rsi


def _analyze_ohlcv(ohlcv: List[List[float]], config: MarketIntelligenceConfig) -> Dict[str, Any]:
    if not ohlcv:
        raise MarketDataError("No candles provided")

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)

    rsi_series = _rsi(closes, config.rsi_period)
    last_close = float(closes.iloc[-1])
    rsi_value = float(rsi_series.iloc[-1])

    sma_20_series = closes.rolling(20).mean()
    sma_50_series = closes.rolling(50).mean()

    sma_20 = (
        float(sma_20_series.iloc[-1])
        if len(closes) >= 20 and pd.notna(sma_20_series.iloc[-1])
        else None
    )
    sma_50 = (
        float(sma_50_series.iloc[-1])
        if len(closes) >= 50 and pd.notna(sma_50_series.iloc[-1])
        else None
    )

    trend_score = 0
    if sma_20 is not None:
        trend_score += 1 if last_close >= sma_20 else -1
    if sma_50 is not None:
        trend_score += 1 if last_close >= sma_50 else -1
    if sma_20 is not None and sma_50 is not None:
        trend_score += 1 if sma_20 >= sma_50 else -1

    if trend_score >= 2:
        trend = "Bullish"
    elif trend_score <= -2:
        trend = "Bearish"
    else:
        trend = "Mixed"

    if rsi_value >= 70.0:
        signal = "Overbought"
        momentum = "overbought"
        risk_level = "HIGH"
        suggested_action = "REQUIRE_EXTRA_CONFIRMATION_BEFORE_BUY"
        reason = "RSI is above 70."
    elif rsi_value <= 30.0:
        signal = "Oversold"
        momentum = "oversold"
        risk_level = "ELEVATED_BUT_OPPORTUNISTIC"
        suggested_action = "CHECK_SUPPORT_THEN_CONSIDER_STAGED_ENTRY"
        reason = "RSI is below 30."
    else:
        signal = "Neutral"
        if rsi_value >= 55.0:
            momentum = "bullish"
        elif rsi_value <= 45.0:
            momentum = "bearish"
        else:
            momentum = "neutral"
        risk_level = "NORMAL"
        suggested_action = "WAIT_FOR_CONFIRMATION"
        reason = "RSI is in the neutral band."

    risk_flags: List[str] = []
    if signal == "Overbought":
        risk_flags.append("RSI_OVERBOUGHT")
    if signal == "Oversold":
        risk_flags.append("RSI_OVERSOLD")
    if sma_50 is not None and last_close < sma_50:
        risk_flags.append("PRICE_BELOW_LONG_TREND")
    if sma_20 is not None and sma_50 is not None and sma_20 < sma_50:
        risk_flags.append("SHORT_TREND_BELOW_LONG_TREND")

    lookback = min(20, len(df))
    recent_support = float(lows.tail(lookback).min()) if lookback else None
    recent_resistance = float(highs.tail(lookback).max()) if lookback else None

    distance_to_support_pct = (
        ((last_close - recent_support) / last_close) * 100.0
        if recent_support is not None and last_close > 0
        else None
    )
    distance_to_resistance_pct = (
        ((recent_resistance - last_close) / last_close) * 100.0
        if recent_resistance is not None and last_close > 0
        else None
    )

    rsi_strength = min(abs(rsi_value - 50.0) / 50.0, 1.0)
    trend_strength = min(abs(trend_score) / 3.0, 1.0)
    confidence = round((0.65 * rsi_strength) + (0.35 * trend_strength), 3)

    return {
        "last_close": _safe_round(last_close, 8),
        "rsi_period": config.rsi_period,
        "rsi_14": _safe_round(rsi_value, 2),
        "momentum": momentum,
        "sma_20": _safe_round(sma_20, 8),
        "sma_50": _safe_round(sma_50, 8),
        "trend": trend,
        "trend_score": trend_score,
        "signal": signal,
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "suggested_action": suggested_action,
        "reason": reason,
        "confidence": confidence,
        "recent_support_20": _safe_round(recent_support, 8),
        "recent_resistance_20": _safe_round(recent_resistance, 8),
        "distance_to_support_pct": _safe_round(distance_to_support_pct, 4),
        "distance_to_resistance_pct": _safe_round(distance_to_resistance_pct, 4),
        "last_candle_time": df["timestamp"].iloc[-1].isoformat(),
    }


async def _get_spot_quote(gateway: PublicExchangeGateway, symbol: str) -> Dict[str, Any]:
    try:
        try:
            result = await gateway.fetch("ticker", symbol)
            ticker = result["payload"]
        except MarketDataError:
            logger.warning("Crypto exchanges blocked for ticker. Falling back to Yahoo Finance.")
            import yfinance as yf
            base = symbol.split('/')[0]
            base = next((base[:-len(q)] for q in ("USDT","USDC","BUSD","USD") if base.endswith(q) and len(base)>len(q)), base)
            tk = yf.Ticker(f"{base}-USD")
            info = tk.fast_info
            ticker = {"last": info.last_price, "bid": info.last_price, "ask": info.last_price, "quoteVolume": info.three_month_average_volume}
            result = {"exchange": "yahoo_finance", "symbol": symbol, "payload": ticker}

        last = _safe_float(ticker.get("last"))
        bid = _safe_float(ticker.get("bid"))
        ask = _safe_float(ticker.get("ask"))

        if bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
            spread = ask - bid
            spread_bps = (spread / mid) * 10_000 if mid > 0 else None
        else:
            mid = last
            spread = None
            spread_bps = None

        return {
            "ok": True,
            "tool": "get_spot_quote",
            "exchange": result["exchange"],
            "symbol": result["symbol"],
            "last": _safe_round(last, 8),
            "bid": _safe_round(bid, 8),
            "ask": _safe_round(ask, 8),
            "mid": _safe_round(mid, 8),
            "spread": _safe_round(spread, 8),
            "spread_bps": _safe_round(spread_bps, 4),
            "percentage_change_24h": _safe_round(_safe_float(ticker.get("percentage")), 4),
            "quote_volume_24h": _safe_round(_safe_float(ticker.get("quoteVolume")), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.exception("get_spot_quote failed")
        return _error_payload("get_spot_quote", symbol, exc)


async def _get_order_book_metrics(
    gateway: PublicExchangeGateway,
    config: MarketIntelligenceConfig,
    symbol: str,
    limit: int = 10,
) -> Dict[str, Any]:
    try:
        safe_limit = max(1, min(int(limit or 10), config.max_order_book_levels))
        result = await gateway.fetch("order_book", symbol, limit=safe_limit)
        order_book = result["payload"]

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        for item in (order_book.get("bids") or [])[:safe_limit]:
            try:
                bids.append((float(item[0]), float(item[1])))
            except Exception:
                continue

        for item in (order_book.get("asks") or [])[:safe_limit]:
            try:
                asks.append((float(item[0]), float(item[1])))
            except Exception:
                continue

        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None

        spread = None
        spread_bps = None
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0
            if mid > 0:
                spread_bps = (spread / mid) * 10_000

        bid_depth_quote = sum(price * amount for price, amount in bids)
        ask_depth_quote = sum(price * amount for price, amount in asks)
        total_depth_quote = bid_depth_quote + ask_depth_quote
        depth_imbalance = (
            (bid_depth_quote - ask_depth_quote) / total_depth_quote
            if total_depth_quote > 0
            else None
        )

        if depth_imbalance is None:
            microstructure_bias = "unknown"
        elif depth_imbalance > 0.10:
            microstructure_bias = "bid_heavy"
        elif depth_imbalance < -0.10:
            microstructure_bias = "ask_heavy"
        else:
            microstructure_bias = "balanced"

        return {
            "ok": True,
            "tool": "get_order_book_metrics",
            "exchange": result["exchange"],
            "symbol": result["symbol"],
            "levels": safe_limit,
            "best_bid": _safe_round(best_bid, 8),
            "best_ask": _safe_round(best_ask, 8),
            "spread": _safe_round(spread, 8),
            "spread_bps": _safe_round(spread_bps, 4),
            "bid_depth_quote": _safe_round(bid_depth_quote, 2),
            "ask_depth_quote": _safe_round(ask_depth_quote, 2),
            "depth_imbalance": _safe_round(depth_imbalance, 4),
            "microstructure_bias": microstructure_bias,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.exception("get_order_book_metrics failed")
        return _error_payload("get_order_book_metrics", symbol, exc)


async def _get_technicals(
    gateway: PublicExchangeGateway,
    config: MarketIntelligenceConfig,
    symbol: str,
    timeframe: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        resolved_timeframe = (timeframe or config.default_timeframe).strip() or config.default_timeframe
        safe_limit = max(
            config.min_candles,
            min(int(limit or config.min_candles), config.max_candles),
        )

        try:
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
            base = next((base[:-len(q)] for q in ("USDT","USDC","BUSD","USD") if base.endswith(q) and len(base)>len(q)), base)
            df = yf.Ticker(f"{base}-USD").history(period="7d", interval="1h")
            if df.empty:
                raise MarketDataError("yfinance returned no data")
            payload = [
                [int(row.Index.timestamp() * 1000), float(row.Open), float(row.High), float(row.Low), float(row.Close), float(row.Volume)]
                for row in df.itertuples()
            ]
            result = {"exchange": "yahoo_finance", "symbol": symbol, "payload": payload}

        if not payload:
            return _error_payload(
                "analyze_technicals",
                result["symbol"],
                MarketDataError("Exchange returned no candles."),
                exchange=result["exchange"],
                timeframe=resolved_timeframe,
            )

        minimum_candles = max(20, config.rsi_period + 1)
        if len(payload) < minimum_candles:
            return _error_payload(
                "analyze_technicals",
                result["symbol"],
                MarketDataError(f"Not enough candles: {len(payload)}"),
                exchange=result["exchange"],
                timeframe=resolved_timeframe,
            )

        analysis = _analyze_ohlcv(payload, config)

        return {
            "ok": True,
            "tool": "analyze_technicals",
            "exchange": result["exchange"],
            "symbol": result["symbol"],
            "timeframe": resolved_timeframe,
            "candles_requested": safe_limit,
            "candles_used": len(payload),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **analysis,
        }
    except Exception as exc:
        logger.exception("analyze_technicals failed")
        return _error_payload("analyze_technicals", symbol, exc, timeframe=timeframe)


def register_market_intelligence_tools(mcp: Any, config: Optional[MarketIntelligenceConfig] = None) -> None:
    cfg = config or MarketIntelligenceConfig()
    gateway = PublicExchangeGateway(cfg)

    @mcp.tool()
    async def get_spot_quote(symbol: str) -> Dict[str, Any]:
        """Fetch a live public spot quote."""
        return await _get_spot_quote(gateway, symbol)

    @mcp.tool()
    async def get_order_book_metrics(symbol: str, limit: int = 10) -> Dict[str, Any]:
        """Fetch order book metrics."""
        return await _get_order_book_metrics(gateway, cfg, symbol, limit)

    @mcp.tool()
    async def analyze_technicals(
        symbol: str,
        timeframe: str = cfg.default_timeframe,
        limit: int = cfg.min_candles,
    ) -> Dict[str, Any]:
        """Calculate RSI, SMA trend, support/resistance, and signal."""
        return await _get_technicals(gateway, cfg, symbol, timeframe, limit)

# ------------------------------------------------------------------
# MODULE-LEVEL EXPORTS (For direct calling by main_server.py)
# ------------------------------------------------------------------
async def analyze_technicals(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 50,
) -> Dict[str, Any]:
    """Module-level wrapper for analyze_technicals to be called by main_server.py"""
    cfg = MarketIntelligenceConfig()
    gateway = PublicExchangeGateway(cfg)
    return await _get_technicals(gateway, cfg, symbol, timeframe, limit)



if __name__ == "__main__":
    import json

    async def main():
        cfg = MarketIntelligenceConfig()
        gateway = PublicExchangeGateway(cfg)
        result = await _get_technicals(gateway, cfg, "BTC")
        print(json.dumps(result, indent=2))

    asyncio.run(main())
