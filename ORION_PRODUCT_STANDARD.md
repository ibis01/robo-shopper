# ROBO-SHOPPER — ORION TOP-GRADE PRODUCT STANDARD

## OBJECTIVE

Transform Robo-Shopper into a polished, genuinely useful AI finance agent capable of competing for a top position in the Orion Builder Hackathon.

The goal is NOT maximum features.

The goal is:
USEFULNESS + EXECUTION + ORIGINALITY + TRUST + DEMONSTRABILITY.

---

## 1. PRODUCT DEFINITION

Robo-Shopper is an AI finance copilot that autonomously investigates financial opportunities and risks, produces evidence-backed proposals, applies deterministic risk and governance policies, and requires explicit human authorization before consequential execution.

Core principle:

AI INVESTIGATES → SYSTEM VERIFIES → POLICY GOVERNS → HUMAN AUTHORIZES → GATEWAY EXECUTES → MEMORY RECORDS.

Do not turn Robo-Shopper into a generic chatbot.

---

## 2. AGENTIC BEHAVIOR

Robo-Shopper must demonstrate genuine agent behavior.

For every meaningful task:

1. Understand the user's objective.
2. Determine what information is required.
3. Create an investigation plan.
4. Select appropriate tools.
5. Execute tools.
6. Inspect results.
7. Identify missing or suspicious information.
8. Decide whether additional investigation is necessary.
9. Synthesize evidence.
10. Produce a structured decision dossier.
11. Apply deterministic policy/risk controls.
12. Request human authorization when required.

Avoid fixed pipelines where intelligent tool selection is appropriate.

However, never allow agentic behavior to bypass deterministic safety controls.

---

## 3. EVIDENCE-FIRST INTELLIGENCE

Never fabricate financial information.

Every important claim should have provenance.

Prefer:

claim → tool → raw result → deterministic calculation → conclusion.

The UI should make evidence inspectable.

If data is unavailable, stale, contradictory, or unreliable, explicitly state this.

The agent must be comfortable saying:

"Insufficient evidence."

This is preferable to hallucinating certainty.

---

## 4. DETERMINISTIC RISK ENGINE

Financial safety decisions must remain outside LLM control.

The risk engine must deterministically enforce:

- position sizing
- portfolio exposure
- risk percentage
- maximum loss
- stop-loss requirements
- concentration limits
- circuit breakers
- policy limits
- execution constraints

The LLM may recommend.

The risk engine decides whether the proposal satisfies policy.

The LLM must never be able to override a rejected risk decision through prompting.

---

## 5. GOVERNANCE

Every consequential action must follow an explicit lifecycle:

PROPOSED
→ SCREENING
→ RISK_CHECKED
→ AWAITING_APPROVAL
→ APPROVED
→ EXECUTED
→ CLOSED

Invalid transitions must fail closed.

Approval must be tied to the exact proposal.

Changing any material field after authorization must invalidate authorization.

Approval mechanisms should support:

- expiration
- replay protection
- proposal hashing
- policy-version binding
- single-use authorization
- auditability
- idempotent execution

---

## 6. HUMAN-IN-THE-LOOP

Human approval must be meaningful.

Before approval, present:

- asset
- side
- entry
- stop
- take-profit where applicable
- position size
- portfolio exposure
- maximum risk
- policy checks
- major evidence
- agent reasoning
- warnings
- confidence/uncertainty

The user should understand exactly what they are authorizing.

Never hide material information behind the LLM.

---

## 7. SECURITY STANDARD

Treat every external input as untrusted.

Audit and defend against:

- prompt injection
- malicious market metadata
- malicious token names/symbols
- tool injection
- command injection
- SQL injection
- path traversal
- unsafe deserialization
- secret leakage
- authorization bypass
- approval replay
- race conditions
- malformed API responses
- compromised external services

Never expose private keys or seed phrases.

Never store secrets in source code.

Never give the LLM direct access to sensitive credentials.

---

## 8. OBSERVABILITY

The agent should expose a useful execution trace.

A judge should be able to see:

USER REQUEST
↓
AGENT PLAN
↓
TOOL CALL
↓
TOOL RESULT
↓
ANALYSIS
↓
ADDITIONAL INVESTIGATION
↓
RISK DECISION
↓
GOVERNANCE
↓
HUMAN APPROVAL
↓
EXECUTION
↓
AUDIT RECORD

Do not expose private chain-of-thought.

Show concise decision-relevant reasoning, evidence, tool activity, and deterministic calculations instead.

---

## 9. MEMORY

Memory must be structured and useful.

Store where appropriate:

- previous proposals
- decisions
- risk metrics
- approvals
- executions
- outcomes
- PnL
- user preferences
- policy versions
- timestamps
- feedback

Historical memory must never override current safety policies.

The system should be able to learn from outcomes without becoming unpredictable.

---

## 10. FAILURE HANDLING

Assume every external dependency can fail.

Handle:

