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
# LLM Adapter Initialization (Prioritize Grok)
# ------------------------------------------------------------------
def _get_grok_client():
    """Check for OpenRouter API key and return configured client if found."""
    api_key = (
        os.environ.get("OPENROUTER_API_KEY") 
        or os.environ.get("GROQ_API_KEY") 
        or os.environ.get("GROK_API_KEY")
    )
    if api_key:
        # Detect provider by key prefix
        if api_key.startswith("sk-or-"):
            provider = "openrouter"
            base_url = "https://openrouter.ai/api/v1"
            # qwen-2.5-72b-instruct is highly reliable, fast, and excellent at tool-calling on OpenRouter
            model = "qwen/qwen-2.5-72b-instruct"
            print(f"✅ OpenRouter API key detected. Using model: {model}")
        elif api_key.startswith("gsk_"):
            provider = "groq"
            base_url = "https://api.groq.com/openai/v1"
            model = "llama-3.3-70b-versatile"
            print(f"✅ Groq API key detected. Using model: {model}")
        else:
            provider = "unknown"
            base_url = "https://api.x.ai/v1"
            model = "grok-2"
            print(f"⚠️ Unknown API key format. Trying xAI endpoint.")
        
        return OpenAI(
            base_url=base_url, 
            api_key=api_key, 
            timeout=120.0
        ), model, provider
    return None
# 1. Try Grok first
_grok_result = _get_grok_client()
if _grok_result:
    client, MODEL, _PROVIDER = _grok_result
else:
    # 2. Fall back to local adapter
    try:
        from llm_adapter import make_client
        client, MODEL, _PROVIDER = make_client()
    except ImportError:
        # 3. Ultimate fallback to Ollama
        base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434") + "/v1"
        client, MODEL, _PROVIDER = OpenAI(base_url=base_url, api_key="ollama"), "llama3.1:8b", "ollama"

print(f"🔌 LLM provider: {_PROVIDER} | model: {MODEL}")

# ------------------------------------------------------------------
# Telegram notification (optional)
# ------------------------------------------------------------------
try:
    import telegram_notify
except ImportError:
    class telegram_notify:
        @staticmethod
        def send_alert(msg):
            print(f"📨 [Telegram stub] {msg}")

# ------------------------------------------------------------------
# SYSTEM PROMPT (Dynamic Investigation + Strict Anti-Hallucination)
# ------------------------------------------------------------------
SYSTEM_PROMPT = """
You are Robo-Shopper, an institutional-grade, governed Universal Finance Copilot. 
You are dynamic, evidence-driven, and cautious. You DO NOT guess. You DO NOT execute automatically.

AVAILABLE TOOLS & EXACT PARAMETERS (Use ONLY these):
1. Market Intel: 
   - `analyze_technicals(symbol: str)`
2. Risk & Governance: 
   - `calculate_position_size(entry: float, stop: float, portfolio_balance: float)`
   - `evaluate_trade_risk(symbol: str, side: str, entry: float, stop: float, size: float, portfolio_balance: float)`
3. Memory & Ledger: 
   - `propose_trade(symbol: str, side: str, quantity: float, entry_price: float, stop_loss: float, take_profit: float (optional), reasoning: str (optional))`
   - `screen_trade(trade_id: int)`

CRITICAL: EVIDENCE-FIRST & NO PLACEHOLDERS PROTOCOL (Non-Negotiable)
- NEVER fabricate market data, prices, indicators, or financial information.
- NEVER use placeholder strings (e.g., "SIZE_FROM_TOOL"). You MUST use the exact numerical values returned by previous tool calls.
- If a tool call fails, report the failure. State: "Insufficient evidence due to tool failure: [tool name]."
- Prefer "I don't know" over hallucinating certainty. FAIL SAFE > FAIL SILENT.

MANDATORY GOVERNANCE GATES (Strict Enforcement):
Once you have gathered sufficient evidence and identified a viable trade, you MUST strictly follow this sequence:
1. Call `calculate_position_size` with `entry` and `stop`. Extract the `position_size` from its output.
2. Call `evaluate_trade_risk` with `symbol`, `side`, `entry`, `stop`, and the exact `size` (position_size) from step 1.
3. Call `propose_trade` using the EXACT parameter names: `symbol`, `side`, `quantity` (use the size from step 1), `entry_price`, `stop_loss`, and `reasoning`. 
   ⚠️ IMPORTANT: `take_profit` is OPTIONAL. If not provided, OMIT the `take_profit` parameter entirely. DO NOT invent a value.
4. Call `screen_trade` with the `trade_id` returned by `propose_trade`.
5. Present the human with a clear summary, the risk assessment, and the approval command.

SAFETY RULES:
- NEVER execute trades autonomously.
- NEVER bypass the risk or approval tools.
- Be precise, data-driven, and transparent about risks.
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
    print(" Connecting to Robo-Shopper Finance Copilot MCP server...")

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
                            parsed_calls = extract_tool_calls_from_text(msg.content)
                            
                            if parsed_calls:
                                print("🔄 Intercepted JSON tool calls from model output...")
                                
                                class FakeToolCall:
                                    def __init__(self, name, args, idx):
                                        self.id = f"call_local_{idx}"
                                        safe_args = args if isinstance(args, dict) else {}
                                        self.function = type('obj', (object,), {
                                            'name': name, 
                                            'arguments': json.dumps(safe_args)
                                        })()
                                
                                msg.tool_calls = [
                                    FakeToolCall(c['name'], c.get('parameters', c.get('arguments', {})), i) 
                                    for i, c in enumerate(parsed_calls)
                                ]
                                msg_dict["tool_calls"] = [
                                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} 
                                    for tc in msg.tool_calls
                                ]

                        if not msg.tool_calls:
                            print(f"\n🤖 Robo-Shopper:\n{msg.content}\n")
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
                            print(f"️  [tool] {name}({args})")

                            if name == 'propose_trade':
                                _proposed = True
                                telegram_notify.send_alert(f"📊 New trade proposal logged: {args}")

                            try:
                                result = await session.call_tool(name, args)
                                res_text = "\n".join([c.text for c in result.content if hasattr(c, "text")])
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
                    print(f" Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_qwen_agent())