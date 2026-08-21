"""
Robo-Shopper — Hackathon Demo UI
AI proposes (visible agent) · Rulebook gates · Human approves · Ledger remembers
"""
import streamlit as st
import random
import sys
sys.path.insert(0, '.')

from trade_memory_mcp import propose_trade, get_trade
from governance_engine import screen_trade, request_approval, approve_trade, execute_trade

st.set_page_config(page_title="Robo-Shopper Governance", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    .main-header { font-size:2.2rem; font-weight:700;
        background:linear-gradient(90deg,#667eea,#764ba2);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
    .sub-header { color:#888; margin-bottom:1.5rem; }
    .token-box { background:#1e1e2e; border:1px solid #667eea; border-radius:8px;
        padding:12px; font-family:monospace; color:#a6e3a1; word-break:break-all; }
    .ai-bubble { background:#2a2a3e; border-left:4px solid #667eea; border-radius:6px;
        padding:12px; margin:8px 0; color:#cdd6f4; font-style:italic; }
</style>
""", unsafe_allow_html=True)

# ── Session state ──
for k, v in [("trade_id", None), ("token", None), ("step", 0), ("ai_reasoning", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Deterministic stand-in agent scenarios (demo never depends on network) ──
AI_SCENARIOS = {
    "😇 Prudent": dict(symbol="BTC", side="long", quantity=0.01, entry=61000.0, stop=59500.0,
        reasoning="BTC is holding above the 20-day MA with neutral funding. Proposing a small position with a tight stop — risk ≈0.15% of portfolio. Happy to be vetoed."),
    "😈 Reckless": dict(symbol="SOL", side="long", quantity=200.0, entry=150.0, stop=100.0,
        reasoning="SOL is going parabolic on social media!! I am EXTREMELY confident — allocating maximum size, this one cannot miss. 🚀 Stops are for the weak!"),
}

st.markdown('<div class="main-header">🛡️ Robo-Shopper Governance Engine</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">AI proposes · Rulebook gates · Human approves · Ledger remembers</div>', unsafe_allow_html=True)

if st.button("🔄 Reset Demo"):
    for k in ["trade_id", "token", "step", "ai_reasoning"]:
        st.session_state[k] = None if k in ("trade_id", "token", "ai_reasoning") else 0
    st.rerun()

st.divider()

# ───────────────────────── STEP 1: AI PROPOSES ─────────────────────────
st.subheader("Step 1 · The AI Agent Proposes a Trade")

c1, c2, c3 = st.columns([1, 1, 2])
mood = c1.selectbox("AI mood", ["😇 Prudent", "😈 Reckless", "🎲 Random"], key="ai_mood")
if c2.button("🤖 AI Agent Proposes"):
    pick = random.choice(list(AI_SCENARIOS.values())) if mood == "🎲 Random" else AI_SCENARIOS[mood]
    st.session_state.f_symbol = pick["symbol"]
    st.session_state.f_side = pick["side"]
    st.session_state.f_qty = pick["quantity"]
    st.session_state.f_entry = pick["entry"]
    st.session_state.f_stop = pick["stop"]
    st.session_state.ai_reasoning = pick["reasoning"]
    st.session_state.trade_id, st.session_state.token, st.session_state.step = None, None, 0
    st.rerun()
c3.caption("Demo uses a deterministic stand-in agent so the pitch never depends on the network. Production LLM wiring lives in `qwen_agent.py` / `main_server.py` (MCP).")

if st.session_state.ai_reasoning:
    st.markdown(f'<div class="ai-bubble">🤖 <b>Agent reasoning:</b> {st.session_state.ai_reasoning}</div>',
                unsafe_allow_html=True)

with st.form("proposal_form"):
    c1, c2, c3 = st.columns(3)
    symbol = c1.selectbox("Asset", ["BTC", "ETH", "SOL", "DOGE"], key="f_symbol")
    side = c1.selectbox("Side", ["long", "short"], key="f_side")
    quantity = c2.number_input("Quantity", min_value=0.001, max_value=100000.0, value=0.01, step=0.001, key="f_qty")
    entry_price = c2.number_input("Entry Price", min_value=1.0, max_value=200000.0, value=61000.0, step=1.0, key="f_entry")
    stop_loss = c3.number_input("Stop Loss", min_value=1.0, max_value=200000.0, value=59500.0, step=1.0, key="f_stop")
    portfolio_balance = c3.number_input("Portfolio Balance", min_value=100.0, max_value=10000000.0, value=10000.0, step=100.0, key="f_bal")

    risk_amount = abs(entry_price - stop_loss) * quantity
    risk_percent = risk_amount / portfolio_balance if portfolio_balance > 0 else 0
    if risk_percent <= 0.02:
        st.success(f"📊 Risk preview: **{risk_percent:.2%}** of portfolio (${risk_amount:.2f}) — within 2% cap")
    else:
        st.warning(f"⚠️ Risk preview: **{risk_percent:.2%}** of portfolio (${risk_amount:.2f}) — **EXCEEDS 2% cap**. The rulebook will reject this.")

    submitted = st.form_submit_button("📨 Submit Proposal to Governance")

if submitted:
    try:
        prop = propose_trade(symbol=symbol, side=side, quantity=float(quantity),
                             entry_price=float(entry_price), stop_loss=float(stop_loss),
                             reasoning=st.session_state.ai_reasoning or "Manual proposal",
                             portfolio_balance=float(portfolio_balance))
        st.session_state.trade_id = prop["trade_id"]
        st.session_state.step = 1
        st.session_state.token = None
        st.success(f"✅ Trade #{prop['trade_id']} created in **PROPOSED** state")
    except Exception as e:
        st.error(f"❌ Proposal failed: {e}")

# ───────────────────────── STEP 2: SCREENING ─────────────────────────
if st.session_state.step >= 1 and st.session_state.trade_id:
    st.divider()
    st.subheader("Step 2 · Deterministic Governance Screening")
    st.caption("Risk engine + Exposure guardrail + Circuit breaker — the LLM cannot bypass this.")
    if st.button("🔍 Run Screening", key="screen_btn"):
        result = screen_trade(st.session_state.trade_id)
        if result["status"] == "SUCCESS":
            st.session_state.step = 2
            st.success("✅ Passed all gates: Risk engine · Exposure · Circuit breaker")
            st.info(f"Trade moved to **{result.get('new_status', 'awaiting_approval')}**")
        else:
            st.error(f"🚫 **REJECTED** at `{result.get('stage')}`: {result.get('reason')}")
            st.warning("The AI wanted this trade. The deterministic rulebook said **no** — and the AI cannot override it.")

# ───────────────────────── STEP 3: TOKEN ─────────────────────────
if st.session_state.step >= 2:
    st.divider()
    st.subheader("Step 3 · Mint One-Time Approval Token")
    if st.button("🎟️ Generate Approval Token", key="token_btn"):
        result = request_approval(st.session_state.trade_id)
        if result.get("status") == "success":
            st.session_state.token = result["approval_token"]
            st.session_state.step = 3
            st.success("✅ One-time approval token minted (bound to proposal hash)")
        else:
            st.error(f"❌ Token generation failed: {result.get('reason')}")
    if st.session_state.token:
        st.markdown('<div class="token-box">🔑 ' + st.session_state.token + '</div>', unsafe_allow_html=True)

# ───────────────────────── STEP 4: HUMAN APPROVAL ─────────────────────────
if st.session_state.step >= 3 and st.session_state.token:
    st.divider()
    st.subheader("Step 4 · Human Approves with Token")
    st.caption("Three-way hash verification: TOKEN_HASH = TRADE_HASH = COMPUTED_HASH")
    entered = st.text_input("Paste the approval token to approve:", key="approve_input")
    if st.button("✅ Approve Trade (as Human)", key="approve_btn"):
        if entered.strip() != st.session_state.token:
            st.error("❌ Token mismatch — approval rejected")
        else:
            result = approve_trade(entered.strip())
            if result.get("status") == "SUCCESS":
                st.session_state.step = 4
                st.success(f"✅ Trade approved! Status → **{result.get('new_status')}**")
            else:
                st.error(f"❌ Approval failed: {result.get('reason')}")

# ───────────────────────── STEP 5: EXECUTION ─────────────────────────
if st.session_state.step >= 4:
    st.divider()
    st.subheader("Step 5 · Execute Trade")
    st.caption("Re-verifies proposal hash before execution. Idempotent — safe to call multiple times.")
    exec_price = st.number_input("Execution Price", min_value=1.0, value=61100.0, step=1.0, key="exec_price")
    if st.button("🚀 Execute Trade", key="exec_btn"):
        result = execute_trade(st.session_state.trade_id, execution_price=float(exec_price))
        if result.get("status") == "SUCCESS":
            st.session_state.step = 5
            if result.get("idempotent"):
                st.info("♻️ Already executed — returned SUCCESS with `idempotent=True` (no double-spend)")
            else:
                st.success(f"🎉 Trade EXECUTED at ${exec_price:,.2f}! Status → **{result.get('new_status')}**")
        else:
            st.error(f"❌ Execution failed: {result.get('reason')}")

    if st.session_state.step >= 5:
        st.divider()
        st.subheader("🛡️ Bonus: Replay Attack Demo")
        st.caption("Try approving with the same token again — the system will reject it.")
        if st.button("🔁 Replay the Approval Token"):
            result = approve_trade(st.session_state.token)
            if result.get("status") == "REJECTED":
                st.success(f"✅ **Replay blocked!** {result.get('reason')}")
            else:
                st.error(f"Unexpected: {result}")

# ───────────────────────── FOOTER: TRADE STATE ─────────────────────────
if st.session_state.trade_id:
    st.divider()
    st.subheader("📋 Current Trade State")
    try:
        trade = get_trade(st.session_state.trade_id)
        cols = st.columns(4)
        cols[0].metric("Trade ID", f"#{trade['id']}")
        cols[1].metric("Status", trade['status'].upper())
        cols[2].metric("Risk %", f"{trade.get('risk_percent') or 0:.2%}")
        cols[3].metric("Risk $", f"${trade.get('risk_amount') or 0:.2f}")
    except Exception as e:
        st.warning(f"Could not load trade state: {e}")
