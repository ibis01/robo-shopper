import sys
from functools import partial
print = partial(print, file=sys.stderr)

import asyncio
import logging
import sys
from typing import Any

# Import gateway and config from Step 1
try:
    from market_intelligence_mcp import PublicExchangeGateway, MarketIntelligenceConfig
except ImportError:
    print("Error: Could not import market_intelligence_mcp. Ensure it is in the same directory.")
    sys.exit(1)

import pandas as pd

logger = logging.getLogger("robo_shopper.proactive_alerts")
logging.basicConfig(level=logging.INFO)

SYMBOLS_TO_MONITOR = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
CHECK_INTERVAL_SECONDS = 60

# ANSI color codes for terminal output
RED = '\033[91m'
YELLOW = '\033[93m'
GREEN = '\033[92m'
BOLD = '\033[1m'
RESET = '\033[0m'

def _calculate_rsi_inline(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

async def _monitor_markets():
    config = MarketIntelligenceConfig()
    gateway = PublicExchangeGateway(config)
    
    print(f"{GREEN}{BOLD}🚀 Proactive Market Monitor started. Checking {SYMBOLS_TO_MONITOR} every {CHECK_INTERVAL_SECONDS}s...{RESET}")
    
    while True:
        for symbol in SYMBOLS_TO_MONITOR:
            try:
                result = await gateway.fetch(
                    "ohlcv",
                    symbol,
                    timeframe="15m", # 15m is better for proactive setups
                    limit=50,
                )
                ohlcv = result.get("payload")
                if not ohlcv or len(ohlcv) < 20:
                    continue
                
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                closes = df["close"].astype(float)
                lows = df["low"].astype(float)
                highs = df["high"].astype(float)
                
                rsi_series = _calculate_rsi_inline(closes)
                current_rsi = rsi_series.iloc[-1]
                
                current_price = closes.iloc[-1]
                recent_support = lows.tail(20).min()
                recent_resistance = highs.tail(20).max()
                
                distance_to_support = (current_price - recent_support) / current_price
                
                # Condition 1: Major Buy Setup (Oversold + Near Support)
                if current_rsi < 30 and distance_to_support < 0.015: # Within 1.5% of support
                    alert_msg = (
                        f"\n{RED}{BOLD}🚨🚨🚨 PROACTIVE ALERT: MAJOR BUY SETUP DETECTED 🚨🚨🚨{RESET}\n"
                        f"{BOLD}Asset:{RESET} {symbol}\n"
                        f"{BOLD}Current Price:{RESET} ${current_price:,.2f}\n"
                        f"{BOLD}RSI(14):{RESET} {current_rsi:.2f} {RED}(OVERSOLD){RESET}\n"
                        f"{BOLD}Support Level:{RESET} ${recent_support:,.2f}\n"
                        f"{BOLD}Distance to Support:{RESET} {distance_to_support*100:.2f}%\n"
                        f"{GREEN}{BOLD}Suggestion:{RESET} Consider a staged BUY entry. Run `analyze_technicals` for full context.\n"
                        f"{RED}{BOLD}🚨🚨🚨---------------------------------------🚨🚨🚨{RESET}\n"
                    )
                    print(alert_msg, flush=True)
                    
                # Condition 2: Major Sell Warning (Overbought + Near Resistance)
                elif current_rsi > 70 and (recent_resistance - current_price) / current_price < 0.015:
                    alert_msg = (
                        f"\n{YELLOW}{BOLD}⚠️ PROACTIVE ALERT: OVERBOUGHT WARNING ⚠️{RESET}\n"
                        f"{BOLD}Asset:{RESET} {symbol}\n"
                        f"{BOLD}RSI:{RESET} {current_rsi:.2f} {YELLOW}(OVERBOUGHT){RESET}\n"
                        f"{BOLD}Resistance:{RESET} ${recent_resistance:,.2f}\n"
                        f"{YELLOW}{BOLD}Suggestion:{RESET} Avoid new longs. Consider taking profits if holding.\n"
                    )
                    print(alert_msg, flush=True)
                    
            except Exception as e:
                logger.error(f"Monitor error for {symbol}: {e}")
                
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

def start_proactive_monitor():
    """Starts the background asyncio task."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_monitor_markets())
        logger.info("Monitor task scheduled on running event loop.")
    except RuntimeError:
        logger.info("No running event loop found yet. Will start when MCP server starts.")

def register_proactive_alerts(mcp: Any = None):
    """Hook to start the monitor when the MCP server initializes."""
    start_proactive_monitor()

if __name__ == "__main__":
    # For standalone testing
    async def main():
        await _monitor_markets()
    asyncio.run(main())
