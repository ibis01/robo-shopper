# Robo-Shopper Finance Copilot

> A governed, memory-aware trading copilot on **X Layer**, built for the
> OKX AI Genesis **Finance Copilot** category.

Robo-Shopper helps traders **analyze markets, manage decisions, automate
workflows, and act with more context** — without ever trading without a
human in the loop.

![architecture](docs/architecture.png)  <!-- add later -->

## Why it exists

Autonomous crypto bots blow up accounts. Robo-Shopper is the opposite:
an agent that *proposes*, a rulebook that *gates*, a human who *approves*,
and a ledger that *remembers*.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  THE VOICE  (monitor_service.py, 24/7, stderr alerts)       │
│   scans BTC/ETH/SOL every 60s → 🚨 on RSI<30 @ support     │
└──────────────────────────────┬──────────────────────────────┘
                               │ wakes
┌──────────────────────────────▼──────────────────────────────┐
│  THE BRAIN  (Qwen-Max via qwen_agent.py, or any MCP client) │
│   reads alert → calls tools → reasons → proposes            │
└──────────────────────────────┬──────────────────────────────┘
                               │ MCP stdio
┌──────────────────────────────▼──────────────────────────────┐
│  main_server.py  — Governed tool registry                   │
│  ┌──────────────┬──────────────┬─────────────┬────────────┐ │
│  │ market_      │ risk_        │ trade_      │ onchain_   │ │
│  │ intelligence │ management   │ memory      │ execution  │ │
│  │ +finance_    │ (2% rule,    │ (SQLite     │ (Onchain   │ │
│  │ copilot_     │  overbought  │  ledger,    │  OS CLI,   │ │
│  │ skills       │  gate)       │  feedback)  │  dry-run)  │ │
│  └──────────────┴──────────────┴─────────────┴──────────── │
└──────────────────────────────┬──────────────────────────────┘
                               │ human approves
                        🟢 BIG GREEN BUTTON
                               │
                  onchainos swap execute --chain xlayer_test
```

## Modules

| File | Role |
|---|---|
| `market_intelligence_mcp.py` | Live spot quotes, order-book metrics, RSI/SMA/support technicals |
| `finance_copilot_skills_mcp.py` | OKX perp funding/OI context + Onchain OS skill router + decision dossier |
| `risk_management_mcp.py` | 2% max-risk rule, overbought gate, dynamic position sizing |
| `trade_memory_mcp.py` | SQLite ledger: proposals, executions, PnL, hold time, human feedback |
| `onchain_execution_mcp.py` | Big Green Button swap command formatter |
| `proactive_alerts_mcp.py` | Background market scanner + terminal alerts |
| `monitor_service.py` | Standalone 24/7 Voice runner |
| `qwen_agent.py` | Qwen-Max LLM orchestrator over MCP |
| `main_server.py` | FastMCP server wiring everything together |
| `agent.yaml` | OKX AI Genesis submission manifest |

## Quickstart

```bash
cd ~/robo-shopper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Terminal 1 — the always-on Voice
nohup .venv/bin/python monitor_service.py >> voice.log 2>&1 &
tail -f voice.log

# Terminal 2 — the copilot brain (Qwen)
export DASHSCOPE_API_KEY=sk-...
export ROBO_VOICE=off
python qwen_agent.py
```

Try: *"The Voice flagged ETH oversold at support. Run the full governance
check for a 0.5 ETH buy at 1894 with a 1860 stop."*

## The governance protocol (what the agent MUST do)

1. `analyze_technicals` + `get_derivatives_context` → understand the market.
2. `get_trade_history` → learn from past mistakes and human feedback.
3. `calculate_position_size` → size to ≤2% portfolio risk.
4. `evaluate_trade_risk` → pass the rulebook gate.
5. `propose_trade` → log intent to the ledger.
6. `format_onchainos_command` → emit the CLI command, **never execute**.
7. Human runs the command → `record_execution` → later `close_trade`.

## Safety model

- **No private keys** are ever stored or used by the agent.
- **No automatic execution.** Every on-chain action is a dry-run CLI string
  the human copies into their own terminal.
- **Full audit trail.** Every proposal, approval, rejection, PnL, and piece
  of human feedback is persisted in `trades.db`.
- **Risk hard-capped.** The agent cannot propose a trade whose stop-loss
  loss exceeds 2% of the $10,000 portfolio.

## Roadmap

- [ ] Mainnet switch (`--chain xlayer`) behind a second confirmation
- [ ] OKX DEX authenticated quote for exact slippage
- [ ] Multi-agent: a separate "risk officer" agent that countersigns
- [ ] Public dashboard over `trades.db`

## License

MIT
# robo-shopper
# robo-shopper

---

## 🧬 V3 Roadmap: Economic Autonomy (In Progress)

V3 transforms Robo-Shopper from a tool into a self-sustaining economic entity:

### 1. The Agentic Treasury (Stage 1 ✅)
- **Self-Funding:** The agent controls its own wallet (`0x8d65...c1cc`).
- **Performance Tax:** It autonomously skims 2% of *realized profits* to pay for its own Groq API credits and gas fees. It pays for its own brain.

### 2. The x402 Memory Paywall (Stage 2 ✅)
- **Monetized Intelligence:** The agent exposes its SQLite trade memory via an x402-gated API.
- **Pay-to-Query:** Other agents must pay 0.05 USDC to query its historical win-rates. If they don't pay, it returns `HTTP 402 Payment Required`.

### 3. Idle Capital Sweep (Stage 3 - Coming Soon)
- **Zero Dead Capital:** Un-deployed USDT will be autonomously swept into safe X Layer yield vaults (Aave V3) while waiting for human-approved setups.
