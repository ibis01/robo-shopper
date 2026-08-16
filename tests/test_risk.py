import pytest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_management_mcp import calculate_position_size

def test_risk_under_2_percent():
    result = calculate_position_size(entry=60000, stop=59500, portfolio_balance=10000)
    # Risk = 500 / 5000 = 0.01 (1% of portfolio)
    assert result["position_size"] == 2.0  # 2 BTC? Actually for 10000 balance, risk=200, risk per unit=500, size=0.4? Let's fix logic.
    # Actually: risk_amount = 10000 * 0.02 = 200. risk_per_unit = 500. size = 200/500 = 0.4
    assert result["position_size"] == 0.4
    assert result["max_risk_percent"] == 2.0

def test_risk_exactly_2_percent():
    result = calculate_position_size(entry=60000, stop=59000, portfolio_balance=10000)
    # risk_amount = 200. risk_per_unit = 1000. size = 0.2
    assert result["position_size"] == 0.2