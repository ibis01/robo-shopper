# Robo-Shopper

**A Human-Governed AI Finance Agent with Deterministic Risk Controls**

> _"Robo-Shopper does not blindly trust the AI. It investigates with the AI, verifies with deterministic systems, and requires human authorization before consequential action."_

## 🎯 What It Is

Robo-Shopper is an AI finance copilot that autonomously investigates financial opportunities, produces evidence-backed proposals, applies deterministic risk and governance policies, and requires explicit human authorization before execution.

It solves the "black box" problem of AI trading agents by separating concerns: the LLM handles investigation and synthesis, while deterministic code handles risk calculation, policy enforcement, and cryptographic execution gating.

**Core Pipeline:**

```
AI INVESTIGATES → SYSTEM VERIFIES → POLICY GOVERNS → HUMAN AUTHORIZES → GATEWAY EXECUTES → MEMORY RECORDS
```

## 🚀 Why It Exists

Most AI trading agents are dangerous black boxes that blindly trust LLM outputs for financial execution. If the LLM hallucinates a risk metric or ignores a stop-loss, the user loses money.

Robo-Shopper moves AI agents from demos to real products by enforcing **trust through architecture**:

- **AI investigates** market conditions and proposes trades.
- **Deterministic code** calculates risk and enforces policy (2% risk cap, 20% exposure cap).
- **Cryptographic state machine** gates every transition.
- **Human approves** via a secure institutional dashboard.
- **Execution gateway** generates dry-run commands using database-authoritative values only.

## 🏗️ Architecture

```text
┌─────────────────
│   User Request  │
└────────────────┘
         ▼
┌─────────────────┐
│  Agent Plan &   │
│  Tool Selection │
└────────────────┘
         ▼
┌─────────────────┐      ┌──────────────────┐
│  Evidence       │─────▶│  Risk Engine     │
│  Gathering      │      │  (Deterministic) │
└─────────────────┘      └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │  Governance      │
                         │  State Machine   │
                         └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │  Human Approval  │
                         │  (Dashboard)     │
                         └────────┬─────────┘
                                  ▼
                         ┌──────────────────┐
                         │  Execution       │
                         │  Gateway         │
                         └─────────────────┘
                                  ▼
                         ┌──────────────────┐
                         │  Audit Memory    │
                         └──────────────────┘
```

## 🤖 Agent Workflow

Robo-Shopper demonstrates genuine agentic behavior, not just a chatbot interface:

1. **Understands Objective:** Parses natural language queries (e.g., _"Investigate BTC long 0.01 at entry 60000 stop 59500"_).
2. **Plans Investigation:** Determines what market data and portfolio context is required.
3. **Gathers Evidence:** Uses MCP tools to fetch real market data and portfolio balances.
4. **Synthesizes Proposal:** Produces a structured decision dossier with entry, stop-loss, and reasoning.
5. **Applies Policy:** Passes the proposal to the deterministic risk engine. The LLM cannot override a rejection.

## 🔐 Governance & Security Model

### State Machine

Every trade follows an explicit, fail-closed lifecycle:

```text
PROPOSED → RISK_CHECKED → AWAITING_APPROVAL → APPROVED → EXECUTED → CLOSED
                ↓                ↓
            REJECTED         REJECTED (fail-closed)
```

Invalid transitions are rejected. The state machine enforces legal transitions, authorized actors per state, and atomic updates via SQLite WAL mode.

### Cryptographic Authorization

- **Proposal Hash:** SHA-256 hash of all material trade parameters.
- **One-Time Tokens:** Single-use approval tokens with 1-hour expiration.
- **Tamper Detection:** Hash is independently recomputed and verified at _both_ the approval and execution stages.
- **Replay Protection:** Tokens are cryptographically marked as used after consumption.
- **Policy Binding:** Tokens are bound to the specific policy version active at the time of minting.

### Non-Negotiable Safety

- ❌ Never exposes private keys or seed phrases.
- ❌ LLM cannot bypass deterministic risk controls.
- ❌ LLM cannot directly execute discretionary trades.
- ❌ No secrets stored in source code.
- ✅ Human approval is cryptographically bound to the exact proposal.
- ✅ Fails closed on missing, invalid, expired, or inconsistent authorization data.

