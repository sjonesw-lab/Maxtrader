"""
Tests for relaxed signal generation (Config D).
Ensures directional displacement logic is correct.
"""

import pandas as pd
import numpy as np
from engine.strategy import generate_signals_relaxed
from engine.ict_structures import detect_displacement


def test_displacement_direction_bullish():
    """Test that bullish displacement requires close > open."""
    
    periods = 25
    df = pd.DataFrame({
        'timestamp': pd.date_range('2025-01-01 09:30', periods=periods, freq='1min', tz='America/New_York'),
        'open': [100.0] * periods,
        'high': [101.5] * periods,
        'low': [98.5] * periods,
        'close': [100.2] * (periods - 1) + [102.5],
        'volume': [1000] * periods,
        'sweep_bullish': [False] * (periods - 1) + [True],
        'sweep_bearish': [False] * periods,
        'fvg_bullish': [True] * periods,
        'fvg_bearish': [False] * periods,
        'mss_bullish': [False] * (periods - 1) + [True],
        'mss_bearish': [False] * periods,
        'sweep_source': [None] * (periods - 1) + ['asia'],
        'regime': ['sideways'] * periods,
        'asia_high': [102.0] * periods,
        'asia_low': [98.0] * periods,
        'london_high': [102.0] * periods,
        'london_low': [98.0] * periods,
        'ny_high': [np.nan] * periods,
        'ny_low': [np.nan] * periods
    })
    
    df = detect_displacement(df, atr_period=14, threshold=1.0)
    
    signals = generate_signals_relaxed(
        df,
        require_fvg=False,
        displacement_threshold=1.0,
        extended_window=True,
        enable_regime_filter=True
    )
    
    if signals:
        signal = signals[0]
        bar_idx = signal.index
        bar = df.iloc[bar_idx]
        
        assert bar['close'] > bar['open'], "Bullish signal must have close > open"
        assert (bar['close'] - bar['open']) > 1.0 * bar['atr'], "Bullish signal must exceed 1.0x ATR"


def test_displacement_direction_bearish():
    """Test that bearish displacement requires close < open."""
    
    periods = 25
    df = pd.DataFrame({
        'timestamp': pd.date_range('2025-01-01 09:30', periods=periods, freq='1min', tz='America/New_York'),
        'open': [100.0] * periods,
        'high': [101.5] * periods,
        'low': [98.5] * periods,
        'close': [99.8] * (periods - 1) + [97.5],
        'volume': [1000] * periods,
        'sweep_bullish': [False] * periods,
        'sweep_bearish': [False] * (periods - 1) + [True],
        'fvg_bullish': [False] * periods,
        'fvg_bearish': [True] * periods,
        'mss_bullish': [False] * periods,
        'mss_bearish': [False] * (periods - 1) + [True],
        'sweep_source': [None] * (periods - 1) + ['asia'],
        'regime': ['sideways'] * periods,
        'asia_high': [102.0] * periods,
        'asia_low': [98.0] * periods,
        'london_high': [102.0] * periods,
        'london_low': [98.0] * periods,
        'ny_high': [np.nan] * periods,
        'ny_low': [np.nan] * periods
    })
    
    df = detect_displacement(df, atr_period=14, threshold=1.0)
    
    signals = generate_signals_relaxed(
        df,
        require_fvg=False,
        displacement_threshold=1.0,
        extended_window=True,
        enable_regime_filter=True
    )
    
    if signals:
        signal = signals[0]
        bar_idx = signal.index
        bar = df.iloc[bar_idx]
        
        assert bar['close'] < bar['open'], "Bearish signal must have close < open"
        assert (bar['open'] - bar['close']) > 1.0 * bar['atr'], "Bearish signal must exceed 1.0x ATR"


def test_mutually_exclusive_signals():
    """Test that long and short signals are mutually exclusive on same bar."""
    
    periods = 25
    closes = [99.9] * 14 + [102.0, 98.0, 102.0, 98.0, 102.0, 98.0, 102.0, 98.0, 102.0, 98.0, 102.0]
    df = pd.DataFrame({
        'timestamp': pd.date_range('2025-01-01 09:30', periods=periods, freq='1min', tz='America/New_York'),
        'open': [100.0] * periods,
        'high': [102.5] * periods,
        'low': [97.5] * periods,
        'close': closes,
        'volume': [1000] * periods,
        'sweep_bullish': [True] * periods,
        'sweep_bearish': [True] * periods,
        'fvg_bullish': [True] * periods,
        'fvg_bearish': [True] * periods,
        'mss_bullish': [True] * periods,
        'mss_bearish': [True] * periods,
        'sweep_source': ['asia'] * periods,
        'regime': ['sideways'] * periods,
        'asia_high': [103.0] * periods,
        'asia_low': [97.0] * periods,
        'london_high': [103.0] * periods,
        'london_low': [97.0] * periods,
        'ny_high': [np.nan] * periods,
        'ny_low': [np.nan] * periods
    })
    
    df = detect_displacement(df, atr_period=14, threshold=1.0)
    
    signals = generate_signals_relaxed(
        df,
        require_fvg=False,
        displacement_threshold=1.0,
        extended_window=True,
        enable_regime_filter=True
    )
    
    timestamps = [s.timestamp for s in signals]
    
    for ts in set(timestamps):
        signals_at_ts = [s for s in signals if s.timestamp == ts]
        
        longs = [s for s in signals_at_ts if s.direction == 'long']
        shorts = [s for s in signals_at_ts if s.direction == 'short']
        
        assert not (longs and shorts), f"Cannot have both long and short signal at {ts}"


def test_no_displacement_no_signal():
    """Test that small candles (below threshold) don't generate signals."""
    
    periods = 25
    df = pd.DataFrame({
        'timestamp': pd.date_range('2025-01-01 09:30', periods=periods, freq='1min', tz='America/New_York'),
        'open': [100.0] * periods,
        'high': [100.3] * periods,
        'low': [99.7] * periods,
        'close': [100.1, 99.9] * (periods // 2) + [100.05] * (periods % 2),
        'volume': [1000] * periods,
        'sweep_bullish': [True] * periods,
        'sweep_bearish': [True] * periods,
        'fvg_bullish': [True] * periods,
        'fvg_bearish': [True] * periods,
        'mss_bullish': [True] * periods,
        'mss_bearish': [True] * periods,
        'sweep_source': ['asia'] * periods,
        'regime': ['sideways'] * periods,
        'asia_high': [100.5] * periods,
        'asia_low': [99.5] * periods,
        'london_high': [100.5] * periods,
        'london_low': [99.5] * periods,
        'ny_high': [np.nan] * periods,
        'ny_low': [np.nan] * periods
    })
    
    df = detect_displacement(df, atr_period=14, threshold=1.0)
    
    signals = generate_signals_relaxed(
        df,
        require_fvg=False,
        displacement_threshold=1.0,
        extended_window=True,
        enable_regime_filter=True
    )
    
    assert len(signals) == 0, "Small candles (< 1.0x ATR) should not generate signals"
