# Robo-Shopper — Governed AI Finance Copilot

**Agent proposes → rulebook gates → human approves → ledger remembers.**

Robo-Shopper is a human-governed trading copilot built on the Model Context
Protocol (MCP). It fuses market intelligence (spot, options, prediction
markets, news sentiment) with a deterministic risk engine and persistent
trade memory — and it **never moves user funds without explicit human approval**.

> ⚠️ Prototype status: paper-trading only. Not financial advice.

## Safety model (read first)

Robo-Shopper follows **Model A: human-governed copilot**.

- Execution is emitted as CLI strings with `dry_run: true` and
  `PENDING_HUMAN_APPROVAL`. The agent never holds user keys.
- Governance gates live **outside the LLM**, in deterministic code
  (`risk_management_mcp.py`): 2% max risk per trade, portfolio exposure cap,
  RSI overbought gate, mandatory stop-loss. The LLM can propose; only code can approve.
- Limited treasury autonomy: the agent manages **only its own earned treasury**
  (performance fees) to fund its operating costs. User funds are always separate.

## Architecture

y

## Features

| Capability | Module |
|---|---|
| Multi-asset intelligence (spot/options/predictions/news) | `market_intelligence_mcp.py`, `options_mcp.py`, `prediction_mcp.py`, `news_mcp.py` |
| Deterministic risk gates + ATR sizing | `risk_management_mcp.py`, `guardrails_mcp.py` |
| Trade memory with human feedback loop | `trade_memory_mcp.py` |
| Multi-TF confluence & regime detection | `confluence_mcp.py` |
| Self-sustaining economy (2% tax, x402 paywall, yield) | `treasury_mcp.py`, `treasury_yield_mcp.py`, `x402_paywall.py` |
| Mobile command center (Telegram) + TradingView webhooks | `telegram_notify.py`, `webhook_server.py` |
| LLM-agnostic (Ollama, Groq, OpenAI, OpenRouter, DashScope) | `llm_adapter.py` |
| Read-only live dashboard | `dashboard.py` |
| One-command deployment | `Dockerfile`, `docker-compose.yml` |

## Quickstart

```bash
git clone https://github.com/ibis01/robo-shopper && cd robo-shopper
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add keys as needed

# Full stack (brain 8001, paywall 8002, dashboard 8003)
docker compose up --build

# Or run the brain locally
supergateway --stdio "python main_server.py" --port 8001

# Chat with the copilot
LLM_PROVIDER=ollama LLM_MODEL=llama3.1:8b python qwen_agent.py


