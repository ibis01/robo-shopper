# Robo-Shopper: Governed AI Finance Copilot

**Agent Investigates → System Verifies → Policy Governs → Human Authorizes → Gateway Executes → Memory Records.**

Robo-Shopper is a human-governed, genuinely agentic trading copilot built on the Model Context Protocol (MCP). It fuses dynamic market intelligence with a deterministic risk engine and persistent trade memory. It is **not** an autonomous trading bot; it is a verifiable, evidence-first decision engine that **never moves user funds without explicit human approval**.

> ⚠️ **Prototype Status:** Paper-trading and dry-run execution only. Not financial advice.

## 🏆 Orion Hackathon Alignment

| Criterion           | Implementation in Robo-Shopper                                                                                                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agentic Quality** | Dynamically plans investigations, checks trade history _before_ sizing, assesses confidence, and detects anomalies (e.g., high exposure) before proposing.                                  |
| **Security**        | Zero private key handling. Strict input validation. Tamper-evident cryptographic proposal hashing. One-time, expiring approval tokens. External data sanitization against prompt injection. |
| **Reliability**     | 48/48 adversarial, concurrency, and risk tests passing. Explicit "Insufficient evidence" fail-closed protocol. No silent hallucinations.                                                    |
| **Observability**   | Every decision generates a persistent, human-readable "Decision Dossier" in the web UI, tracing evidence, risk metrics, and authorization.                                                  |
| **Execution**       | Canonical, deterministic tool routing. The LLM _cannot_ bypass the 2% per-trade risk cap or 20% portfolio exposure cap.                                                                     |

## 🛡️ Safety Model (Non-Negotiable)

1. **No Private Keys**: The agent NEVER stores, touches, or uses private keys.
2. **No Auto-Execution**: The agent ONLY outputs dry-run CLI commands. Human copy-paste is required.
3. **Deterministic Veto**: Risk calculations (`calculate_position_size`, `evaluate_trade_risk`) are executed in Python, entirely outside the LLM's control. The LLM cannot be prompted to bypass the 2% risk or 20% exposure caps.
4. **Tamper-Evident Governance**: Human approval is cryptographically bound to the exact proposal hash and policy version. If any parameter changes post-approval, execution is instantly rejected.
5. **Prompt Injection Defense**: All external market metadata (symbols, exchange names) is sanitized and length-limited before reaching the LLM context.

## 🏗️ Architecture

1. **LLM Agent (`qwen_agent.py`)**: Plans investigations, gathers evidence via MCP tools, synthesizes findings, and proposes trades.
2. **MCP Server (`main_server.py`)**: Canonical tool registry and direct pass-through routing.
3. **Market Intelligence (`market_intelligence_mcp.py`)**: Live data via CCXT (with Yahoo Finance failover).
4. **Risk Engine (`risk_management_mcp.py`)**: Hardcoded financial vetoes (2% risk, 20% exposure). Purely deterministic.
5. **Governance (`governance_engine.py`)**: State machine, proposal hashing, and one-time approval tokens.
6. **Memory (`trade_memory_mcp.py`)**: SQLite ledger with full lifecycle tracking.
7. **Observability (`dashboard.py`)**: FastAPI web UI featuring the Decision Dossier.

## 🚀 Quick Start

1. **Clone & Install**:
   ```bash
   git clone https://github.com/ibis01/robo-shopper.git
   cd robo-shopper
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
