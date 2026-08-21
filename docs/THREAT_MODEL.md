# Robo-Shopper Threat Model

> **Scope:** Governance layer for an AI-proposed, human-approved trading copilot.
> **Status:** Paper-trading prototype. This model describes the security invariants
> enforced by the current implementation and the residual risks for real-money use.
> **Methodology:** STRIDE (Spoofing, Tampering, Repudiation, Info Disclosure, DoS, Elevation).

---

## 1. System Architecture & Trust Boundaries


**Trust boundaries:**
- **B1:** LLM agent is *untrusted*. It may propose anything; it can never approve or execute.
- **B2:** Approval token is *bearer-style but single-use*. Possession grants one approval.
- **B3:** Human approver is *semi-trusted*. They hold the token but cannot forge the proposal.
- **B4:** Execution gateway is *trusted code*. It verifies the hash before acting.

---

## 2. Asset Under Protection

| Asset | Value | Compromise Impact |
|---|---|---|
| Portfolio funds | High | Direct financial loss |
| Proposal integrity | High | Unauthorized trade parameters executed |
| Approval authority | High | AI/system self-approves trades |
| Audit trail | Medium | Repudiation, forensic blindness |
| Private keys | **Not stored** | N/A by design (agent never holds keys) |

---

## 3. Threat Catalog

### T1 — Proposal Tampering (STRIDE: Tampering)
**Attack:** Modify `quantity`, `entry_price`, `stop_loss`, or `risk_amount` after approval but before execution.
**Mitigation:** `compute_hash()` binds all material parameters via SHA-256. The hash is stored at token minting and **recomputed independently** at both `approve_trade()` and `execute_trade()`. Any field change breaks the hash → `REJECTED`.
**Status:** ✅ Mitigated. Covered by `test_modified_*` adversarial tests.

### T2 — Approval Token Replay (STRIDE: Repudiation / Elevation)
**Attack:** Capture a valid approval token and submit it multiple times.
**Mitigation:** Tokens are single-use. Consumption uses atomic `UPDATE approval_tokens SET used_at=? WHERE id=? AND used_at IS NULL`. Only the first caller gets `rowcount=1`; replays get `rowcount=0` → rejected.
**Status:** ✅ Mitigated. Covered by `test_replayed_token_fails` and `test_concurrent_approvals`.

### T3 — Expired Token Use (STRIDE: Elevation)
**Attack:** Use a token after its validity window to approve a stale proposal.
**Mitigation:** `expires_at` is checked at approval time against timezone-aware UTC. Normalized to aware datetimes to avoid naive/aware comparison crashes.
**Status:** ✅ Mitigated. Covered by `test_expired_token_fails`.

### T4 — Screening Bypass (STRIDE: Elevation)
**Attack:** Call `request_approval()` directly on a `PROPOSED` trade to skip risk/exposure/breaker checks.
**Mitigation:** `request_approval()` **rejects** any trade not already in `AWAITING_APPROVAL`. Only `screen_trade()` (running as `RISK_ENGINE`) can transition `PROPOSED → RISK_CHECKED → AWAITING_APPROVAL`.
**Status:** ✅ Mitigated. Covered by `test_governance_bypass.py`.

### T5 — Actor Impersonation (STRIDE: Spoofing)
**Attack:** AI agent or system process attempts to approve a trade (`ActorType.AI` → `APPROVED`).
**Mitigation:** `AUTHORIZED_ACTORS` table maps each transition to permitted actors. Only `ActorType.HUMAN` may transition to `APPROVED`. State machine returns `UNAUTHORIZED` for any other actor.
**Status:** ✅ Mitigated. Covered by `test_ai_cannot_approve` / `test_system_cannot_approve`.

