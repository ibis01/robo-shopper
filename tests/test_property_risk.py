"""
Property-based tests using Hypothesis to verify the governance invariants hold
across thousands of random trade configurations.

Key insight: propose_trade() accepts ANY proposal (data ingestion).
screen_trade() enforces the 2% cap (governance gate).
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from trade_memory_mcp import propose_trade
from governance_engine import screen_trade
from schemas import TradeStatus


# Define the input space for random trade generation
@given(
    symbol=st.sampled_from(["BTC", "ETH", "SOL", "DOGE"]),
    side=st.sampled_from(["long", "short"]),
    quantity=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
    entry_price=st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    stop_loss=st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    portfolio_balance=st.floats(min_value=1000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=500, deadline=None)
def test_propose_trade_accepts_any_valid_input(symbol, side, quantity, entry_price, stop_loss, portfolio_balance):
    """
    Property: propose_trade() accepts ANY valid trade configuration.
    
    This is the data ingestion layer — it doesn't enforce business rules,
    just computes risk metrics and stores the proposal.
    """
    # Skip if stop_loss == entry_price (zero risk distance)
    if abs(entry_price - stop_loss) < 0.01:
        return
    
    # Create the proposal — should never raise
    prop = propose_trade(
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        portfolio_balance=portfolio_balance
    )
    
    # Verify it was persisted with computed metrics
    trade_id = prop["trade_id"]
    
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, risk_percent, risk_amount FROM trades WHERE id = ?",
        (trade_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None, "Trade not found in database"
    status, risk_percent, risk_amount = row
    
    # Verify it's in PROPOSED state
    assert status == TradeStatus.PROPOSED.value
    
    # Verify metrics were computed
    assert risk_percent is not None
    assert risk_amount is not None
    
    # Verify the calculation is deterministic
    expected_risk_amount = abs(entry_price - stop_loss) * quantity
    assert abs(risk_amount - expected_risk_amount) < 0.01


@given(
    quantity=st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False),
    entry_price=st.floats(min_value=50000.0, max_value=70000.0, allow_nan=False, allow_infinity=False),
    stop_loss=st.floats(min_value=49000.0, max_value=69000.0, allow_nan=False, allow_infinity=False),
    portfolio_balance=st.floats(min_value=10000.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=200, deadline=None)
def test_screen_trade_rejects_high_risk_proposals(quantity, entry_price, stop_loss, portfolio_balance):
    """
    Property: screen_trade() REJECTS proposals where risk_percent > 0.02.
    
    This is the governance gate — it enforces the 2% cap deterministically.
    """
    # Skip if stop_loss == entry_price
    if abs(entry_price - stop_loss) < 0.01:
        return
    
    # Compute the expected risk
    risk_amount = abs(entry_price - stop_loss) * quantity
    risk_percent = risk_amount / portfolio_balance
    
    # Create the proposal
    prop = propose_trade(
        symbol="BTC",
        side="long",
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        portfolio_balance=portfolio_balance
    )
    
    trade_id = prop["trade_id"]
    
    # Screen it
    result = screen_trade(trade_id)
    
    # If risk exceeds 2%, screening should REJECT
    if risk_percent > 0.02:
        assert result["status"] == "REJECTED", \
            f"Trade with {risk_percent:.4f} risk should be REJECTED, got {result}"
        assert result.get("stage") == "risk_engine", \
            f"High-risk rejection should come from risk_engine, got {result.get('stage')}"
    else:
        # If risk is acceptable, screening should succeed (assuming exposure/breaker pass)
        # We can't guarantee SUCCESS because exposure/breaker might reject,
        # but we can verify it didn't fail on risk
        if result["status"] == "REJECTED":
            assert result.get("stage") != "risk_engine", \
                f"Trade with {risk_percent:.4f} risk should not fail risk check"


@given(
    quantity=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    entry_price=st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    stop_loss=st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False)
)
@settings(max_examples=500, deadline=None)
def test_risk_amount_calculation_is_deterministic(quantity, entry_price, stop_loss):
    """
    Property: risk_amount = abs(entry - stop) * quantity
    
    This must hold for ANY combination of inputs. No rounding errors,
    no edge cases, no exceptions.
    """
    if quantity == 0 or abs(entry_price - stop_loss) < 0.01:
        return  # Skip degenerate cases
    
    expected_risk = abs(entry_price - stop_loss) * quantity
    
    # Verify the calculation matches exactly
    prop = propose_trade(
        symbol="BTC",
        side="long",
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        portfolio_balance=100000.0
    )
    
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT risk_amount FROM trades WHERE id = ?",
        (prop["trade_id"],)
    )
    row = cursor.fetchone()
    conn.close()
    
    persisted_risk = row[0]
    assert abs(persisted_risk - expected_risk) < 0.01, \
        f"Deterministic calculation failed: {persisted_risk} != {expected_risk}"


def test_propose_trade_always_sets_status_proposed():
    """
    Property: Every proposal starts in PROPOSED state.
    
    This is a state machine invariant that must hold universally.
    """
    prop = propose_trade(
        symbol="BTC",
        side="long",
        quantity=0.1,
        entry_price=50000,
        stop_loss=49500,
        portfolio_balance=10000.0
    )
    
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status FROM trades WHERE id = ?",
        (prop["trade_id"],)
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row[0] == TradeStatus.PROPOSED.value, \
        f"New trade must start as PROPOSED, got {row[0]}"
