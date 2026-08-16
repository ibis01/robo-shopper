import json
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Import all MCP modules
import market_intelligence_mcp
import risk_management_mcp
import trade_memory_mcp
import onchain_execution_mcp
import proactive_alerts_mcp
# import finance_copilot_skills_mcp  # V2 module removed
# NEW IMPORTS
import options_mcp
import prediction_mcp
import news_mcp

server = Server("robo-shopper-universal")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        # --- Existing Tools ---
        types.Tool(name="analyze_technicals", description="Get RSI, SMA, support/resistance", inputSchema={"type": "object", "properties": {"symbol": {"type": "string"}}}),
        types.Tool(name="get_trade_history", description="Fetch past trades from SQLite", inputSchema={"type": "object", "properties": {"limit": {"type": "integer"}}}),
        types.Tool(name="calculate_position_size", description="Calculate size based on 2% risk rule", inputSchema={"type": "object", "properties": {"entry": {"type": "number"}, "stop": {"type": "number"}, "portfolio": {"type": "number"}}}),
        types.Tool(name="propose_trade", description="Log trade intent to ledger", inputSchema={"type": "object", "properties": {"symbol": {"type": "string"}, "side": {"type": "string"}, "size": {"type": "number"}, "entry": {"type": "number"}, "stop": {"type": "number"}}}),
        types.Tool(name="format_onchainos_command", description="Generate CLI command for execution", inputSchema={"type": "object", "properties": {"symbol": {"type": "string"}, "amount": {"type": "number"}}}),
        
        # --- NEW Tools (Options) ---
        types.Tool(name="get_deribit_summary", description="Get BTC/ETH option chain data from Deribit", inputSchema={"type": "object", "properties": {"currency": {"type": "string", "enum": ["BTC", "ETH"]}}}),
        types.Tool(name="suggest_option_strategy", description="Suggest option strategies based on volatility", inputSchema={"type": "object", "properties": {"currency": {"type": "string"}, "sentiment": {"type": "string"}}}),
        
        # --- NEW Tools (Prediction) ---
        types.Tool(name="get_polymarket_markets", description="Fetch live prediction markets", inputSchema={"type": "object", "properties": {"limit": {"type": "integer"}}}),
        types.Tool(name="verify_prediction_odds", description="Verify odds against reality", inputSchema={"type": "object", "properties": {"slug": {"type": "string"}}}),
        
        # --- NEW Tools (News) ---
        types.Tool(name="get_crypto_sentiment", description="Get crypto news headlines and sentiment", inputSchema={"type": "object", "properties": {"coin": {"type": "string"}}}),
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}
    
    # Route to appropriate MCP handler
    # Existing handlers...
    if name == "analyze_technicals": result = market_intelligence_mcp.analyze_technicals(args.get("symbol"))
    elif name == "get_trade_history": result = trade_memory_mcp.get_trade_history(args.get("limit"))
    elif name == "calculate_position_size": result = risk_management_mcp.calculate_position_size(args.get("entry"), args.get("stop"), args.get("portfolio"))
    elif name == "propose_trade": result = trade_memory_mcp.propose_trade(args.get("symbol"), args.get("side"), args.get("size"), args.get("entry"), args.get("stop"))
    elif name == "format_onchainos_command": result = onchain_execution_mcp.format_onchainos_command(args.get("symbol"), args.get("amount"))
    
    # NEW Handlers
    elif name == "get_deribit_summary": result = options_mcp.get_deribit_summary(args.get("currency", "BTC"))
    elif name == "suggest_option_strategy": result = options_mcp.suggest_option_strategy(args.get("currency", "BTC"), args.get("sentiment", "neutral"))
    elif name == "get_polymarket_markets": result = prediction_mcp.get_polymarket_markets(args.get("limit", 5))
    elif name == "verify_prediction_odds": result = prediction_mcp.verify_prediction_odds(args.get("slug"))
    elif name == "get_crypto_sentiment": result = news_mcp.get_crypto_sentiment(args.get("coin", "BTC"))
    else: result = f"Error: Tool {name} not found"
    
    return [types.TextContent(type="text", text=str(result))]

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="robo-shopper-universal",
                server_version="4.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())