#!/usr/bin/env python3
"""
Robo-Shopper V4 - Universal MCP Tool Registry.
Exposes ALL tools: Market Intel, Risk, Memory, Execution, Governance.
Governance is enforced via explicit tool routing.
TRUST BOUNDARY: Portfolio balance is never accepted from LLM.
"""
import json
import asyncio
import logging
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
# 1. TOOL REGISTRY (Canonical Schemas)
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
        # ---------- RISK & GOVERNANCE ----------
        types.Tool(
            name="calculate_position_size",
            description="Calculate position size based on the 2% hard risk cap and real portfolio balance",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry": {"type": "number", "description": "Proposed entry price"},
                    "stop": {"type": "number", "description": "Stop loss price"}
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
                    "rsi_override": {"type": "number", "description": "Optional RSI override for testing"}
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
                    "symbol": {"type": "string", "description": "Trading pair (BTC, ETH, SOL)"},
                    "side": {"type": "string", "enum": ["long", "short"], "description": "Trade direction"},
                    "quantity": {"type": "number", "description": "Position size in base asset units"},
                    "entry_price": {"type": "number", "description": "Proposed entry price"},
                    "stop_loss": {"type": "number", "description": "Stop loss price"},
                    "take_profit": {"type": "number", "description": "Optional take profit price"},
                    "reasoning": {"type": "string", "description": "Agent reasoning for the trade"}
                },
                "required": ["symbol", "side", "quantity", "entry_price", "stop_loss"]
            }
        ),
        # ---------- GOVERNANCE: REQUEST APPROVAL ----------
        types.Tool(
            name="request_approval",
            description="Request human approval for a screened trade. Returns an approval token that must be confirmed by the human. DO NOT call this unless the trade has passed screen_trade.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trade_id": {"type": "integer", "description": "The ID of the trade to approve."}
                },
                "required": ["trade_id"]
            }
        ),
        # ---------- EXECUTION (DRY-RUN ONLY, GATED) ----------
        types.Tool(
            name="format_onchainos_command",
            description="Generate a dry-run CLI command for an APPROVED trade. REQUIRES an approved trade_id. DO NOT pass raw parameters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trade_id": {"type": "integer", "description": "The ID of the APPROVED trade."}
                },
                "required": ["trade_id"]
            }
        ),
    ]
    return tools

# ------------------------------------------------------------------
# 2. TOOL ROUTING (Direct Pass-Through)
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
            result = await market_intelligence_mcp.analyze_technicals(
                symbol=args.get("symbol", "BTC")
            )

        # ---------- RISK & GOVERNANCE ----------
        elif name == "calculate_position_size":
            result = risk_management_mcp.calculate_position_size(
                entry=args.get("entry"),
                stop=args.get("stop")
            )

        elif name == "evaluate_trade_risk":
            result = risk_management_mcp.evaluate_trade_risk(
                symbol=args.get("symbol"),
                side=args.get("side"),
                entry=args.get("entry"),
                stop=args.get("stop"),
                size=args.get("size"),
                rsi_override=args.get("rsi_override")
            )

        # ---------- MEMORY ----------
        elif name == "get_trade_history":
            result = trade_memory_mcp.get_trade_history(args.get("limit", 10))

        elif name == "propose_trade":
            result = trade_memory_mcp.propose_trade(
                symbol=args.get("symbol"),
                side=args.get("side"),
                quantity=args.get("quantity"),
                entry_price=args.get("entry_price"),
                stop_loss=args.get("stop_loss"),
                take_profit=args.get("take_profit"),
                reasoning=args.get("reasoning", "")
            )

        # ---------- GOVERNANCE: REQUEST APPROVAL ----------
        elif name == "request_approval":
            from governance_engine import request_approval
            result = request_approval(args.get("trade_id"))

        # ---------- EXECUTION (DRY-RUN ONLY) ----------
        elif name == "format_onchainos_command":
            from governance_engine import generate_execution_command
            result = generate_execution_command(args.get("trade_id"))

        else:
            raise ValueError(f"Unknown tool: {name}")

        # Format successful result for MCP
        if isinstance(result, dict):
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        return [types.TextContent(type="text", text=str(result))]

    except Exception as exc:
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