#!/usr/bin/env python3
"""
Robo-Shopper V4 - Agentic Finance Copilot (Qwen/Groq/OpenRouter Adapter).
Implements the Institutional Desk UX: Agent investigates in terminal, 
human authorizes via web dashboard.
"""
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
# SYSTEM PROMPT (Institutional Desk UX + Agentic Behavior + Trust Boundary)
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
4. Governance:
   - `request_approval(trade_id: int)` - Moves trade to AWAITING_APPROVAL.
5. Execution:
   - `format_onchainos_command(trade_id: int)` - Generates dry-run CLI command for an APPROVED trade.

MANDATORY AGENTIC PROTOCOL:
1. PLAN FIRST: Always begin with a brief "Investigation Plan:".
2. CONTEXT FIRST: Check `get_trade_history(limit=5)` before calculating new position sizes.
3. STRICT DATA CHAINING: Use exact numerical values from tool outputs. NO placeholders.
4. ASSESS & SYNTHESIZE: Produce a concise decision dossier. Flag anomalies.

MANDATORY GOVERNANCE GATES (Non-Negotiable):
1. `calculate_position_size`
2. `evaluate_trade_risk`
3. `propose_trade` (EXACT parameters: `symbol`, `side`, `quantity`, `entry_price`, `stop_loss`, `reasoning`)
4. `screen_trade`
5. `request_approval` (using exact integer `trade_id`). This moves the trade to AWAITING_APPROVAL. Inform the user to approve via the Dashboard at http://localhost:8003. Do NOT ask for CLI confirmation.
6. `format_onchainos_command` (using exact integer `trade_id`) ONLY after the user confirms they have approved via the dashboard.

CRITICAL SAFETY RULES:
- NEVER fabricate market data or use placeholder strings.
- NEVER attempt to pass a portfolio_balance to risk tools. The system fetches the authoritative balance from the trusted treasury automatically.
- NEVER execute trades autonomously. Human approval is a mandatory governance boundary.
- Execution commands CANNOT be created directly from proposed parameters. Execution requires an approved trade_id.
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
                            # Only show execution prompt if trade was approved and command generated
                            if msg.content and ("onchainos" in msg.content and not _rejected):
                                telegram_notify.send_alert(msg.content)
                                print("\n✅ Trade approved and execution command generated.")
                                print("Copy the command above to execute the dry-run.")
                            break

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
                                
                                # Handle request_approval: Direct user to dashboard
                                if name == 'request_approval':
                                    res_data = json.loads(res_text) if res_text.startswith('{') else {}
                                    if res_data.get("status") == "success":
                                        trade_id = args.get("trade_id")
                                        print(f"\n🔐 Trade {trade_id} is now AWAITING_APPROVAL.")
                                        print(f"   Please review and approve via the Dashboard at http://localhost:8003")
                                        print(f"   Once approved, ask me to 'execute trade {trade_id}'.")
                                        res_text = json.dumps({
                                            "status": "success",
                                            "message": f"Trade {trade_id} awaiting dashboard approval."
                                        }, indent=2)
                                    else:
                                        print(f"❌ Approval request failed: {res_data.get('reason')}")
                                
                                # Detect rejection from screen_trade
                                if name == 'screen_trade' and 'REJECTED' in res_text.upper():
                                    _rejected = True
                                    
                            except Exception as e:
                                res_text = f"Error executing tool: {e