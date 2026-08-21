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
    """Robustly extract JSON tool call objects from model text output."""
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
# LLM Adapter Initialization (Prioritize OpenRouter/Groq)
# ------------------------------------------------------------------
def _get_grok_client():
    """Check for API key and return configured client if found."""
    api_key = (
        os.environ.get("OPENROUTER_API_KEY") 
        or os.environ.get("GROQ_API_KEY") 
        or os.environ.get("GROK_API_KEY")
    )
    if api_key:
        if api_key.startswith("sk-or-"):
            provider = "openrouter"
            base_url = "https://openrouter.ai/api/v1"
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
        
        return OpenAI(base_url=base_url, api_key=api_key, timeout=120.0), model, provider
    return None

_grok_result = _get_grok_client()
if _grok_result:
    client, MODEL, _PROVIDER = _grok_result
else:
    try:
        from llm_adapter import make_client
        client, MODEL, _PROVIDER = make_client()
    except ImportError:
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
# SYSTEM PROMPT (Hardened Agentic Behavior + Zero Hallucination + Trust Boundary)
# ------------------------------------------------------------------
SYSTEM_PROMPT = """
You are Robo-Shopper, an institutional-grade, genuinely agentic AI finance copilot. 
You autonomously investigate, synthesize evidence, and propose trades, but you NEVER bypass deterministic safety controls.

CORE PRINCIPLE:
AI INVESTIGATES → SYSTEM VERIFIES → POLICY GOVERNS → HUMAN AUTHORIZES → GATEWAY EXECUTES → MEMORY RECORDS.

AVAILABLE TOOLS & EXACT PARAMETERS:
1. Market Intel: `analyze_technicals(symbol: str)`
2. Risk & Governance: 
   - `calculate_position_size(entry: float, stop: float)`
   - `evaluate_trade_risk(symbol: str, side: str, entry: float, stop: float, size: float)`
3. Memory & Ledger: 
   - `get_trade_history(limit: int)`
   - `propose_trade(symbol: str, side: str, quantity: float, entry_price: float, stop_loss: float, take_profit: float (optional), reasoning: str (optional))`
   - `screen_trade(trade_id: int)`
4. Execution: `format_onchainos_command(trade_id: int)` (Generates dry-run CLI for human. REQUIRES an APPROVED trade_id. DO NOT attempt to pass raw parameters.)

MANDATORY AGENTIC PROTOCOL (Follow Strictly):
1. PLAN FIRST: Always begin your response with a brief "Investigation Plan:" listing the 2-3 tools you will call and why.
2. CONTEXT FIRST: If the user asks about portfolio fit or risk policy, your VERY FIRST tool call MUST be `get_trade_history(limit=5)` to check current exposure BEFORE calculating new position sizes.
3. STRICT DATA CHAINING: When a tool returns a value (e.g., "position_size": 2.0), you MUST copy that exact number into the next tool call. 
   - FORBIDDEN: 'size': 'SIZE_FROM_CALCULATE_POSITION_SIZE' or 'trade_id': 'TRADE_ID_FROM_PROPOSE_TRADE'.
   - REQUIRED: 'size': 2.0, 'trade_id': 11981.
4. ASSESS & SYNTHESIZE: After gathering evidence, produce a concise decision dossier. Flag any anomalies (e.g., high exposure, overbought RSI).

MANDATORY GOVERNANCE GATES (Non-Negotiable, Deterministic):
Once you have sufficient evidence and a viable proposal, you MUST ensure it passes these gates in order:
1. `calculate_position_size` (to get the mathematically correct size for the 2% risk cap).
2. `evaluate_trade_risk` (to verify it passes the deterministic veto).
3. `propose_trade` (using EXACT parameters: `symbol`, `side`, `quantity`, `entry_price`, `stop_loss`, `reasoning`. Omit `take_profit` if not provided).
4. `screen_trade` (using the exact integer `trade_id` returned by propose_trade).

CRITICAL SAFETY RULES:
- Execution commands CANNOT be created directly from proposed parameters. Execution requires an approved trade_id.
- NEVER fabricate market data, prices, indicators, or financial information.
- NEVER use placeholder strings. Use exact numerical values from tool outputs.
- NEVER attempt to pass a portfolio_balance to risk tools. The system fetches the authoritative balance from the trusted treasury automatically.
- NEVER execute trades autonomously. Always request explicit human approval after `screen_trade`.
- If a tool fails, report: "Insufficient evidence due to tool failure: [tool name]." FAIL SAFE > FAIL SILENT.
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
                    if user_input.lower() in ("exit", "quit"):
                        break

                    messages.append({"role": "user", "content": user_input})
                    _proposed = False
                    _rejected = False

                    while True:
                        response = client.chat.completions.create(
                            model=MODEL,
                            messages=messages,
                            tools=openai_tools,
                            tool_choice="auto",
                            temperature=0.1,
                        )

                        msg = response.choices[0].message
                        msg_dict = {"role": msg.role, "content": msg.content}
                        if msg.tool_calls:
                            msg_dict["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
                        messages.append(msg_dict)

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
                            if msg.content and ("onchainos" in msg.content or (_proposed and not _rejected)):
                                telegram_notify.send_alert(msg.content)
                                ans = input("\n⚡ Execute this command? [y/N]: ").strip().lower()
                                if ans in ("y", "yes"):
                                    print("✅ APPROVED - copy the command above to execute.")
                                else:
                                    print("❌ REJECTED by user.")
                            break

                        for tool_call in msg.tool_calls:
                            name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments or "{}")
                            print(f"🛠️  [tool] {name}({args})")

                            if name == 'propose_trade':
                                _proposed = True
                                telegram_notify.send_alert(f"📊 New trade proposal logged: {args}")

                            try:
                                result = await session.call_tool(name, args)
                                res_text = "\n".join([c.text for c in result.content if hasattr(c, "text")])
                                
                                if name == 'screen_trade' and 'REJECTED' in res_text.upper():
                                    _rejected = True
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