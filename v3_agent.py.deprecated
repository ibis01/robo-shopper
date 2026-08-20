import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    print("Connecting to V3 on port 8001...")
    async with sse_client("http://localhost:8001/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("🛠️  Available Tools:", [t.name for t in tools.tools])
            
            if any("treasury" in t.name for t in tools.tools):
                print("\n✅ Treasury tools found! Fetching status...")
                res = await session.call_tool("get_treasury_status", {})
                print("Raw Response:", res.content[0].text)
            else:
                print("\n❌ Treasury tools missing from the list!")

asyncio.run(main())
