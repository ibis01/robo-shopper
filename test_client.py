
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def show(result):
    for block in result.content:
        try:
            print(json.dumps(json.loads(block.text), indent=2))
        except Exception:
            print(block.text)
    print("-" * 70)


async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["main_server.py"],
        cwd="/home/ibismuh/robo-shopper",
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("REGISTERED TOOLS:", [t.name for t in tools.tools])
            print("=" * 70)

            print("1) analyze_technicals(ETH, 15m)  <- follow-up on the alert")
            show(await session.call_tool("analyze_technicals", {"symbol": "ETH", "timeframe": "15m"}))

            print("2) get_trade_history()  <- check memory first")
            show(await session.call_tool("get_trade_history", {}))

            print("3) calculate_position_size(entry=1894, stop=1860)")
            show(await session.call_tool("calculate_position_size", {
                "entry_price": 1894.0,
                "stop_loss_price": 1860.0,
            }))

            print("4) evaluate_trade_risk(buy ETH)  <- risk gate")
            show(await session.call_tool("evaluate_trade_risk", {
                "side": "buy",
                "technicals": {"rsi_14": 25.66, "signal": "Oversold"},
                "proposed_amount": 0.5,
                "entry_price": 1894.0,
                "stop_loss_price": 1860.0,
            }))

            print("5) propose_trade(ETH buy)  <- log intent to memory")
            show(await session.call_tool("propose_trade", {
                "symbol": "ETH",
                "side": "buy",
                "amount": 0.5,
                "proposed_price": 1894.0,
            }))

            print("6) execute_onchain_swap(USDC -> WETH)  <- Big Green Button")
            show(await session.call_tool("execute_onchain_swap", {
                "token_in": "USDC",
                "token_out": "WETH",
                "amount": 100,
            }))


asyncio.run(main())
