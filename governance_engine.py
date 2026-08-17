"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Uses the SINGLE state-transition authority.
"""
from typing import Dict, Any
from config import DB_PATH

from schemas import TradeStatus, ActorType
from state_machine import transition_trade
import risk_management_mcp
import guardrails_mcp
import trade_memory_mcp

def screen_trade(trade_id: int) -> Dict[str, Any]:
    """
    Unified veto gate using the SINGLE state-transition authority.
    """
    # 1. Fetch the trade
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {
            "status": "ERROR",
            "reason": f"Trade {trade_id} is '{trade['status']}', must be '{TradeStatus.PROPOSED.value}'."
        }
    
    symbol = trade["symbol"]
    side = trade["side"]
    entry = trade["entry_price"]
    stop = trade["stop_loss"]
    size = trade["quantity"]
    balance = trade["portfolio_balance"]
    
    # 2. Run Risk Engine
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=symbol, side=side, entry=entry, stop=stop, size=size, portfolio_balance=balance
    )
    
    if risk_result["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.RISK_ENGINE, {"risk_result": risk_result})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": risk_result["reason"], "stage": "risk_engine"}
    
    # 3. Run Portfolio Guardrails
    exposure = guardrails_mcp.check_exposure_limit(size, entry)
    if exposure["status"] == "REJECTED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"exposure_result": exposure})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": exposure["reason"], "stage": "exposure_guardrail"}
    
    breaker = guardrails_mcp.check_circuit_breaker()
    if breaker["status"] == "TRIPPED":
        transition_trade(trade_id, TradeStatus.REJECTED, ActorType.GUARDRAIL, {"breaker_result": breaker})
        return {"status": "REJECTED", "trade_id": trade_id, "reason": breaker["reason"], "stage": "circuit_breaker"}
    
    # 4. ALL PASSED → Use SINGLE authority to transition
    transition_trade(trade_id, TradeStatus.RISK_CHECKED, ActorType.RISK_ENGINE)
    transition_trade(trade_id, TradeStatus.AWAITING_APPROVAL, ActorType.RISK_ENGINE)
    
    return {
        "status": "PASSED",
        "trade_id": trade_id,
        "message": "Trade passed all gates. Awaiting human approval.",
        "risk_check": risk_result,
        "exposure_check": exposure,
        "circuit_breaker": breaker,
        "new_status": TradeStatus.AWAITING_APPROVAL.value
    }

# In approve_and_execute_trade:
def approve_and_execute_trade(
    trade_id: int,
    execution_price: float,
    approved_by: str = "human"
) -> Dict[str, Any]:
    # 1. Fetch trade
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "message": f"Trade {trade_id} not found."}
    
    # 2. Compute hash and validate
    from schemas import TradeProposal
    proposal = TradeProposal(
        asset=trade["symbol"],
        side=trade["side"],
        entry_price=trade["entry_price"],
        stop_loss=trade["stop_loss"],
        take_profit=trade.get("take_profit"),
        quantity=trade["quantity"],
    )
    computed_hash = proposal.compute_hash()
    
    # 3. Approve using SINGLE authority
    approval_result = transition_trade(
        trade_id,
        TradeStatus.APPROVED,
        ActorType.HUMAN,
        {"approved_by": approved_by, "approval_hash": computed_hash}
    )
    
    if approval_result["status"] != "SUCCESS":
        return approval_result
    
    # 4. Execute using SINGLE authority (requires hash match)
    execution_result = transition_trade(
        trade_id,
        TradeStatus.EXECUTED,
        ActorType.HUMAN,
        {"execution_price": execution_price, "executed_by": approved_by},
        require_approval_hash=computed_hash  # This enforces the hash match
    )
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "approval": approval_result,
        "execution": execution_result,
        "proposal_hash": computed_hash
    }