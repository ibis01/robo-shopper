#!/usr/bin/env python3
"""
Robo-Shopper V4 - Centralized Governance Engine (Sprint 5).
Single authority coordinating: Proposal → Risk → Guardrails → Approval → Execution.
No execution path can bypass this engine.
"""
from typing import Dict, Any
from config import DB_PATH
from schemas import TradeStatus

# Import all governance components
import risk_management_mcp
import guardrails_mcp
import trade_memory_mcp
from state_machine import transition_status


def screen_trade(trade_id: int) -> Dict[str, Any]:
    """
    UNIFIED VETO GATE for an existing trade proposal.
    Fetches the trade from the ledger, runs ALL checks, updates the state.
    
    Flow:
    1. Fetch trade from DB.
    2. Validate current status is PROPOSED.
    3. Run Risk Engine (2% cap, RSI).
    4. Run Portfolio Guardrails (Exposure, Circuit Breaker).
    5. If all pass → update status to RISK_CHECKED → AWAITING_APPROVAL.
    6. If any fail → update status to REJECTED and return reason.
    """
    # 1. Fetch the trade
    trade = trade_memory_mcp.get_trade(trade_id)
    if not trade:
        return {"status": "ERROR", "reason": f"Trade {trade_id} not found."}
    
    if trade["status"] != TradeStatus.PROPOSED.value:
        return {
            "status": "ERROR",
            "reason": f"Trade {trade_id} is '{trade['status']}', must be '{TradeStatus.PROPOSED.value}' to screen."
        }
    
    symbol = trade["symbol"]
    side = trade["side"]
    entry = trade["entry_price"]
    stop = trade["stop_loss"]
    size = trade["quantity"]
    balance = trade["portfolio_balance"]
    
    # 2. Run Risk Engine
    risk_result = risk_management_mcp.evaluate_trade_risk(
        symbol=symbol,
        side=side,
        entry=entry,
        stop=stop,
        size=size,
        portfolio_balance=balance
    )
    
    if risk_result["status"] == "REJECTED":
        # Reject the trade
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE trades SET status = ? WHERE id = ?", (TradeStatus.REJECTED.value, trade_id))
        conn.commit()
        conn.close()
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "reason": risk_result["reason"],
            "stage": "risk_engine"
        }
    
    # 3. Run Portfolio Guardrails
    exposure = guardrails_mcp.check_exposure_limit(size, entry)
    if exposure["status"] == "REJECTED":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE trades SET status = ? WHERE id = ?", (TradeStatus.REJECTED.value, trade_id))
        conn.commit()
        conn.close()
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "reason": exposure["reason"],
            "stage": "exposure_guardrail"
        }
    
    breaker = guardrails_mcp.check_circuit_breaker()
    if breaker["status"] == "TRIPPED":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE trades SET status = ? WHERE id = ?", (TradeStatus.REJECTED.value, trade_id))
        conn.commit()
        conn.close()
        return {
            "status": "REJECTED",
            "trade_id": trade_id,
            "reason": breaker["reason"],
            "stage": "circuit_breaker"
        }
    
    # 4. ALL PASSED → Update state to RISK_CHECKED → AWAITING_APPROVAL
    trade_memory_mcp.set_risk_checked(trade_id)
    trade_memory_mcp.set_awaiting_approval(trade_id)
    
    return {
        "status": "PASSED",
        "trade_id": trade_id,
        "message": "Trade passed all governance gates and is awaiting human approval.",
        "risk_check": risk_result,
        "exposure_check": exposure,
        "circuit_breaker": breaker,
        "new_status": TradeStatus.AWAITING_APPROVAL.value
    }


def approve_and_execute_trade(
    trade_id: int, 
    execution_price: float,
    approved_by: str = "human"
) -> Dict[str, Any]:
    """
    Convenience function: Approves and executes a trade in one step.
    This is what the human triggers after reviewing the proposal.
    """
    # 1. Approve
    approval_result = trade_memory_mcp.approve_trade(trade_id, approved_by=approved_by)
    if approval_result["status"] != "success":
        return approval_result
    
    # 2. Execute
    execution_result = trade_memory_mcp.record_execution(
        trade_id=trade_id,
        execution_price=execution_price,
        executed_by=approved_by
    )
    
    return {
        "status": "success",
        "trade_id": trade_id,
        "approval": approval_result,
        "execution": execution_result,
        "message": f"Trade {trade_id} approved by {approved_by} and executed at ${execution_price:.2f}."
    }