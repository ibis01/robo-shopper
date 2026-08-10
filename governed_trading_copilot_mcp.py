from mcp.server.fastmcp import FastMCP

from market_intelligence_mcp import register_market_intelligence_tools
from trade_memory_mcp import TradeMemory, register_trade_memory_tools

mcp = FastMCP("Governed Trading Copilot")

memory = TradeMemory()

register_market_intelligence_tools(mcp)
register_trade_memory_tools(mcp, memory)

if __name__ == "__main__":
    mcp.run()
