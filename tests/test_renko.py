"""Tests for Renko chart builder."""

import pandas as pd
import pytest
import numpy as np
from engine.renko import build_renko, get_renko_direction_series, calculate_renko_trend_strength


def test_build_renko_atr_mode():
    """Test Renko builder with ATR mode returns valid structure."""
    np.random.seed(42)
    
    timestamps = pd.date_range('2024-01-02 10:00', periods=50, freq='1min', tz='America/New_York')
    
    prices = 100 + np.cumsum(np.random.randn(50) * 2)
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': prices,
        'high': prices + abs(np.random.randn(50)),
        'low': prices - abs(np.random.randn(50)),
        'close': prices,
        'volume': [1000] * 50
    })
    
    renko_df = build_renko(df, mode="atr", k=0.5)
    
    assert isinstance(renko_df, pd.DataFrame)
    
    if len(renko_df) > 0:
        assert 'timestamp' in renko_df.columns
        assert 'brick_close' in renko_df.columns
        assert 'direction' in renko_df.columns
        assert all(renko_df['direction'].isin([-1, 1]))


def test_build_renko_fixed_mode():
    """Test Renko builder with fixed brick size."""
    timestamps = pd.to_datetime([
        '2024-01-02 10:00:00',
        '2024-01-02 10:01:00',
        '2024-01-02 10:02:00',
    ], utc=True).tz_convert('America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100, 105, 110],
        'high': [101, 106, 111],
        'low': [99, 104, 109],
        'close': [100, 105, 110],
        'volume': [1000] * 3
    })
    
    renko_df = build_renko(df, mode="fixed", fixed_brick_size=2.0)
    
    assert len(renko_df) > 0
    assert all(renko_df['direction'].isin([-1, 1]))


def test_get_renko_direction_series():
    """Test alignment of Renko directions with original DataFrame."""
    timestamps = pd.to_datetime([
        '2024-01-02 10:00:00',
        '2024-01-02 10:01:00',
        '2024-01-02 10:02:00',
        '2024-01-02 10:03:00',
    ], utc=True).tz_convert('America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100, 102, 104, 106],
        'high': [101, 103, 105, 107],
        'low': [99, 101, 103, 105],
        'close': [100, 102, 104, 106],
        'volume': [1000] * 4
    })
    
    renko_df = build_renko(df, mode="fixed", fixed_brick_size=1.0)
    direction_series = get_renko_direction_series(df, renko_df)
    
    assert len(direction_series) == len(df)
    assert all(direction_series.isin([-1, 0, 1]))


def test_calculate_renko_trend_strength():
    """Test trend strength calculation."""
    renko_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-02 10:00', periods=10, freq='1min', tz='America/New_York'),
        'brick_close': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        'direction': [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]  # All up
    })
    
    trend_strength = calculate_renko_trend_strength(renko_df, lookback=5)
    
    assert len(trend_strength) == len(renko_df)
    assert trend_strength.iloc[-1] == 1.0  # Perfect uptrend


def test_empty_dataframe():
    """Test Renko builder with empty DataFrame."""
    df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    renko_df = build_renko(df)
    
    assert len(renko_df) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