### T6 — Race Conditions (STRIDE: DoS / Tampering)
**Attack:** Two concurrent approvals or executions interleave, causing double-spend or inconsistent state.
**Mitigation:**
- Token minting/approval uses `BEGIN EXCLUSIVE` transactions.
- State transitions use optimistic locking: `UPDATE ... WHERE id=? AND status=?`. A losing racer gets `rowcount=0` → "concurrent modification" rejection.
- `execute_trade()` is idempotent — repeated calls on an `EXECUTED` trade return `SUCCESS` with `idempotent=True`.
**Status:** ✅ Mitigated. Covered by `test_concurrent_approvals` / `test_concurrent_executions`.

### T7 — Fail-Open Authorization (STRIDE: Elevation)
**Attack:** Omit `portfolio_balance`, `risk_amount`, or `expires_at` to trigger a permissive default (e.g., assume $10,000 balance).
**Mitigation:** **Fail-closed everywhere.** Every governance boundary (`request_approval`, `approve_trade`, `execute_trade`) returns `REJECTED` if any authorization field is missing. No invented defaults at approval/execution.
**Status:** ✅ Mitigated. Defaults only exist at proposal *creation* (legitimate business logic), never at authorization.

### T8 — Policy Version Downgrade (STRIDE: Tampering)
**Attack:** Approve a trade under an old, weaker risk policy.
**Mitigation:** `policy_version` is bound into the proposal hash and the token. A mismatch between token policy and trade policy → `REJECTED`.
**Status:** ✅ Mitigated. Covered by `test_modified_policy_version_fails`.

### T9 — Expiration Extension (STRIDE: Tampering)
**Attack:** Modify `expires_at` after hashing to widen the approval window.
**Mitigation:** `expires_at.isoformat()` is included in the canonical hash string. Changing it breaks the hash.
**Status:** ✅ Mitigated. Covered by `test_modified_expiration_fails`.

### T10 — Circuit Breaker / Guardrail Failure (STRIDE: DoS)
**Attack:** Guardrail service returns `None` or crashes, causing a `TypeError` that bypasses screening.
**Mitigation:** `screen_trade()` defensively coerces `None` guardrail results to a safe `{"status": "OK"}` and checks every `transition_trade()` result before proceeding.
**Status:** ✅ Mitigated. Defensive handling verified.

---

## 4. Residual Risks (Real-Money Deployment)

| # | Risk | Severity | Mitigation Path |
|---|---|---|---|
| R1 | **Human identity not cryptographically authenticated.** `approved_by` is a string, not a verified identity. An attacker with token access could approve. | 🔴 High | Integrate OAuth / SIWE / hardware-key (WebAuthn) for approver identity. Bind approver pubkey to the token. |
| R2 | **Audit trail is JSONL** (`audit.jsonl`) — append-only but not tamper-evident. | 🟠 Medium | Migrate to an append-only event-sourcing table with hash-chaining or Merkle commitments. |
| R3 | **SQLite single-writer model.** Adequate for prototype; a distributed deployment needs a real DB with row-level locking. | 🟡 Low | Move to Postgres for multi-node before real funds. |
| R4 | **No rate limiting on token minting.** An attacker could mint many tokens for one trade. | 🟡 Low | Add per-trade token mint rate limits. (Concurrent approval is still safe — only one consumes.) |
| R5 | **Market data trust.** Risk engine consumes external prices; a manipulated feed could skew risk calc. | 🟡 Low | Use TWAP / multi-source price validation before risk evaluation. |

---

## 5. Explicit Security Assumptions

1. **The agent never holds private keys.** Execution outputs CLI commands for human copy-paste; the signing device is air-gapped from the agent.
2. **Dry-run by default.** `execute_trade()` does not move real funds in prototype mode.
3. **The deterministic rulebook is outside LLM control.** The 2% cap, exposure limits, and circuit breaker are code, not prompts — the LLM cannot argue its way past them.
4. **The treasury wallet (V3) is restricted** to fee collection and idle-yield sweep; it cannot execute discretionary trades.

---

## 6. Verification

All mitigations above are backed by an automated test suite:

