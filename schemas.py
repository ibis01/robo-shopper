"""
Robo-Shopper V4 - Formal Governance Schemas (Sprint 5).
Single source of truth for all data models.
"""
from pydantic import BaseModel, Field, validator
from datetime import datetime, timedelta
from typing import Optional, Literal
from enum import Enum
import hashlib

from config import POLICY_VERSION, PROPOSAL_EXPIRY_HOURS

# --- Enums ---
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

class ActorType(str, Enum):
    SYSTEM = "system"
    AI = "ai"
    HUMAN = "human"
    RISK_ENGINE = "risk_engine"
    GUARDRAIL = "guardrail"
    EXECUTION_GATEWAY = "execution_gateway"

# --- The Core Trade Proposal (SINGLE DEFINITION) ---
class TradeProposal(BaseModel):
    # Metadata
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    asset: str
    side: TradeSide
    
    # Prices
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: Optional[float] = Field(None, gt=0)
    
    # Sizing & Risk
    quantity: float = Field(gt=0)
    risk_amount: float = Field(gt=0)
    risk_percent: float = Field(le=0.02)
    portfolio_balance_at_time: float = Field(gt=0)
    
    # Governance
    market_snapshot: dict = Field(default_factory=dict)
    agent_reasoning: str
    risk_decision: str
    
    # Human approval
    human_approval: Optional[bool] = None
    approval_timestamp: Optional[datetime] = None
    
    # Execution
    execution_status: TradeStatus = Field(default=TradeStatus.PROPOSED)
    transaction_hash: Optional[str] = None
    
    # --- SECURITY: Proposal hash & policy binding ---
    proposal_hash: Optional[str] = None
    policy_version: str = POLICY_VERSION
    chain_id: str = "x-layer"
    venue: str = "onchainos"
    wallet_address: Optional[str] = None
    
    # Expiration
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(hours=PROPOSAL_EXPIRY_HOURS)
    )
    
    # --- Validators ---
    @validator('stop_loss')
    def validate_stop(cls, v, values):
        if 'side' in values and 'entry_price' in values:
            if values['side'] == TradeSide.LONG and v >= values['entry_price']:
                raise ValueError("Stop loss must be BELOW entry for LONG")
            if values['side'] == TradeSide.SHORT and v <= values['entry_price']:
                raise ValueError("Stop loss must be ABOVE entry for SHORT")
        return v

    @validator('risk_percent')
    def validate_risk(cls, v):
        if v > 0.02:
            raise ValueError(f"Risk {v*100}% exceeds 2% cap")
        return v
    

def compute_hash(self) -> str:
    """Deterministic SHA-256 hash binding ALL materially relevant parameters."""
    canonical = "|".join([
        self.chain_id,
        self.venue,
        self.wallet_address or "0x",
        self.asset,
        self.side.value,
        str(round(self.entry_price, 6)),
        str(round(self.stop_loss, 6)),
        str(round(self.take_profit or 0, 6)),
        str(round(self.quantity, 8)),
        str(round(self.risk_percent, 6)),
        str(round(self.risk_amount, 8)),           
        str(round(self.portfolio_balance_at_time, 2)),
        self.policy_version,
        self.expires_at.isoformat()                (normalized UTC)
    ])
    return hashlib.sha256(canonical.encode()).hexdigest()