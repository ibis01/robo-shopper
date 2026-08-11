# Resubmission Note — Robo-Shopper v2 (Finance Copilot)

Previous submission: Robo-Shopper v1.
This is not a new entry — it is a full architectural upgrade of our
existing ASP into the Finance Copilot category.

## What v1 had
- Single-purpose MCP tools, no persistent memory
- No risk governance, no human-in-the-loop execution model

## What v2 adds (mapped to the category criteria)
1. **ANALYZE** — live spot + derivatives context (OKX funding/OI),
   RSI/SMA/support technicals, geo-block-resilient data layer
   (ccxt → Yahoo Finance fallback).
2. **DECIDE** — rulebook enforced in code: ≤2% portfolio risk per trade,
   overbought/oversold gates, position sizing from stop distance.
3. **REMEMBER** — SQLite ledger of every proposal, execution, PnL, hold
   time and human feedback; the agent reads its own history first.
4. **ACT** — never autonomously: emits Onchain OS CLI commands for
   `xlayer_test`; the human is the Big Green Button.
5. **VOICE** — 24/7 background scanner that surfaces setups proactively.

## Why re-judge us
v1 proved we can ship an MCP agent. v2 proves we can ship a *governed* one.
Same team, same repo, now institutional-grade.
