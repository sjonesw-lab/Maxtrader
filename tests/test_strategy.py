"""Tests for trading strategy and signal generation."""

import pandas as pd
import pytest
from engine.strategy import in_ny_open_window, find_target


def test_in_ny_open_window():
    """Test NY open window detection."""
    ts_in_window = pd.Timestamp('2024-01-02 10:00', tz='America/New_York')
    ts_outside_window = pd.Timestamp('2024-01-02 14:00', tz='America/New_York')
    
    assert in_ny_open_window(ts_in_window) == True
    assert in_ny_open_window(ts_outside_window) == False


def test_find_target():
    """Test target finding logic."""
    df = pd.DataFrame({
        'close': [100, 101, 102, 103, 104],
        'asia_high': [105, 105, 105, 105, 105],
        'asia_low': [95, 95, 95, 95, 95],
        'london_high': [106, 106, 106, 106, 106],
        'london_low': [94, 94, 94, 94, 94],
    })
    
    target_long = find_target(df, 2, 'long', lookback=10)
    target_short = find_target(df, 2, 'short', lookback=10)
    
    assert target_long is not None
    assert target_short is not None
    assert target_long > df.loc[2, 'close']
    assert target_short < df.loc[2, 'close']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
