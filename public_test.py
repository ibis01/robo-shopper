import asyncio
from fastmcp import Client

URL = "https://usable-discharge-whimsical.ngrok-free.dev/sse"

async def main():
    async with Client(URL) as client:
        tools = await client.list_tools()
        print("🌍 Public menu:", [t.name for t in tools])
        r = await client.call_tool("get_btc_price", {})
        print("🤖 Live answer:", r.data if hasattr(r, "data") else r)

asyncio.run(main())