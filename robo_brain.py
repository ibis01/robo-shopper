import json
import hashlib
import os
from datetime import datetime, timezone
from openai import OpenAI

client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
MODEL = "qwen2.5-coder:14b"

# --- 📓 The Magic Diary (tamper-evident mini-chain) ---
AUDIT_FILE = "audit.jsonl"
last_hash = "0" * 16
if os.path.exists(AUDIT_FILE):
    with open(AUDIT_FILE) as f:
        lines = f.read().strip().splitlines()
        if lines:
            last_hash = json.loads(lines[-1]).get("hash", last_hash)

def diary(event, details):
    global last_hash
    entry = {"time": datetime.now(timezone.utc).isoformat(),
             "event": event, "details": details, "prev": last_hash}
    last_hash = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:16]
    entry["hash"] = last_hash
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"   ✍️  Diary: {event} (#{last_hash})")

# --- The robot's hands ---
def get_option_expiries():
    return "The next 3 option expiration dates are: Sept 27, Oct 25, and Nov 22."

def propose_trade(contract, side, amount):
    diary("proposal", {"contract": contract, "side": side, "amount": amount})
    MAX_AUTO_APPROVE, ABSOLUTE_LIMIT = 500.0, 1000.0
    print(f"\n📜 RULEBOOK CHECK: {side} ${amount} of {contract}")

    if amount > ABSOLUTE_LIMIT:
        diary("rejected_by_rulebook", {"contract": contract, "amount": amount})
        return "REJECTED by Rulebook: over the $1000 absolute limit."

    if amount > MAX_AUTO_APPROVE:
        print("   ⚠️  Over auto-approve limit. Waiting for human...")
        if input("   🟢 Approve? (y/n): ").lower() != "y":
            diary("human_rejected", {"contract": contract, "amount": amount})
            return "REJECTED by human. Trade cancelled."
        diary("human_approved", {"contract": contract, "amount": amount})
    else:
        diary("auto_approved", {"contract": contract, "amount": amount})

    diary("executed", {"contract": contract, "side": side, "amount": amount})
    return f"SUCCESS: {side} ${amount} of {contract} executed!"

TOOLS = {"get_option_expiries": get_option_expiries, "propose_trade": propose_trade}

SYSTEM_PROMPT = """You are Robo-Shopper, a crypto options assistant.
Tools available: get_option_expiries, propose_trade.

RULES:
1. To use a tool, reply with EXACTLY this line: TOOL_CALL: tool_name(arg1, arg2)
   Example: TOOL_CALL: propose_trade(BTC-Sept-27, buy, 750)
2. Only call propose_trade when the user explicitly asks to make a trade.
3. When you get the tool result, give a friendly final answer."""

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": "Hey Robo! Buy $750 worth of the Sept 27 options."},
]

print("🧠 Robo-Shopper is waking up...")

for step in range(6):
    resp = client.chat.completions.create(model=MODEL, messages=messages, temperature=0.0)
    reply = resp.choices[0].message.content.strip()

    if "TOOL_CALL:" in reply:
        raw_call = reply.split("TOOL_CALL:")[-1].strip().splitlines()[0].strip()
        print(f"🦾 Robot wants to run: {raw_call}")
        try:
            name, args_str = raw_call.split("(", 1)
            args = [a.strip().strip("'\"") for a in args_str.rstrip(")").split(",")]
            name = name.strip()
            if name == "propose_trade":
                result = propose_trade(args[0], args[1], float(args[2]))
            else:
                result = TOOLS[name]()
        except Exception as e:
            result = f"Error parsing tool call: {str(e)}"
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": f"Here is the result for {name}: {result}"})
    else:
        messages.append({"role": "assistant", "content": reply})
        print("\n🤖 Robo-Shopper final answer:\n", reply)
        break