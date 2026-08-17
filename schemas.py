"""
Robo-Shopper V4 - Formal Governance Schemas (Sprint 5).
Single source of truth for all data models.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timezone, timedelta, timezone
from typing import Optional
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
    """
    Immutable proposal object — the canonical representation of a trade proposal.
    Used for hash binding, approval tokens, and execution verification.
    """
    # Auto-generated fields
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Core trade parameters
    asset: str
    side: TradeSide
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    quantity: float
    
    # Risk parameters (computed at proposal time, immutable after)
    risk_percent: float
    risk_amount: float
    portfolio_balance_at_time: float
    
    # Agent reasoning (LLM's justification, for human review)
    agent_reasoning: str
    
    # Risk engine decision (PASSED/REJECTED by deterministic rulebook)
    risk_decision: str
    
    # Policy binding (version + chain + venue + wallet)
    policy_version: str = POLICY_VERSION
    chain_id: str = "x-layer"
    venue: str = "onchainos"
    wallet_address: Optional[str] = None
    
    # Expiration – deterministic; will be stored and reused
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=PROPOSAL_EXPIRY_HOURS)
    )

    @model_validator(mode='after')
    def validate_cross_field(self) -> 'TradeProposal':
        """Validate cross-field constraints using Pydantic V2 API."""
        # Stop loss vs entry price based on side
        if self.side.value == 'long':
            if self.stop_loss >= self.entry_price:
                raise ValueError(f"Long: stop_loss ({self.stop_loss}) must be < entry_price ({self.entry_price})")
        elif self.side.value == 'short':
            if self.stop_loss <= self.entry_price:
                raise ValueError(f"Short: stop_loss ({self.stop_loss}) must be > entry_price ({self.entry_price})")
        
        # Risk percent bounds
        if self.risk_percent is not None:
            if not (0 <= self.risk_percent <= 1):
                raise ValueError(f"risk_percent must be in [0, 1], got {self.risk_percent}")
        
        # Risk amount consistency check
        if self.risk_amount is not None and self.risk_percent is not None:
            if self.portfolio_balance_at_time and self.portfolio_balance_at_time > 0:
                expected = self.risk_percent * self.portfolio_balance_at_time
                if abs(self.risk_amount - expected) > 1.0:  # Allow small tolerance
                    raise ValueError(f"risk_amount ({self.risk_amount}) != risk_percent * balance ({expected})")
        
        return self
    
    def compute_hash(self) -> str:
        """
        Deterministic SHA-256 hash binding ALL materially relevant parameters.
        The hash is used to cryptographically bind approval to the exact trade details.
        """
        # Normalise all numbers to fixed precision to avoid floating-point mismatches.
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
            self.expires_at.isoformat()   # normalized UTC
        ])
        return hashlib.sha256(canonical.encode()).hexdigest()


