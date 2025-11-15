"""Tests for ICT structure detection."""

import pandas as pd
import pytest
import numpy as np
from engine.ict_structures import (
    detect_liquidity_sweeps,
    detect_displacement,
    detect_fvgs,
    calculate_atr
)


def test_calculate_atr():
    """Test ATR calculation."""
    df = pd.DataFrame({
        'high': [102, 103, 104, 105, 106],
        'low': [98, 99, 100, 101, 102],
        'close': [100, 101, 102, 103, 104],
    })
    
    atr = calculate_atr(df, period=3)
    
    assert len(atr) == len(df)
    assert atr.notna().sum() > 0


def test_detect_fvgs():
    """Test Fair Value Gap detection."""
    df = pd.DataFrame({
        'high': [100, 101, 110],
        'low': [98, 99, 108],
        'close': [99, 100, 109],
        'open': [98, 99, 108],
    })
    
    df = detect_fvgs(df)
    
    assert 'fvg_bullish' in df.columns
    assert 'fvg_bearish' in df.columns
    assert df.loc[2, 'fvg_bullish'] == True


def test_detect_displacement():
    """Test displacement candle detection."""
    df = pd.DataFrame({
        'open': [100] * 20,
        'high': [101] * 20,
        'low': [99] * 20,
        'close': [100.5] * 20,
    })
    
    df.loc[15, 'close'] = 110
    df.loc[15, 'high'] = 110.5
    
    df = detect_displacement(df, atr_period=14)
    
    assert 'displacement_bullish' in df.columns
    assert 'displacement_bearish' in df.columns


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
