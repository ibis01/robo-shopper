import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_management_mcp import calculate_position_size, evaluate_trade_risk

# ------------------------------------------------------------------
# 1. POSITION SIZING TESTS
# ------------------------------------------------------------------
def test_position_size_exact_2_percent():
    """Portfolio: $10,000 | Risk: 2% ($200) | Stop distance: $1000 (60k->59k) -> Size: 0.2"""
    result = calculate_position_size(entry=60000, stop=59000, portfolio_balance=10000)
    # $200 risk / $1000 per unit = 0.2 BTC
    assert result["position_size"] == 0.2
    assert result["max_risk_percent"] == 2.0
    assert result["risk_amount_usd"] == 200.0

def test_position_size_under_2_percent():
    """Portfolio: $10,000 | Stop distance: $500 -> Risk: 1% -> Size: 0.4"""
    result = calculate_position_size(entry=60000, stop=59500, portfolio_balance=10000)
    # $200 risk / $500 per unit = 0.4 BTC
    assert result["position_size"] == 0.4
    assert result["max_risk_percent"] == 2.0

def test_position_size_invalid_inputs():
    """Ensure Hard Stop on garbage inputs."""
    with pytest.raises(ValueError, match="Entry price must be positive"):
        calculate_position_size(entry=0, stop=59500)
    
    with pytest.raises(ValueError, match="Stop loss price must be positive"):
        calculate_position_size(entry=60000, stop=0)
    
    with pytest.raises(ValueError, match="Entry and Stop prices cannot be equal"):
        calculate_position_size(entry=60000, stop=60000)

# ------------------------------------------------------------------
# 2. TRADE EVALUATION (VETO GATE) TESTS
# ------------------------------------------------------------------
def test_evaluate_trade_risk_pass():
    """Risk = 2% exactly, RSI neutral -> PASSED"""
    result = evaluate_trade_risk(
        symbol="BTC", side="long", entry=60000, stop=59500, 
        size=0.4, portfolio_balance=10000, rsi_override=50
    )
    assert result["status"] == "PASSED"
    assert result["risk_percent"] == 2.0

def test_evaluate_trade_risk_reject_risk():
    """Risk = 4% (>2%) -> REJECTED"""
    result = evaluate_trade_risk(
        symbol="BTC", side="long", entry=60000, stop=58000, 
        size=0.4, portfolio_balance=10000, rsi_override=50
    )
    assert result["status"] == "REJECTED"
    assert "Risk exceeds 2%" in result["reason"]

def test_evaluate_trade_risk_reject_rsi_long():
    """RSI = 75 (Overbought) + Long -> REJECTED"""
    result = evaluate_trade_risk(
        symbol="BTC", side="long", entry=60000, stop=59500, 
        size=0.4, portfolio_balance=10000, rsi_override=75
    )
    assert result["status"] == "REJECTED"
    assert "overbought" in result["reason"]

def test_evaluate_trade_risk_reject_rsi_short():
    """RSI = 25 (Oversold) + Short -> REJECTED"""
    result = evaluate_trade_risk(
        symbol="BTC", side="short", entry=60000, stop=60500, 
        size=0.4, portfolio_balance=10000, rsi_override=25
    )
    assert result["status"] == "REJECTED"
    assert "oversold" in result["reason"]