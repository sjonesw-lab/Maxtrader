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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
