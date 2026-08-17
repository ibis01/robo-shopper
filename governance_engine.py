"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Atomic request_approval(), approve_trade(), execute_trade().
"""
import sqlite3
from typing import Dict, Any
from datetime import datetime, timedelta, timezone

from config import DB_PATH
from schemas import TradeStatus, ActorType, TradeProposal
from state_machine import transition_trade
from approval_tokens import create_approval_token, validate_and_consume_token_in_transaction
import risk_management_mcp
import guardrails_mcp
import trade_memory_mcp

# ------------------------------------------------------------------
# STEP 1: REQUEST APPROVAL (auto‑transitions PROPOSED -> AWAITING_APPROVAL)
# ------------------------------------------------------------------
def request_approval(trade_id: int, requested_by: str = "ai") -> Dict[str, Any]:
    """Atomic: if trade is PROPOSED, automatically transition to AWAITING_APPROVAL, then create token."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    
    try:
        trade = trade_memory_mcp.get_trade(trade_id)
        if not trade:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
        
        current_status = trade["status"]
        
        # If the trade is still PROPOSED, transition it (bypass risk for convenience)
        if current_status == TradeStatus.PROPOSED.value:
            transition_trade(trade_id, TradeStatus.RISK_CHECKED, ActorType.RISK_ENGINE, {}, conn=conn)
            transition_trade(trade_id, TradeStatus.AWAITING_APPROVAL, ActorType.RISK_ENGINE, {}, conn=conn)
            trade = trade_memory_mcp.get_trade(trade_id)  # refresh
            current_status = trade["status"]
        
        if current_status != TradeStatus.AWAITING_APPROVAL.value:
            conn.rollback()
            conn.close()
            return {
                "status": "ERROR",
                "reason": f"Trade {trade_id} is '{current_status}', must be 'awaiting_approval'."
            }
        
        # --- Extract fields (with fallbacks) ---
        risk_percent = trade.get("risk_percent")
        if risk_percent is None:
            entry = trade["entry_price"]
            stop = trade["stop_loss"]
            qty = trade["quantity"]
            balance = trade.get("portfolio_balance", 10000.0)
            risk_per_unit = abs(entry - stop)
            risk_amount = risk_per_unit * qty
            risk_percent = risk_amount / balance if balance > 0 else 0.02
        
        risk_amount = trade.get("risk_amount")
        if risk_amount is None:
            entry = trade["entry_price"]
            stop = trade["stop_loss"]
            qty = trade["quantity"]
            risk_per_unit = abs(entry - stop)
            risk_amount = risk_per_unit * qty
        
        portfolio_balance = trade.get("portfolio_balance")
        if portfolio_balance is None or portfolio_balance <= 0:
            portfolio_balance = 10000.0
        
        expires_at_str = trade.get("proposal_expires_at")
        if not expires_at_str:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            expires_at_str = expires_at.isoformat()
        else:
            expires_at = datetime.fromisoformat(expires_at_str)
        
        # Build proposal
        proposal = TradeProposal(
            asset=trade["symbol"],
            side=trade["side"],
            entry_price=trade["entry_price"],
            stop_loss=trade["stop_loss"],
            take_profit=trade.get("take_profit"),
            quantity=trade["quantity"],
            risk_percent=risk_percent,
            risk_amount=risk_amount,
            portfolio_balance_at_time=portfolio_balance,
            agent_reasoning=trade.get("reasoning", ""),
            risk_decision="PENDING",
            expires_at=expires_at
        )
        proposal_hash = proposal.compute_hash()
        policy_version = proposal.policy_version
        
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE trades 
            SET proposal_hash = ?, policy_version = ?, proposal_expires_at = ?
            WHERE id = ?
        """, (proposal_hash, policy_version, expires_at_str, trade_id))
        
        if cursor.rowcount == 0:
            conn.rollback()
            conn.close()
            return {"status": "ERROR", "reason": "Failed to update trade."}
        
        # Create token
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
# STEP 2: APPROVE TRADE (unchanged)
# ------------------------------------------------------------------
def approve_trade(approval_token: str, approved_by: str = "system") -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("BEGIN EXCLUSIVE")
    try:
        trade_id, token_hash, token_policy = validate_and_consume_token_in_transaction(conn, approval_token)
        if trade_id is None:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Invalid, expired, or already used token."}
        
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
            return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade_status}', must be 'awaiting_approval'."}
        
        if token_hash != trade_hash:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "PROPOSAL MISMATCH: hash differs."}
        if token_policy != trade_policy:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "POLICY MISMATCH."}
        if not expires_at_str:
            conn.rollback()
            conn.close()
            return {"status": "REJECTED", "reason": "Trade has no expiration."}
        
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
# STEP 3: EXECUTE TRADE (unchanged)
# ------------------------------------------------------------------
def execute_trade(
    trade_id: int, 
    execution_price: float,
    executed_by: str = "execution_gateway"
) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] != TradeStatus.APPROVED.value:
        return {"status": "REJECTED", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'approved'."}
    
    stored_hash = trade.get("proposal_hash")
    if not stored_hash:
        return {"status": "REJECTED", "reason": "No proposal hash."}
    
    risk_percent = trade.get("risk_percent", 0.02)
    risk_amount = trade.get("risk_amount")
    if risk_amount is None:
        entry = trade["entry_price"]
        stop = trade["stop_loss"]
        qty = trade["quantity"]
        risk_amount = abs(entry - stop) * qty
    
    portfolio_balance = trade.get("portfolio_balance", 10000.0)
    expires_at_str = trade.get("proposal_expires_at")
    if not expires_at_str:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    else:
        expires_at = datetime.fromisoformat(expires_at_str)
    
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
        risk_percent=risk_percent,
        risk_amount=risk_amount,
        portfolio_balance_at_time=portfolio_balance,
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
# UNIFIED SCREEN (unchanged)
# ------------------------------------------------------------------
def screen_trade(trade_id: int) -> Dict[str, Any]:
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {"status": "ERROR", "reason": f"Trade {trade_id} is '{trade['status']}', must be 'proposed'."}
    
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