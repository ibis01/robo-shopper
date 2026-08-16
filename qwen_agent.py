import asyncio
import json
import sys
import os

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


from llm_adapter import make_client  # V4 sprint 6
import telegram_notify
client, MODEL, _PROVIDER = make_client()
print(f"🔌 LLM provider: {_PROVIDER} | model: {MODEL}")

SYSTEM_PROMPT = """
You are an institutional-grade Governed Trading Copilot managing a $10,000 portfolio on X Layer.
You DO NOT guess.

CRITICAL: You MUST use your available tools by emitting function calls. DO NOT print JSON blocks, <json> tags, or code. Invoke the tools directly.
 You strictly follow the governance protocol using your MCP tools:
1. Always use `analyze_technicals` to assess the market.
2. Use `get_derivatives_context` for funding/OI crowding context.
3. Check `get_trade_history` to learn from past mistakes and human feedback.
4. Use `calculate_position_size` and `evaluate_trade_risk` before suggesting any trade.
5. If a trade passes risk checks, use `propose_trade` to log it.
6. Use `format_onchainos_command` ONLY to generate the CLI command for the human to run. NEVER execute it yourself.
Be concise, professional, and highly risk-aware.
"""

def mcp_to_openai_tools(mcp_tools):
    tools = []
    for t in mcp_tools:
        tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema if hasattr(t, "inputSchema") else {"type": "object", "properties": {}},
            },
        })
    return tools

async def run_qwen_agent():
    print("🔌 Connecting to Robo-Shopper Finance Copilot MCP server...")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["main_server.py"],
        env={**os.environ, "ROBO_VOICE": "off"},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ Connected. Qwen is online with all governance tools.\n")

            mcp_tools = await session.list_tools()
            openai_tools = mcp_to_openai_tools(mcp_tools.tools)

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

            while True:
                try:
                    user_input = input("\n🧑 You: ")
                    _proposed = False
                    if user_input.lower() in ("exit", "quit"):
                        break

                    messages.append({"role": "user", "content": user_input})

                    while True:
                        response = client.chat.completions.create(
                            model=MODEL,
                            messages=messages,
                            tools=openai_tools,
                            tool_choice="auto",
                            temperature=0.1,
                        )

                        msg = response.choices[0].message
                        
                        # Format message for history
                        msg_dict = {"role": msg.role, "content": msg.content}
                        if msg.tool_calls:
                            msg_dict["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
                        messages.append(msg_dict)

                        if not msg.tool_calls and msg.content:
                            # Try to parse JSON array of tool calls from content
                            try:
                                content = msg.content.strip()
                                if content.startswith("```"):
                                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                                parsed_calls = json.loads(content)
                                if isinstance(parsed_calls, list) and all(isinstance(c, dict) and 'name' in c for c in parsed_calls):
                                    print("🔄 Intercepted JSON tool calls from model output...")
                                    class FakeToolCall:
                                        def __init__(self, name, args, idx):
                                            self.id = f"call_local_{idx}"
                                            self.function = type('obj', (object,), {'name': name, 'arguments': json.dumps(args)})()
                                    msg.tool_calls = [FakeToolCall(c['name'], c.get('arguments', {}), i) for i, c in enumerate(parsed_calls)]
                                    msg_dict["tool_calls"] = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]
                            except Exception:
                                pass
                        if not msg.tool_calls:
                            print(f"\n🤖 Qwen:\n{msg.content}\n")
                            # ⚡ ONE-CLICK APPROVAL HOOK
                            if msg.content and ("onchainos" in msg.content or _proposed):
                                telegram_notify.send_alert(msg.content)
                                ans = input("\n⚡ Execute this command? [y/N]: ").strip().lower()
                                if ans in ("y", "yes"):
                                    print("✅ APPROVED - copy the command above to execute.")
                                else:
                                    print("❌ REJECTED by user.")
                            break

                        for tool_call in msg.tool_calls:
                            if getattr(tool_call.function, 'name', '') == 'propose_trade':
                                _proposed = True
                                telegram_notify.send_alert('📊 New trade proposal logged: ' + str(tool_call.function.arguments))
                            name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments or "{}")
                            print(f"🛠️  [tool] {name}({args})")

                            try:
                                result = await session.call_tool(name, args)
                                res_text = "\n".join(
                                    [c.text for c in result.content if hasattr(c, "text")]
                                )
                            except Exception as e:
                                res_text = f"Error executing tool: {e}"

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": res_text,
                            })

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_qwen_agent())