- API timeout
- rate limit
- malformed response
- unavailable RPC
- missing market data
- stale data
- conflicting data
- database failure
- model failure
- tool failure

Never silently continue with fabricated or dangerously incomplete information.

Prefer:

FAIL SAFE > FAIL SILENT.

---

## 11. TESTING

Critical financial and governance logic must have automated tests.

Minimum coverage should include:

- risk calculations
- position sizing
- exposure limits
- state transitions
- approval generation
- token validation
- expiration
- replay prevention
- proposal hash validation
- policy mismatch
- tampering detection
- idempotency
- rejected trades
- failed tools
- missing data
- malformed data
- execution authorization

Test both normal and adversarial paths.

---

## 12. PRODUCT UX

The product must feel like a professional financial intelligence system.

Avoid unnecessary complexity.

Prioritize:

- clear hierarchy
- fast feedback
- understandable decisions
- visible evidence
- transparent risk
- obvious approval state
- useful error messages
- polished loading states
- responsive interface

A new user should understand the product within 30 seconds.

---

## 13. HERO WORKFLOW

The entire product should have one extremely polished demonstration.

Recommended flow:

User:
"Investigate ETH and determine whether a $500 position fits my current risk policy."

Robo-Shopper:

1. Understands request.
2. Investigates market.
3. Retrieves relevant data.
4. Checks portfolio context.
5. Calculates deterministic risk.
6. Identifies important risks.
7. Performs additional investigation if necessary.
8. Produces proposal.
9. Runs governance checks.
10. Presents approval request.
11. Human approves.
12. Authorization is verified.
13. Execution gateway performs a safe paper/dry-run or supported execution.
14. Result is recorded.
15. Robo-Shopper updates memory.

The complete workflow should be demonstrable in approximately 2–3 minutes.

---

## 14. HACKATHON DIFFERENTIATION

Do NOT compete by adding generic AI features.

Differentiate around:

- autonomous investigation
- evidence-backed decisions
- deterministic financial governance
- human authorization
- tamper-evident proposals
- persistent decision memory
- transparent agent traces
- measurable outcomes

The strongest product statement should communicate:

"Robo-Shopper does not blindly trust the AI. It investigates with the AI, verifies with deterministic systems, and requires human authorization before consequential action."

---

## 15. DEMO QUALITY

The demo must prove, not merely describe, the product.

Show real execution.

Avoid:

- static screenshots
- fake tool calls
- prerecorded outputs presented as live
- fabricated market data
- unexplained magic results

If a capability is simulated, label it clearly as simulated.

The judge must be able to understand what is real.

---

## 16. DOCUMENTATION

README must contain:

1. What Robo-Shopper is.
2. Why it exists.
3. Architecture.
4. Agent workflow.
5. Governance model.
6. Security model.
7. Setup.
8. Configuration.
9. Testing.
10. Demo.
11. Limitations.
12. Roadmap.

Documentation must describe the CURRENT implementation, not historical prototypes.

Remove misleading claims.

---

## 17. CODE QUALITY

Prefer:

- small modules
- explicit interfaces
- strong typing
- deterministic functions
- clear error handling
- dependency injection where useful
- structured logging
- configuration through environment variables
- automated tests

Avoid:

- duplicated implementations
- hidden global state
- magic constants
- unnecessary abstractions
- dead code
- obsolete demo paths
- inconsistent naming
- silent exceptions

There must be one canonical implementation for each critical capability.

---

## 18. QUALITY GATE

Before declaring Robo-Shopper hackathon-ready, verify:

### Agent
[ ] Genuine tool-using agent
[ ] Autonomous investigation
[ ] Robust tool selection
[ ] Evidence-backed conclusions

### Finance
[ ] Deterministic risk engine
[ ] Position sizing
[ ] Exposure controls
[ ] Policy enforcement

### Governance
[ ] Explicit state machine
[ ] Human authorization
[ ] Proposal integrity
[ ] Expiring authorization
[ ] Replay protection
[ ] Fail-closed behavior

### Security
[ ] No private-key exposure
[ ] Prompt-injection defenses
[ ] Tool security
[ ] Secret management
[ ] Authorization security

### Reliability
[ ] Automated tests
[ ] Failure handling
[ ] Idempotency
[ ] Observability
[ ] Structured audit trail

### Product
[ ] Polished UI
[ ] Clear UX
[ ] Fast hero workflow
[ ] Useful demo
[ ] Accurate documentation

### Hackathon
[ ] Strong usefulness
[ ] Strong execution
[ ] Strong originality
[ ] Clear differentiation
[ ] Working demo
[ ] GitHub ready
[ ] Website ready
[ ] X profile ready
[ ] Telegram/Discord ready

---

## FINAL PRINCIPLE

Do not optimize Robo-Shopper to LOOK impressive.

Optimize it to BE impressive when a technically competent judge tries to break it.

The final product should make the judge think:

"This is not an LLM wrapper. This is a real agent system with serious financial governance."
