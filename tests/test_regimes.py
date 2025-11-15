"""Tests for regime detection."""

import pandas as pd
import pytest
import numpy as np
from engine.regimes import detect_regime, get_regime_stats, filter_by_regime


def test_detect_regime_uptrend():
    """Test regime detection in uptrend."""
    timestamps = pd.to_datetime([
        f'2024-01-02 10:{i:02d}:00' for i in range(30)
    ], utc=True).tz_convert('America/New_York')
    
    prices = np.linspace(100, 120, 30)
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': prices,
        'high': prices + 0.5,
        'low': prices - 0.5,
        'close': prices,
        'volume': [1000] * 30
    })
    
    renko_direction = pd.Series([1] * 30)
    
    regimes = detect_regime(df, renko_direction, lookback=10)
    
    assert len(regimes) == len(df)
    assert 'bull_trend' in regimes.values


def test_detect_regime_downtrend():
    """Test regime detection in downtrend."""
    timestamps = pd.to_datetime([
        f'2024-01-02 10:{i:02d}:00' for i in range(30)
    ], utc=True).tz_convert('America/New_York')
    
    prices = np.linspace(120, 100, 30)
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': prices,
        'high': prices + 0.5,
        'low': prices - 0.5,
        'close': prices,
        'volume': [1000] * 30
    })
    
    renko_direction = pd.Series([-1] * 30)
    
    regimes = detect_regime(df, renko_direction, lookback=10)
    
    assert len(regimes) == len(df)
    assert 'bear_trend' in regimes.values


def test_detect_regime_sideways():
    """Test regime detection in sideways market."""
    timestamps = pd.to_datetime([
        f'2024-01-02 10:{i:02d}:00' for i in range(20)
    ], utc=True).tz_convert('America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100] * 20,
        'high': [101] * 20,
        'low': [99] * 20,
        'close': [100] * 20,
        'volume': [1000] * 20
    })
    
    renko_direction = pd.Series([1, -1, 1, -1] * 5)
    
    regimes = detect_regime(df, renko_direction, lookback=10)
    
    assert len(regimes) == len(df)
    assert 'sideways' in regimes.values


def test_get_regime_stats():
    """Test regime statistics calculation."""
    df = pd.DataFrame({
        'regime': ['bull_trend'] * 40 + ['bear_trend'] * 30 + ['sideways'] * 30
    })
    
    stats = get_regime_stats(df)
    
    assert stats['total_bars'] == 100
    assert 'regime_counts' in stats
    assert 'regime_percentages' in stats
    assert stats['regime_percentages']['bull_trend'] == 40.0


def test_filter_by_regime_long():
    """Test regime filter for long signals."""
    df = pd.DataFrame({
        'regime': ['bull_trend', 'bear_trend', 'sideways', 'bull_trend']
    })
    
    mask = filter_by_regime(df, 'long', allow_sideways=True)
    
    assert mask.iloc[0] == True  # bull_trend
    assert mask.iloc[1] == False  # bear_trend
    assert mask.iloc[2] == True  # sideways
    assert mask.iloc[3] == True  # bull_trend


def test_filter_by_regime_short():
    """Test regime filter for short signals."""
    df = pd.DataFrame({
        'regime': ['bull_trend', 'bear_trend', 'sideways', 'bear_trend']
    })
    
    mask = filter_by_regime(df, 'short', allow_sideways=True)
    
    assert mask.iloc[0] == False  # bull_trend
    assert mask.iloc[1] == True  # bear_trend
    assert mask.iloc[2] == True  # sideways
    assert mask.iloc[3] == True  # bear_trend


def test_filter_no_sideways():
    """Test regime filter without sideways allowance."""
    df = pd.DataFrame({
        'regime': ['bull_trend', 'sideways']
    })
    
    mask = filter_by_regime(df, 'long', allow_sideways=False)
    
    assert mask.iloc[0] == True
    assert mask.iloc[1] == False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
