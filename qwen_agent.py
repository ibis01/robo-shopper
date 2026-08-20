import asyncio
import json
import sys
import os
import re

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ------------------------------------------------------------------
# HELPER: Robust tool call extraction from text
# ------------------------------------------------------------------
def extract_tool_calls_from_text(text: str):
    """
    Robustly extract JSON tool call objects from model text output.
    Handles nested JSON objects and ignores conversational text.
    """
    calls = []
    decoder = json.JSONDecoder()
    # Look for JSON objects that contain a 'name' key
    for match in re.finditer(r'\{', text):
        start = match.start()
        try:
            obj, end = decoder.raw_decode(text, start)
            if isinstance(obj, dict) and 'name' in obj:
                calls.append(obj)
        except json.JSONDecodeError:
            continue
    return calls

# ------------------------------------------------------------------
# LLM Adapter (Configured for Grok API)
# ------------------------------------------------------------------
try:
    from llm_adapter import make_client
except ImportError:
    # Stub for Grok API (OpenAI-compatible)
    def make_client():
        # Grok uses XAI_API_KEY or GROK_API_KEY
        api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("Missing GROK_API_KEY or XAI_API_KEY environment variable.")
        
        base_url = "https://api.x.ai/v1"
        model_name = "grok-2-latest"  # You can also use "grok-beta"
        return OpenAI(base_url=base_url, api_key=api_key), model_name, "grok"

# ------------------------------------------------------------------
# Telegram notification (optional)
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# SYSTEM PROMPT (Dynamic Investigation + Strict Anti-Hallucination)
# ------------------------------------------------------------------
SYSTEM_PROMPT = """
You are Robo-Shopper, an institutional-grade, governed Universal Finance Copilot. 
You are dynamic, evidence-driven, and cautious. You DO NOT guess. You DO NOT execute automatically.

AVAILABLE TOOLS (Use ONLY these):
1. Market Intel: `analyze_technicals` (RSI, MACD, SMA for BTC/ETH/SOL)
2. Options: `get_deribit_summary` (Live option chains)
3. Risk & Governance: `screen_trade`, `calculate_position_size`, `evaluate_trade_risk`
4. Memory & Ledger: `get_trade_history`, `propose_trade`
5. Execution: `format_onchainos_command` (Generates dry-run CLI for human)

CRITICAL: EVIDENCE-FIRST & FAILURE PROTOCOL (Non-Negotiable)
- NEVER fabricate market data, prices, indicators, or financial information.
- If a tool call fails, returns an error, or indicates data is unavailable, you MUST report the failure to the user.
- DO NOT substitute fabricated values for missing data.
- If evidence is unavailable, state: "Insufficient evidence due to tool failure: [tool name]."
- Do not guess technical indicators, funding rates, or market conditions.
- Prefer "I don't know" over hallucinating certainty. FAIL SAFE > FAIL SILENT.

INVESTIGATION PROTOCOL (Dynamic):
- Analyze the user's intent and dynamically select the best tools from the list above.
- Synthesize the evidence clearly. 

MANDATORY GOVERNANCE GATES (Strict Enforcement):
Once you have gathered sufficient evidence and identified a viable trade, you MUST strictly follow this sequence:
1. Call `calculate_position_size` to ensure the trade respects the 2% max risk budget.
2. Call `evaluate_trade_risk` to pass the deterministic rulebook veto gate.
3. Call `propose_trade` to log the intention into the SQLite ledger.
4. Call `screen_trade` to run the unified veto gate (Risk Engine + Guardrails + Circuit Breaker).
5. Present the human with a clear summary and the approval command.

SAFETY RULES:
- NEVER execute trades autonomously.
- NEVER bypass the risk or approval tools.
- Be precise, data-driven, and transparent about risks.
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
                            # USE THE NEW HELPER FUNCTION HERE
                            parsed_calls = extract_tool_calls_from_text(msg.content)
                            
                            if parsed_calls:
                                print("🔄 Intercepted JSON tool calls from model output...")
                                
                                # Create fake ToolCall objects to integrate with the existing loop
                                class FakeToolCall:
                                    def __init__(self, name, args, idx):
                                        self.id = f"call_local_{idx}"
                                        # Handle both 'parameters' and 'arguments' keys from LLM output
                                        safe_args = args if isinstance(args, dict) else {}
                                        self.function = type('obj', (object,), {
                                            'name': name, 
                                            'arguments': json.dumps(safe_args)
                                        })()
                                
                                msg.tool_calls = [
                                    FakeToolCall(
                                        c['name'], 
                                        c.get('parameters', c.get('arguments', {})), 
                                        i
                                    ) for i, c in enumerate(parsed_calls)
                                ]
                                msg_dict["tool_calls"] = [
                                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} 
                                    for tc in msg.tool_calls
                                ]

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