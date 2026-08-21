import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_management_mcp import calculate_position_size, evaluate_trade_risk

def test_position_size_exact_2_percent():
    result = calculate_position_size(entry=60000, stop=59500)
    assert result["position_size"] == 0.4
    assert result["risk_amount_usd"] == 200.0
    assert result["max_risk_percent"] == 2.0

def test_position_size_under_2_percent():
    # If stop is closer, size should be larger, but risk is still capped at 2%
    result = calculate_position_size(entry=60000, stop=59800)
    assert result["risk_amount_usd"] == 200.0

def test_position_size_invalid_inputs():
    with pytest.raises(ValueError):
        calculate_position_size(entry=-100, stop=59500)
    with pytest.raises(ValueError):
        calculate_position_size(entry=60000, stop=60000)

def test_evaluate_trade_risk_pass():
    result = evaluate_trade_risk(symbol="BTC", side="long", entry=60000, stop=59500, size=0.4)
    assert result["status"] == "PASSED"

def test_evaluate_trade_risk_reject_risk():
    result = evaluate_trade_risk(symbol="BTC", side="long", entry=60000, stop=59500, size=0.5)
    assert result["status"] == "REJECTED"
    assert "2% hard cap" in result["reason"]

def test_evaluate_trade_risk_reject_rsi_long():
    result = evaluate_trade_risk(symbol="BTC", side="long", entry=60000, stop=59500, size=0.4, rsi_override=75)
    assert result["status"] == "REJECTED"
    assert "overbought" in result["reason"]

def test_evaluate_trade_risk_reject_rsi_short():
    result = evaluate_trade_risk(symbol="BTC", side="short", entry=60000, stop=60500, size=0.4, rsi_override=25)
    assert result["status"] == "REJECTED"
    assert "oversold" in result["reason"]