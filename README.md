# Robo-Shopper — Governed AI Finance Copilot

**Agent proposes → rulebook gates → human approves → ledger remembers.**

Robo-Shopper is a human-governed trading copilot built on the Model Context
Protocol (MCP). It fuses market intelligence (spot, options, prediction
markets, news sentiment) with a deterministic risk engine and persistent
trade memory — and it **never moves user funds without explicit human approval**.

> ⚠️ Prototype status: paper-trading only. Not financial advice.

## 🛡️ Safety Model (Non-Negotiable)

Robo-Shopper is a **Human-Governed Copilot**, **not** an autonomous robot.

1. **No Private Keys**: The agent NEVER stores, touches, or uses your private keys.
2. **No Auto-Execution**: The agent ONLY outputs `onchainos` CLI commands. You copy and paste them into your own terminal.
3. **Hardcoded Veto**: The `evaluate_trade_risk` and `calculate_position_size` tools apply deterministic rules **outside** the LLM's control. Even if the LLM hallucinates a 50% risk trade, the tool forces it to respect the 2% rule.
4. **Treasury Autonomy (V3)**: The _treasury wallet_ (which collects the 2% fee) is autonomous ONLY for collecting fees and sweeping idle yield—it **never** executes discretionary trades.

## Architecture