## ⚙️ Setup & Configuration

### One-Command Setup

We provide a bulletproof setup script that handles environment initialization, dependency resolution, and database creation.

```bash
git clone <repository-url>
cd robo-shopper
./setup.sh
```

### Manual Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env to set DEV_MODE=1 for local development

# Initialize database
python reset_db.py
```

### Configuration

Environment variables are managed via `.env`:

- `DEV_MODE=1`: Enables default test credentials and bypasses strict secret requirements for local demos.
- `DB_PATH`: Path to the SQLite database (default: `data/trades.db`).
- `DASHBOARD_API_KEY` / `SESSION_SECRET`: Security credentials for the web dashboard.

## 🧪 Testing

Critical financial and governance logic is covered by automated tests. We test both normal and adversarial paths to ensure the system fails safely under pressure.

```bash
# Run full test suite
pytest tests/ -v

# Run specific categories
pytest tests/test_security.py -v
pytest tests/test_governance.py -v
```

**Current Status:** 95/95 tests passing (100% pass rate). Coverage includes risk calculations, state transitions, approval token validation, replay prevention, proposal hash validation, and tampering detection.

## 🎬 Hero Workflow (Demo)

The complete workflow is demonstrable in approximately 2–3 minutes.

**1. Start the Dashboard**

```bash
DEV_MODE=1 python dashboard.py
# Visit http://localhost:8003
```

**2. Agent Investigates**

```bash
python main.py
# Enter: Investigate BTC long 0.01 at entry 60000 stop 59500
```

**3. Human Approval**
Refresh the dashboard. The new trade appears in "Pending Approvals". Review the dossier (asset, side, entry, stop-loss, risk amount, policy checks) and click **Approve**.

**4. Execution Gateway**

```bash
python -c "from governance_engine import execute_trade; print(execute_trade(<trade_id>, 60100))"
```

**5. Tamper Detection (The "Judge Breaker")**

```bash
# Maliciously alter the quantity in the database
sqlite3 data/trades.db "UPDATE trades SET quantity = 999.0 WHERE id = <trade_id>;"

# Attempt to execute the tampered trade
python -c "from governance_engine import execute_trade; print(execute_trade(<trade_id>, 60100))"
# Output: REJECTED - PROPOSAL TAMPERED: Hash mismatch.
```

## ⚠️ Limitations & Honesty

To maintain absolute transparency for judges and users:

- **Paper-Trading Only:** The execution gateway generates dry-run commands. There are no live blockchain transactions or live exchange API executions in this repository.
- **Simulated Treasury:** Portfolio balance is managed in a local SQLite database for demonstration purposes.
- **Asset Scope:** Currently supports BTC, ETH, and SOL spot markets.
- **Single-User Dashboard:** HttpOnly cookie authentication is sufficient for a local demo, but not designed for multi-tenant SaaS production.

## Roadmap

- [ ] Live exchange API integration (sandbox mode).
- [ ] Multi-asset support (derivatives, DeFi protocols).
- [ ] Advanced risk models (VaR, Sharpe ratio, correlation limits).
- [ ] Real-time market data streaming via WebSockets.
- [ ] Multi-user dashboard with role-based access control (RBAC).
- [ ] On-chain execution integration via Starknet/STRK20.

## 🔗 Orion Integration Readiness

Robo-Shopper is designed to be deployed as a verified agent on the Orion network.

- **Deterministic Outputs:** The risk engine ensures the agent never hallucinates financial parameters.
- **Structured Tool Use:** The agent's investigation trace (plan → tool call → result → deterministic calculation) is fully observable and auditable.
- **Safe Execution:** The execution gateway is built for dry-run validation today, with a clear path to connect to live Orion-compatible execution endpoints tomorrow.

## 📄 License

MIT License. See `LICENSE` file for details.

---

**⚠️ Disclaimer:** This is a paper-trading/demonstration system built for the Orion Builder Hackathon. Do not use for live trading without proper exchange integration, additional security audits, and regulatory compliance review.
# TradeGuard-AI
