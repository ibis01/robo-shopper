import asyncio
import logging
import sys
from functools import partial

# Keep stdout clean; alerts go to stderr (captured in voice.log)
print = partial(print, file=sys.stderr)

from proactive_alerts_mcp import _monitor_markets

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("👁️  Robo-Shopper Voice: standalone 24/7 monitor starting...")
    try:
        asyncio.run(_monitor_markets())
    except KeyboardInterrupt:
        print("🛑 Monitor stopped by user.")
