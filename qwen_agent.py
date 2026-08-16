import asyncio
import json
import sys
import os

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --- LLM Adapter (either import your own or use the stub below) ---
try:
    from llm_adapter import make_client
except ImportError:
    # Stub for direct Ollama (or OpenAI-compatible) use
    def make_client():
        base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434") + "/v1"
        return OpenAI(base_url=base_url, api_key="ollama"), "llama3.1:8b", "ollama"

# Telegram notification (optional)
try:
    import telegram_notify
except ImportError:
    # Stub
    class telegram_notify:
        @staticmethod
        def send_alert(msg):
            print(f"📨 [Telegram stub] {msg}")

client, MODEL, _PROVIDER = make_client()
print(f"🔌 LLM provider: {_PROVIDER} | model: {MODEL}")

SYSTEM_PROMPT = """
You are Robo-Shopper, an institutional-grade, governed Universal Finance Copilot managing a $10,000 portfolio on X Layer.
You DO NOT guess. You DO NOT execute automatically.

You have these tool categories:
1. Market Intel: `analyze_technicals` (spot prices, RSI, MACD, support/resistance).
2. Derivatives: `get_derivatives_context` (funding rates, open interest).
3. Options: `get_deribit_summary` (BTC/ETH option chains), `suggest_option_strategy`.
4. Prediction Markets: `get_polymarket_markets` (live odds), `verify_prediction_odds`.
5. News/Sentiment: `get_crypto_sentiment` (headlines, sentiment score).
6. Risk & Memory: `get_trade_history` (learn from past trades), `calculate_position_size` (2% max risk), `evaluate_trade_risk`.
7. Execution: `propose_trade` (log intent), `format_onchainos_command` (generate CLI for human).

You MUST follow this strict 7-step governance protocol for ANY trade proposal:
1. Call `analyze_technicals` + `get_derivatives_context` to understand market conditions.
2. Call `get_trade_history` to learn from past mistakes and human feedback.
3. Call `calculate_position_size` to size the trade within the 2% risk budget.
4. Call `evaluate_trade_risk` to pass the rulebook gates.
5. Call `propose_trade` to log the intention into the SQLite ledger.
6. Call `format_onchainos_command` to generate a CLI command for the human. NEVER execute it.
7. Wait for the human to run the command and call `record_execution` later.

When a user asks about:
- Options (e.g., "BTC options") → call `get_deribit_summary` first.
- Predictions (e.g., "Polymarket, election odds") → call `get_polymarket_markets`.
- News (e.g., "what's the news on ETH") → call `get_crypto_sentiment`.

For standard spot/futures trades (BTC/ETH/SOL), always stick to the 7-step protocol above.

You are running locally with Llama 3.1. Be precise, data-driven, cautious, and transparent. Never hide risk.
"""

def mcp_to_openai_tools(mcp_tools):
    tools = []
    for t in mcp_tools:
        # MCP tools have .name, .description, .inputSchema (dict)
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
                    if user_input.lower() in ("exit", "quit"):
                        break

                    messages.append({"role": "user", "content": user_input})
                    _proposed = False  # Track if a trade was proposed in this turn

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

                        # If no tool_calls, check if content contains JSON tool calls (fallback)
                        if not msg.tool_calls and msg.content:
                            try:
                                content = msg.content.strip()
                                if content.startswith("```"):
                                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                                parsed_calls = json.loads(content)
                                if isinstance(parsed_calls, list) and all(isinstance(c, dict) and 'name' in c for c in parsed_calls):
                                    print("🔄 Intercepted JSON tool calls from model output...")
                                    # Create fake ToolCall objects
                                    class FakeToolCall:
                                        def __init__(self, name, args, idx):
                                            self.id = f"call_local_{idx}"
                                            self.function = type('obj', (object,), {'name': name, 'arguments': json.dumps(args)})()
                                    msg.tool_calls = [FakeToolCall(c['name'], c.get('arguments', {}), i) for i, c in enumerate(parsed_calls)]
                                    msg_dict["tool_calls"] = [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]
                            except Exception:
                                pass

                        if not msg.tool_calls:
                            # Final response from the model
                            print(f"\n🤖 Robo-Shopper:\n{msg.content}\n")
                            # ONE-CLICK APPROVAL HOOK
                            if msg.content and ("onchainos" in msg.content or _proposed):
                                telegram_notify.send_alert(msg.content)
                                ans = input("\n⚡ Execute this command? [y/N]: ").strip().lower()
                                if ans in ("y", "yes"):
                                    print("✅ APPROVED - copy the command above to execute.")
                                else:
                                    print("❌ REJECTED by user.")
                            break

                        # Process tool calls
                        for tool_call in msg.tool_calls:
                            name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments or "{}")
                            print(f"🛠️  [tool] {name}({args})")

                            if name == 'propose_trade':
                                _proposed = True
                                telegram_notify.send_alert(f"📊 New trade proposal logged: {args}")

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