"""
Robo-Shopper V4 - Formal Governance Schemas (Sprint 5).
Moves the system from loose dictionaries to strict, validated data models.
"""
from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional, Literal
from enum import Enum

# --- Enums for strict state management ---
class TradeStatus(str, Enum):
    ANALYZING = "analyzing"
    PROPOSED = "proposed"
    RISK_CHECKED = "risk_checked"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    CLOSED = "closed"

class TradeSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    
class TradeProposal(BaseModel):
    # ... existing fields
    proposal_hash: Optional[str] = Field(None, description="SHA256 hash of canonical trade for approval binding")
    
    def compute_hash(self) -> str:
        """Computes a deterministic hash of the trade proposal."""
        import hashlib
        canonical = f"{self.asset}|{self.side}|{self.entry_price}|{self.stop_loss}|{self.take_profit}|{self.quantity}"
        return hashlib.sha256(canonical.encode()).hexdigest()

# --- The Core Trade Proposal Object ---
class TradeProposal(BaseModel):
    # Metadata
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    asset: str = Field(..., description="Trading pair, e.g., BTC, ETH")
    side: TradeSide
    
    # Price levels
    entry_price: float = Field(gt=0, description="Proposed entry price")
    stop_loss: float = Field(gt=0, description="Stop loss price")
    take_profit: Optional[float] = Field(None, gt=0, description="Take profit price (optional)")
    
    # Risk calculations (deterministic)
    position_size: float = Field(gt=0, description="Quantity to trade")
    risk_amount: float = Field(gt=0, description="Dollar amount at risk")
    risk_percent: float = Field(le=0.02, description="Risk as % of portfolio (must be <= 2%)")
    portfolio_balance_at_time: float = Field(gt=0, description="Portfolio balance used for sizing")
    
    # Governance context
    market_snapshot: dict = Field(default_factory=dict, description="Technical indicators at proposal time")
    agent_reasoning: str = Field(..., description="The LLM's rationale for the trade")
    risk_decision: str = Field(..., description="PASSED or REJECTED by the risk engine")
    
    # Human-in-the-loop
    human_approval: Optional[bool] = None
    approval_timestamp: Optional[datetime] = None
    
    # Execution tracking
    execution_status: TradeStatus = Field(default=TradeStatus.PROPOSED)
    transaction_hash: Optional[str] = None
    
    # --- Validators to catch bad trades before they reach the LLM ---
    @validator('stop_loss')
    def validate_stop(cls, v, values):
        if 'side' in values and 'entry_price' in values:
            if values['side'] == TradeSide.LONG and v >= values['entry_price']:
                raise ValueError("Stop loss must be BELOW entry price for LONG trades")
            if values['side'] == TradeSide.SHORT and v <= values['entry_price']:
                raise ValueError("Stop loss must be ABOVE entry price for SHORT trades")
        return v

    @validator('risk_percent')
    def validate_risk(cls, v):
        if v > 0.02:
            raise ValueError(f"Risk per trade cannot exceed 2%! Got {v*100}%")
        return v