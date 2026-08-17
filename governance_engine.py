"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Atomic approval: token consumption + hash verification + state transition in ONE transaction.
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
# STEP 1: REQUEST HUMAN APPROVAL
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Atomic: update trade + create token in ONE transaction."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    
    try:
        # 1. Fetch the trade
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
        policy_version = proposal.policy_version
        
        # 3. Update trade with hash and policy (within the same transaction)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE trades 
            SET proposal_hash = ?, policy_version = ?
            WHERE id = ?
        """, (proposal_hash, policy_version, trade_id))
        
        if cursor.rowcount == 0:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": "Failed to update trade."}
        
        # 4. Create the approval token (also within the same transaction)
        token_result = create_approval_token(
            trade_id, proposal_hash, policy_version, requested_by, conn=conn
        )
        
        
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
# STEP 2: HUMAN APPROVES (ATOMIC: token + hash verification + transition)
# ------------------------------------------------------------------
def approve_trade(approval_token: str, approved_by: str = "human") -> Dict[str, Any]:
    """
    Authenticates the human via one‑time token, verifies the hash matches the trade,
    and transitions to APPROVED – ALL in ONE atomic transaction.
    
    The `approved_by` is set by the system (e.g., from authenticated session).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")  # Lock the database for this critical block
    
    try:
        # 1. Validate and consume token
        trade_id, token_hash, token_policy = validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None:
            conn.rollback()
            conn.close()
            return {
                "status": "REJECTED",
                "reason": "Invalid, expired, or already used approval token."
            }
        
        # 2. Fetch the current trade within the SAME transaction
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, status, proposal_hash, policy_version, entry_price, quantity, stop_loss
            FROM trades WHERE id = ?
        """, (trade_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
        
        trade_status = row[1]
        trade_hash = row[2]
        trade_policy = row[3]
        
        # 3. Verify current status is AWAITING_APPROVAL
        if trade_status != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback()
            conn.close()
            return {
                "status": "REJECTED",
                "reason": f"Trade {trade_id} is '{trade_status}', must be 'awaiting_approval'."
            }
        
        # 4. 🔒 CRITICAL: Verify token hash matches the CURRENT trade hash
        if token_hash != trade_hash:
            conn.rollback()
            conn.close()
            return {
                "status": "REJECTED",
                "reason": "PROPOSAL MISMATCH: Token hash does not match current trade hash.",
                "token_hash": token_hash,
                "trade_hash": trade_hash
            }
        
        if token_policy != trade_policy:
            conn.rollback()
            conn.close()
            return {
                "status": "REJECTED",
                "reason": "POLICY MISMATCH: Token policy version does not match current trade.",
                "token_policy": token_policy,
                "trade_policy": trade_policy
            }
        
        # 5. Transition to APPROVED using the SAME connection
        result = transition_trade(
            trade_id,
            TradeStatus.APPROVED,
            ActorType.HUMAN,
            {"approved_by": approved_by, "proposal_hash": token_hash},
            conn=conn  # Pass the connection to stay in the same transaction
        )
        
        if result["status"] != "SUCCESS":
            conn.rollback()
            conn.close()
            return result
        
        # 6. COMMIT everything (token consumed + trade approved)
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
        return {
            "status": "ERROR",
            "reason": f"Approval failed: {str(e)}"
        }

# ------------------------------------------------------------------
# STEP 3: EXECUTE (requires APPROVED + hash match)
# ------------------------------------------------------------------
def execute_trade(
    trade_id: int, 
    execution_price: float,
    executed_by: str = "execution_gateway"
) -> Dict[str, Any]:
    """Executes a previously approved trade. Actor is strictly EXECUTION_GATEWAY."""
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
        return {
            "status": "REJECTED",
            "reason": "No proposal hash. Trade may not have been approved correctly."
        }
    
    # Recompute hash to detect tampering
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
# UNIFIED SCREEN (Risk + Guardrails)
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