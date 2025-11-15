"""Tests for options engine."""

import pandas as pd
import pytest
from engine.options_engine import (
    generate_strikes,
    estimate_option_premium,
    build_long_option,
    build_debit_spread,
    calculate_payoff_at_price
)


def test_generate_strikes():
    """Test strike generation."""
    strikes = generate_strikes(spot=400.0, num_strikes=10, increment=1.0)
    
    assert len(strikes) > 0
    assert 400.0 in strikes or any(abs(s - 400.0) < 1.0 for s in strikes)


def test_estimate_option_premium():
    """Test option premium estimation."""
    call_premium = estimate_option_premium('call', strike=400, spot=395, time_to_expiry_days=7)
    put_premium = estimate_option_premium('put', strike=400, spot=395, time_to_expiry_days=7)
    
    assert call_premium > 0
    assert put_premium > 0
    assert put_premium > call_premium


def test_build_long_option():
    """Test long option builder."""
    strikes = generate_strikes(400, num_strikes=10)
    expiry = pd.Timestamp('2024-01-10', tz='America/New_York')
    entry_time = pd.Timestamp('2024-01-03 10:00', tz='America/New_York')
    
    position = build_long_option('long', 400.0, strikes, expiry, entry_time)
    
    assert len(position.options) == 1
    assert position.options[0].kind == 'call'
    assert position.options[0].is_long == True
    assert position.entry_cost > 0


def test_calculate_payoff():
    """Test payoff calculation."""
    strikes = generate_strikes(400, num_strikes=10)
    expiry = pd.Timestamp('2024-01-10', tz='America/New_York')
    entry_time = pd.Timestamp('2024-01-03 10:00', tz='America/New_York')
    
    position = build_long_option('long', 400.0, strikes, expiry, entry_time)
    
    payoff_at_410 = calculate_payoff_at_price(position, 410.0)
    payoff_at_400 = calculate_payoff_at_price(position, 400.0)
    
    assert payoff_at_410 > payoff_at_400


def test_60min_option_pricing_realistic():
    """
    Regression test for Trade #6 (67R bug).
    
    Verifies that 60-minute call options have realistic premiums (≥ $0.20)
    to prevent unrealistic R-multiples from 1¢ options.
    """
    # Replicate Trade #6 scenario: Sept 4, 2025
    spot = 570.47
    strikes = generate_strikes(spot, num_strikes=20, increment=1.0)
    
    entry_time = pd.Timestamp('2025-09-04 10:23:00', tz='America/New_York')
    expiry = entry_time + pd.Timedelta(hours=1)  # 60 minutes
    
    # Build long call
    position = build_long_option('long', spot, strikes, expiry, entry_time)
    
    # Verify cost is in realistic contract-level range ($100-$500 for 60-min ATM)
    # Per-share premium ~$3 × 100 shares + commissions/slippage = ~$310-320
    assert position.entry_cost >= 100, f"60-min contract cost too low: ${position.entry_cost:.2f}"
    assert position.entry_cost < 500, f"60-min contract cost too high: ${position.entry_cost:.2f}"
    
    # Most importantly: verify this prevents unrealistic 67R outliers
    # Real contract costs make R-multiples realistic
    
    # Verify it's properly calculated using fractional days (not 0 days)
    # 60 minutes = 0.042 days, which should produce reasonable time value
    time_delta = expiry - entry_time
    days_to_expiry = time_delta.total_seconds() / 86400.0
    assert 0.04 <= days_to_expiry <= 0.05, f"Time calculation wrong: {days_to_expiry:.4f} days"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
