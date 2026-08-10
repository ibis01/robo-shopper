# Submission pitch — Robo-Shopper Finance Copilot

## One-liner
A governed, memory-aware trading copilot on X Layer that enforces a 2%
risk rulebook and only ever acts through human-approved Onchain OS commands.

## The problem
Every "autonomous trading agent" demoed in 2025 has the same failure mode:
it has no memory of its own mistakes, no hard risk limit, and no human
override. When it's wrong, it's wrong repeatedly and expensively.

## Our answer
Robo-Shopper separates the four jobs a finance copilot must do, and makes
each one auditable:

- **Analyze** — live spot + derivatives context (funding, OI, crowding bias)
  from public Binance/OKX data, plus RSI/SMA/support technicals.
- **Decide** — an explicit rulebook: ≤2% portfolio risk per trade, an
  overbought gate that forces extra confirmation, and dynamic position
  sizing from the stop distance.
- **Remember** — a SQLite ledger of every proposal, execution, PnL, hold
  time, and crucially the *human's feedback* on each trade, so the agent
  reads its own history before proposing again.
- **Act** — never directly. The agent emits an `onchainos ... --chain
  xlayer_test` command; the human runs it. That's the Big Green Button.

A background "Voice" scans BTC/ETH/SOL every 60 seconds and surfaces
setups (e.g. RSI < 30 at support) without being asked.

## Why X Layer / OKX
We format every execution as an **Onchain OS** command targeting
`xlayer_test`, ready to flip to `xlayer` mainnet behind a second
confirmation. Market context comes from OKX's public perpetual API
(funding + open interest), giving the agent the same derivatives signal
professional desks use.

## How it differs from the other Finance Copilot winners
- vs **LEAPSY** (options depth): we cover governed *spot* execution with
  memory, complementary to options positioning.
- vs **Serenity** (research): we turn research-grade context into a
  *gated, executable* decision, not just a summary.
- vs **PolyDesk** (prediction markets): we bring the same governed-workspace
  ethos to on-chain spot trading on X Layer, with a persistent trade ledger.

## Demo
`./scripts/demo.sh` prints a full governed decision dossier in one command.
A 90-second screen recording is linked in `agent.yaml`.

## Safety
No private keys. No auto-execution. Full audit trail in `trades.db`.
Hard 2% risk cap enforced in code, not in a prompt.
