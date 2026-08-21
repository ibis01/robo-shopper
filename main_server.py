#!/usr/bin/env python3
"""
Robo-Shopper V4 - Universal MCP Tool Registry (Sprint 5).
Exposes ALL tools: Market Intel, Risk, Memory, Execution, Options, Prediction, News.
Governance is enforced via explicit tool routing.
"""
import json
import asyncio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# --- Import all MCP modules ---
import market_intelligence_mcp
import trade_memory_mcp
import risk_management_mcp
import onchain_execution_mcp
import guardrails_mcp

# Initialize the MCP Server
server = Server("robo-shopper-universal")

# ------------------------------------------------------------------
# 1. TOOL REGISTRY (All available functions)
# ------------------------------------------------------------------
@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    tools = [
        # ---------- UNIFIED VETO GATE ----------
        types.Tool(
            name="screen_trade",
            description="UNIFIED VETO GATE: Runs an existing trade proposal (by ID) through Risk Engine + Portfolio Guardrails + Circuit Breaker. Updates the trade state to AWAITING_APPROVAL if PASSED, or REJECTED if failed. This is the FINAL arbiter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trade_id": {"type": "integer", "description": "The ID of the trade proposal to screen."}
                },
                "required": ["trade_id"]
            }
        ),
        # ---------- MARKET INTELLIGENCE ----------
        types.Tool(
            name="analyze_technicals",
            description="Get RSI, MACD, SMA, and support/resistance for BTC/ETH/SOL",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "enum": ["BTC", "ETH", "SOL"]}
                },
                "required": ["symbol"]
            }
        ),
        # ---------- RISK & GOVERNANCE (HARDENED) ----------
        types.Tool(
            name="calculate_position_size",
            description="Calculate position size based on the 2% hard risk cap and real portfolio balance",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry": {"type": "number", "description": "Proposed entry price"},
                    "stop": {"type": "number", "description": "Stop loss price"},
                    "portfolio_balance": {"type": "number", "description": "Optional override for portfolio balance (defaults to DB)"}
                },
                "required": ["entry", "stop"]
            }
        ),
        types.Tool(
            name="evaluate_trade_risk",
            description="HARDCODED VETO GATE. Checks RSI overbought/oversold, portfolio exposure, and validates stop/entry. Returns PASSED or REJECTED with reason.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "enum": ["BTC", "ETH", "SOL"]},
                    "side": {"type": "string", "enum": ["long", "short"]},
                    "entry": {"type": "number"},
                    "stop": {"type": "number"},
                    "size": {"type": "number"},
                    "portfolio_balance": {"type": "number"}
                },
                "required": ["symbol", "side", "entry", "stop", "size"]
            }
        ),
        # ---------- MEMORY & LEDGER ----------
        types.Tool(
            name="get_trade_history",
            description="Retrieve past trades with P&L, human feedback, and reasoning from SQLite ledger",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10}
                }
            }
        ),
        types.Tool(
            name="propose_trade",
            description="Log the trade intent into the ledger (status: PROPOSED)",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["long", "short"]},
                    "size": {"type": "number", "description": "Position size in base asset units"},
                    "entry": {"type": "number", "description": "Proposed entry price"},
                    "stop": {"type": "number", "description": "Stop loss price"},
                    "take_profit": {"type": "number", "description": "Optional take profit price"},
                    "reasoning": {"type": "string", "description": "Agent reasoning for the trade"}
                },
                "required": ["symbol", "side", "size", "entry", "stop"]
            }
        ),
        # ---------- EXECUTION (DRY-RUN ONLY) ----------
        types.Tool(
            name="format_onchainos_command",
            description="Generate a dry-run CLI command for the human to copy and execute. NEVER executes automatically.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "amount": {"type": "number"},
                    "slippage": {"type": "number", "default": 0.5}
                },
                "required": ["symbol", "side", "amount"]
            }
        ),
    ]
    return tools

# ------------------------------------------------------------------
# 2. TOOL ROUTING (Executes the actual logic)
# ------------------------------------------------------------------
@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}
    result = None

    try:
        # ---------- UNIFIED SCREEN ----------
        if name == "screen_trade":
            from governance_engine import screen_trade
            result = screen_trade(args.get("trade_id"))

        # ---------- MARKET INTELLIGENCE ----------
        elif name == "analyze_technicals":
            # P0 FIX: Added 'await' because the underlying function is async.
            result = await market_intelligence_mcp.analyze_technicals(
                symbol=args.get("symbol", "BTC")
            )

        # ---------- RISK & GOVERNANCE ----------
        elif name == "calculate_position_size":
            result = risk_management_mcp.calculate_position_size(
                entry=args.get("entry"),
                stop=args.get("stop"),
                portfolio_balance=args.get("portfolio_balance")
            )

        elif name == "evaluate_trade_risk":
            result = risk_management_mcp.evaluate_trade_risk(
                symbol=args.get("symbol"),
                side=args.get("side"),
                entry=args.get("entry"),
                stop=args.get("stop"),
                size=args.get("size"),
                portfolio_balance=args.get("portfolio_balance")
            )

        # ---------- MEMORY ----------
        elif name == "get_trade_history":
            result = trade_memory_mcp.get_trade_history(args.get("limit", 10))

        elif name == "propose_trade":
            # CRITICAL FIX: Map LLM schema names (size, entry, stop) to actual Python function parameters
            result = trade_memory_mcp.propose_trade(
                symbol=args.get("symbol"),
                side=args.get("side"),
                quantity=args.get("size"),       # LLM sends 'size', function expects 'quantity'
                entry_price=args.get("entry"),   # LLM sends 'entry', function expects 'entry_price'
                stop_loss=args.get("stop"),      # LLM sends 'stop', function expects 'stop_loss'
                take_profit=args.get("take_profit"),
                reasoning=args.get("reasoning", "")
            )

        elif name == "format_onchainos_command":
            # Safe dry-run command generation
            result = {
                "status": "success", 
                "command": f"onchainos {args.get('side', 'buy')} {args.get('amount', 0)} {args.get('symbol', 'BTC')}"
            }

        else:
            raise ValueError(f"Unknown tool: {name}")

        # Format successful result for MCP
        if isinstance(result, dict):
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        return [types.TextContent(type="text", text=str(result))]

    except Exception as exc:
        # P0 FIX: Return explicit error to LLM to trigger "Insufficient evidence" protocol
        import logging
        logging.exception(f"Tool {name} failed")
        error_msg = (
            f"ERROR: Tool '{name}' failed with exception: {str(exc)}. "
            "Do not guess or fabricate data. State 'Insufficient evidence due to tool failure'."
        )
        return [types.TextContent(type="text", text=error_msg)]

# ------------------------------------------------------------------
# 3. SERVER ENTRYPOINT
# ------------------------------------------------------------------
async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="robo-shopper-universal",
                server_version="5.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())