"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Atomic request_approval(), approve_trade(), execute_trade().
Proposal expiration is stored and reused for deterministic hashing.
"""
import sqlite3
from typing import Dict, Any
from datetime import datetime

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
from state_machine import transition_trade
from approval_tokens import create_approval_token, validate_and_consume_token_in_transaction
import risk_management_mcp
import guardrails_mcp
import trade_memory_mcp

# ------------------------------------------------------------------
# STEP 1: REQUEST APPROVAL (ATOMIC: update trade + create token)
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Atomic: update trade with hash, policy, expiration, and create token in one transaction."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    
    try:
        trade = trade_memory_mcp.get_trade(trade_id)
        if not trade:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
        
        if trade["status"] != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback()
            conn.close()
            return {
                "status": "ERROR",
                "reason": f"Trade {trade_id} is '{trade['status']}', must be 'awaiting_approval'."
            }
        
        # Construct proposal with stored expiration
        stored_expires = trade.get("proposal_expires_at")
        if not stored_expires:
            # If missing (old migration), set a default
            expires_at = datetime.utcnow() + timedelta(hours=24)
        else:
            expires_at = datetime.fromisoformat(stored_expires)
        
        proposal = TradeProposal(
            asset=trade["symbol"],
            side=trade["side"],
            entry_price=trade["entry_price"],
            stop_loss=trade["stop_loss"],
            take_profit=trade.get("take_profit"),
            quantity=trade["quantity"],
            risk_percent=trade.get("risk_percent", 0.02),
            risk_amount=trade.get("risk_amount", 0.0),
            portfolio_balance_at_time=trade["portfolio_balance"],
            agent_reasoning=trade.get("reasoning", ""),
            risk_decision="PENDING",
            expires_at=expires_at
        )
        proposal_hash = proposal.compute_hash()
        policy_version = proposal.policy_version
        expires_at_iso = expires_at.isoformat()
        
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE trades 
            SET proposal_hash = ?, policy_version = ?, proposal_expires_at = ?
            WHERE id = ?
        """, (proposal_hash, policy_version, expires_at_iso, trade_id))
        
        if cursor.rowcount == 0:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": "Failed to update trade."}
        
        # Create approval token within the same transaction
        token_result = create_approval_token(trade_id, proposal_hash, policy_version, requested_by, conn=conn)
        
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "trade_id": trade_id,
            "approval_token": token_result["approval_token"],
            "expires_at": token_result["expires_at"],
            "proposal_hash": proposal_hash,
            "policy_version": policy_version,
            "message": "Approval requested."
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "ERROR", "reason": str(e)}

# ------------------------------------------------------------------
# STEP 2: APPROVE TRADE (ATOMIC: token consumption + hash/policy verification + state transition)
# ------------------------------------------------------------------
def approve_trade(approval_token: str, approved_by: str = "system") -> Dict[str, Any]:
    """
    Authenticates via one‑time token, verifies hash/policy match, and transitions to APPROVED.
    All in one database transaction.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    
    try:
        trade_id, token_hash, token_policy = validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Invalid, expired, or already used token."}
        
        # Fetch trade
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, status, proposal_hash, policy_version, entry_price, quantity, stop_loss,
                   risk_percent, risk_amount, portfolio_balance, proposal_expires_at, reasoning
            FROM trades WHERE id = ?
        """, (trade_id,))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
        
        (_, trade_status, trade_hash, trade_policy, entry, qty, stop,
         risk_pct, risk_amt, balance, expires_at_str, reasoning) = row
        
        if trade_status != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback()
            conn.close()
            return {
                "status": "REJECTED",
                "reason": f"Trade {trade_id} is '{trade_status}', must be 'awaiting_approval'."
            }
        
        # Verify hash and policy
        if token_hash != trade_hash:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: hash differs."}
        if token_policy != trade_policy:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "POLICY MISMATCH."}
        
        # Reconstruct proposal for expiration consistency (not needed here, but for completeness)
        expires_at = datetime.fromisoformat(expires_at_str) if expires_at_str else datetime.utcnow() + timedelta(hours=24)
        
        # Transition using the same connection
        result = transition_trade(
            trade_id,
            TradeStatus.APPROVED,
            ActorType.HUMAN,
            {"approved_by": approved_by, "proposal_hash": token_hash},
            conn=conn
        )
        
        if result["status"] != "SUCCESS":
            conn.rollback()
            conn.close()
            return result
        
        conn.commit()
        conn.close()
        
        return {
            "status": "SUCCESS",
            "trade_id": trade_id,
            "new_status": TradeStatus.APPROVED.value,
            "approved_by": approved_by,
            "proposal_hash": token_hash,
            "message": f"Trade {trade_id} approved by {approved_by}."
        }
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "ERROR", "reason": str(e)}

# ------------------------------------------------------------------
# STEP 3: EXECUTE TRADE (requires APPROVED + hash match + deterministic expiration)
# ------------------------------------------------------------------
def execute_trade(
    trade_id: int, 
    execution_price: float,
    executed_by: str = "execution_gateway"
) -> Dict[str, Any]:
    """Executes a previously approved trade. Uses stored expiration for deterministic hash."""
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    if trade["status"] != TradeStatus.APPROVED.value:
        return {
            "status": "REJECTED",
            "reason": f"Trade {trade_id} is '{trade['status']}', must be 'approved' to execute."
        }
    
    stored_hash = trade.get("proposal_hash")
    if not stored_hash:
        return {"status": "REJECTED", "reason": "No proposal hash."}
    
    # Retrieve stored expiration
    stored_expires = trade.get("proposal_expires_at")
    if not stored_expires:
        expires_at = datetime.utcnow() + timedelta(hours=24)
    else:
        expires_at = datetime.fromisoformat(stored_expires)
    
    # Reconstruct proposal with the SAME expiration
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
        risk_percent=trade.get("risk_percent", 0.02),
        risk_amount=trade.get("risk_amount", 0.0),
        portfolio_balance_at_time=trade["portfolio_balance"],
        agent_reasoning=trade.get("reasoning", ""),
        risk_decision="PASSED",
        expires_at=expires_at
    )
    computed_hash = proposal.compute_hash()
    
    if computed_hash != stored_hash:
        return {
            "status": "REJECTED",
            "reason": "PROPOSAL TAMPERED: Hash mismatch.",
            "stored": stored_hash,
            "computed": computed_hash
        }
    
    # Transition via state machine
    result = transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.EXECUTION_GATEWAY,
        {
            "execution_price": execution_price, 
            "executed_by": executed_by,
            "proposal_hash": stored_hash
        },
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
    
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=symbol, side=side, entry=entry, stop=stop, size=size, portfolio_balance=balance
    )
    if risk_result["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.RISK_ENGINE, {"risk_result": risk_result})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": risk_result["reason"], "stage": "risk_engine"}
    
    exposure = guardrails_mcp.check_exposure_limit(size, entry)
    if exposure["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"exposure_result": exposure})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": exposure["reason"], "stage": "exposure_guardrail"}
    
    breaker = guardrails_mcp.check_circuit_breaker()
    if breaker["status"] == "TRIPPED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"breaker_result": breaker})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": breaker["reason"], "stage": "circuit_breaker"}
    
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