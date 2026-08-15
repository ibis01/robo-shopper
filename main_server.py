import treasury_mcp  # V3
import sys
from functools import partial
print = partial(print, file=sys.stderr)

import os
import threading
import asyncio
from fastmcp import FastMCP

# Import all governance modules
from market_intelligence_mcp import register_market_intelligence_tools
from trade_memory_mcp import register_trade_memory_tools
from risk_management_mcp import register_risk_management_tools
from onchain_execution_mcp import register_onchain_execution_tools
from proactive_alerts_mcp import _monitor_markets

# Initialize the MCP Server with Institutional System Prompt
mcp = FastMCP(

# V3 Treasury Injection

# V3 Treasury Registration
    "Governed Trading Copilot",
    instructions="""
    You are an institutional-grade Governed Trading Copilot. You manage a $10,000 portfolio.
    You do not execute trades blindly. You follow a strict governance protocol:
    
    1. MARKET CONTEXT: Always use `analyze_technicals` and `get_spot_quote` before proposing a trade.
    2. MEMORY: Always use `get_trade_history` to check your win/loss ratio and read past human feedback to avoid repeating mistakes.
    3. RISK GATEKEEPING: You MUST pass proposed trades through `evaluate_trade_risk`. If the decision is 'REJECTED', you must abort and explain why. If 'REQUIRES_EXTRA_CONFIRMATION', you must explicitly warn the human about the RSI/Overbought danger.
    4. MEMORY LOGGING: Before asking for approval, log the intent using `propose_trade`.
    5. EXECUTION: NEVER execute a swap directly. Use `execute_onchain_swap` to generate the exact `onchainos` CLI command. Present this command to the human and wait for them to copy/paste it into their terminal.
    6. POST-TRADE: Once the human confirms the trade filled, update the database using `record_execution`.
    """
)

# Register all tools
register_market_intelligence_tools(mcp)
register_trade_memory_tools(mcp)
register_risk_management_tools(mcp)
register_onchain_execution_tools(mcp)

# Start the proactive monitor safely in a background thread
# This prevents asyncio event loop conflicts with the FastMCP server
def start_background_monitor():
    try:

        asyncio.run(_monitor_markets())
    except KeyboardInterrupt:
        pass

monitor_thread = threading.Thread(target=start_background_monitor, daemon=True)
if os.getenv("ROBO_VOICE", "on") == "on":
    monitor_thread.start()
else:
    print("🔇 Voice disabled via ROBO_VOICE=off (standalone monitor expected).")

if __name__ == "__main__":
    print("🚀 Starting Governed Trading Copilot MCP Server...")
    print("👀 Proactive market monitor is running in the background.")
    print("🛠️  Tools registered: Market Data, Memory, Risk, On-Chain Execution.")
    treasury_mcp.register(mcp)  # V3
    mcp.run()
