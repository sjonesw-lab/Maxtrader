"""
Tests for Renko-based hybrid strategy.
"""

import pandas as pd
import pytest
from engine.strategy_renko import (
    detect_momentum_impulse,
    calculate_atr_target,
    generate_renko_signals
)


def test_detect_momentum_impulse():
    """Test momentum impulse detection from Renko bricks."""
    data = {
        'timestamp': pd.date_range('2025-01-01', periods=10, freq='1min', tz='America/New_York'),
        'brick_close': [100.0 + i for i in range(10)],
        'direction': [1, 1, 1, 1, 1, -1, -1, -1, 1, 1]  # 5 up, 3 down, 2 up
    }
    renko_df = pd.DataFrame(data)
    
    # At idx 4: 5 consecutive up bricks
    bullish, bearish, strength = detect_momentum_impulse(renko_df, 4, lookback=5, min_consecutive=3)
    assert bullish == True
    assert bearish == False
    assert strength == 1.0  # 5/5 = perfect momentum
    
    # At idx 7: 3 consecutive down bricks
    bullish, bearish, strength = detect_momentum_impulse(renko_df, 7, lookback=5, min_consecutive=3)
    assert bullish == False
    assert bearish == True
    assert strength == 0.6  # 3/5


def test_calculate_atr_target():
    """Test ATR-based target calculation."""
    data = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=30, freq='1min', tz='America/New_York'),
        'open': [570.0] * 30,
        'high': [571.0] * 30,
        'low': [569.0] * 30,
        'close': [570.5] * 30,
        'volume': [1000] * 30
    }
    df_1min = pd.DataFrame(data)
    
    current_time = df_1min['timestamp'].iloc[-1]
    brick_size = 1.0
    
    target_long = calculate_atr_target(df_1min, current_time, 'long', brick_size, target_multiplier=2.5)
    target_short = calculate_atr_target(df_1min, current_time, 'short', brick_size, target_multiplier=2.5)
    
    # Targets should be away from current price
    current_price = 570.5
    assert target_long > current_price
    assert target_short < current_price


def test_generate_renko_signals():
    """Test signal generation from Renko bricks."""
    # Create 1-min data
    data_1min = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=50, freq='1min', tz='America/New_York'),
        'open': [570.0 + i * 0.1 for i in range(50)],
        'high': [571.0 + i * 0.1 for i in range(50)],
        'low': [569.0 + i * 0.1 for i in range(50)],
        'close': [570.5 + i * 0.1 for i in range(50)],
        'volume': [1000] * 50,
        'regime': ['bull_trend'] * 50
    }
    df_1min = pd.DataFrame(data_1min)
    
    # Create Renko data (simulated)
    data_renko = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=10, freq='2min', tz='America/New_York'),
        'brick_close': [570.0 + i for i in range(10)],
        'direction': [1, 1, 1, 1, 1, 1, -1, -1, -1, 1]
    }
    renko_df = pd.DataFrame(data_renko)
    
    regime_series = df_1min['regime']
    brick_size = 1.0
    
    signals = generate_renko_signals(
        df_1min,
        renko_df,
        regime_series,
        brick_size,
        min_momentum=0.6,
        enable_ict_filter=False
    )
    
    # Should generate signals on momentum impulses
    assert len(signals) > 0
    
    # All signals should have required fields
    for sig in signals:
        assert sig.direction in ['long', 'short']
        assert sig.spot > 0
        assert sig.target > 0
        assert sig.momentum_strength >= 0.6
