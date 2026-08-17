"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Complete three‑step flow: request_approval() → approve_trade() → execute_trade().
Each step is separate and securely authenticated.
"""
import sqlite3
from typing import Dict, Any
from datetime import datetime

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
from state_machine import transition_trade
from approval_tokens import create_approval_token, validate_approval_token, mark_token_used
import risk_management_mcp
import guardrails_mcp
import trade_memory_mcp

# ------------------------------------------------------------------
# STEP 1: REQUEST HUMAN APPROVAL
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """
    Moves trade to AWAITING_APPROVAL, creates a one‑time token,
    stores the proposal hash for later verification.
    """
    # 1. Fetch the trade
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
        return {
            "status": "ERROR",
            "reason": f"Trade {trade_id} is '{trade['status']}', must be 'awaiting_approval'."
        }
    
    # 2. Compute proposal hash
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
        risk_percent=trade.get("risk_percent", 0.02),
        portfolio_balance_at_time=trade["portfolio_balance"],
        agent_reasoning=trade.get("reasoning", ""),
        risk_decision="PENDING"
    )
    proposal_hash = proposal.compute_hash()
    
    # 3. Store the hash and policy version in the trade
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE trades 
        SET proposal_hash = ?, policy_version = ?
        WHERE id = ?
    """, (proposal_hash, proposal.policy_version, trade_id))
    conn.commit()
    conn.close()
    
    # 4. Create the approval token
    token_result = create_approval_token(trade_id, requested_by)
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "approval_token": token_result["approval_token"],
        "expires_at": token_result["expires_at"],
        "proposal_hash": proposal_hash,
        "policy_version": proposal.policy_version,
        "message": "Approval requested. Share the token with the human approver."
    }

# ------------------------------------------------------------------
# STEP 2: HUMAN APPROVES (with token)
# ------------------------------------------------------------------
def approve_trade(trade_id: int, approval_token: str, approved_by: str = "human") -> Dict[str, Any]:
    """
    Authenticates the human via one‑time token, then transitions to APPROVED.
    """
    # 1. Validate token
    token_data = validate_approval_token(approval_token)
    if not token_data:
        return {
            "status": "REJECTED",
            "reason": "Invalid, expired, or already used approval token."
        }
    
    if token_data["trade_id"] != trade_id:
        return {
            "status": "REJECTED",
            "reason": f"Token is for trade {token_data['trade_id']}, not {trade_id}."
        }
    
    # 2. Mark token as used (prevents replay)
    if not mark_token_used(approval_token):
        return {
            "status": "REJECTED",
            "reason": "Token already used or failed to mark."
        }
    
    # 3. Transition to APPROVED (only HUMAN actor allowed)
    result = transition_trade(
        trade_id,
        TradeStatus.APPROVED,
        ActorType.HUMAN,
        {"approved_by": approved_by, "approval_timestamp": datetime.utcnow().isoformat()}
    )
    
    return result

# ------------------------------------------------------------------
# STEP 3: EXECUTE (separate, requires APPROVED + hash match)
# ------------------------------------------------------------------
def execute_trade(trade_id: int, execution_price: float, executed_by: str = "human") -> Dict[str, Any]:
    """
    Executes a previously approved trade.
    Verifies: status == APPROVED, hash matches, not already executed.
    """
    # 1. Fetch the trade
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    # 2. Must be APPROVED
    if trade["status"] != TradeStatus.APPROVED.value:
        return {
            "status": "REJECTED",
            "reason": f"Trade {trade_id} is '{trade['status']}', must be 'approved' to execute."
        }
    
    # 3. Get stored hash
    stored_hash = trade.get("proposal_hash")
    if not stored_hash:
        return {
            "status": "REJECTED",
            "reason": "No proposal hash. Trade may not have been approved correctly."
        }
    
    # 4. Recompute hash to detect tampering
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
        risk_percent=trade.get("risk_percent", 0.02),
        portfolio_balance_at_time=trade["portfolio_balance"],
        agent_reasoning=trade.get("reasoning", ""),
        risk_decision="PASSED"
    )
    computed_hash = proposal.compute_hash()
    
    if computed_hash != stored_hash:
        return {
            "status": "REJECTED",
            "reason": "PROPOSAL TAMPERED: Hash mismatch.",
            "stored_hash": stored_hash,
            "computed_hash": computed_hash
        }
    
    # 5. Transition to EXECUTED via EXECUTION_GATEWAY
    result = transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.EXECUTION_GATEWAY,
        {"execution_price": execution_price, "executed_by": executed_by},
        require_approval_hash=stored_hash
    )
    
    return result

# ------------------------------------------------------------------
# UNIFIED SCREEN (Risk + Guardrails) – uses state machine internally
# ------------------------------------------------------------------
def screen_trade(trade_id: int) -> Dict[str, Any]:
    """Runs Risk Engine + Guardrails on an existing PROPOSED trade."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {
            "status": "ERROR",
            "reason": f"Trade {trade_id} is '{trade['status']}', must be 'proposed'."
        }
    
    symbol = trade["symbol"]
    side = trade["side"]
    entry = trade["entry_price"]
    stop = trade["stop_loss"]
    size = trade["quantity"]
    balance = trade["portfolio_balance"]
    
    # 1. Risk Engine
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=symbol, side=side, entry=entry, stop=stop, size=size, portfolio_balance=balance
    )
    if risk_result["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.RISK_ENGINE, {"risk_result": risk_result})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": risk_result["reason"], "stage": "risk_engine"}
    
    # 2. Guardrails
    exposure = guardrails_mcp.check_exposure_limit(size, entry)
    if exposure["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"exposure_result": exposure})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": exposure["reason"], "stage": "exposure_guardrail"}
    
    breaker = guardrails_mcp.check_circuit_breaker()
    if breaker["status"] == "TRIPPED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"breaker_result": breaker})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": breaker["reason"], "stage": "circuit_breaker"}
    
    # 3. All passed → update state
    transition_trade(trade_id, TradeStatus.RISK_CHECKED, ActorType.RISK_ENGINE)
    transition_trade(trade_id, TradeStatus.AWAITING_APPROVAL, ActorType.RISK_ENGINE)
    
    return {
        "status": "PASSED",
        "trade_id": trade_id,
        "message": "Passed all gates. Awaiting human approval.",
        "risk_check": risk_result,
        "exposure_check": exposure,
        "circuit_breaker": breaker,
        "new_status": TradeStatus.AWAITING_APPROVAL.value
    }