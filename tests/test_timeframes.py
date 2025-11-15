"""
Tests for multi-timeframe data preparation.
"""

import pandas as pd
import pytest
from engine.timeframes import (
    resample_to_timeframe,
    prepare_multi_timeframe_data,
    align_timeframe_context
)


def test_resample_to_3min():
    """Test 1-minute to 3-minute resampling."""
    data = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=6, freq='1min', tz='America/New_York'),
        'open': [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        'high': [100.5, 101.5, 102.5, 103.5, 104.5, 105.5],
        'low': [99.5, 100.5, 101.5, 102.5, 103.5, 104.5],
        'close': [101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
        'volume': [1000, 1100, 1200, 1300, 1400, 1500]
    }
    df = pd.DataFrame(data)
    
    df_3min = resample_to_timeframe(df, '3min')
    
    assert len(df_3min) == 3
    assert df_3min.iloc[1]['open'] == 101.0
    assert df_3min.iloc[1]['close'] == 104.0
    assert df_3min.iloc[1]['high'] == 103.5
    assert df_3min.iloc[1]['low'] == 100.5
    assert df_3min.iloc[1]['volume'] == 3600


def test_resample_to_15min():
    """Test 1-minute to 15-minute resampling."""
    data = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=30, freq='1min', tz='America/New_York'),
        'open': list(range(100, 130)),
        'high': list(range(101, 131)),
        'low': list(range(99, 129)),
        'close': list(range(101, 131)),
        'volume': [1000] * 30
    }
    df = pd.DataFrame(data)
    
    df_15min = resample_to_timeframe(df, '15min')
    
    assert len(df_15min) >= 2
    assert df_15min.iloc[1]['volume'] == 15000


def test_prepare_multi_timeframe_data():
    """Test full multi-timeframe preparation."""
    data = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=45, freq='1min', tz='America/New_York'),
        'open': list(range(100, 145)),
        'high': list(range(101, 146)),
        'low': list(range(99, 144)),
        'close': list(range(101, 146)),
        'volume': [1000] * 45
    }
    df_1min = pd.DataFrame(data)
    
    df_1m, df_3m, df_15m = prepare_multi_timeframe_data(df_1min)
    
    assert len(df_1m) == 45
    assert len(df_3m) >= 15
    assert len(df_15m) >= 3


def test_align_timeframe_context():
    """Test aligning 15-min context onto 3-min bars."""
    data_3min = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=5, freq='3min', tz='America/New_York'),
        'close': [100, 101, 102, 103, 104]
    }
    df_3min = pd.DataFrame(data_3min)
    
    data_15min = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=2, freq='15min', tz='America/New_York'),
        'regime': ['bull_trend', 'sideways'],
        'target': [105.0, 103.0]
    }
    df_15min = pd.DataFrame(data_15min)
    
    df_aligned = align_timeframe_context(df_3min, df_15min, ['regime', 'target'])
    
    assert 'regime_15m' in df_aligned.columns
    assert 'target_15m' in df_aligned.columns
    
    assert df_aligned.iloc[0]['regime_15m'] == 'bull_trend'
    assert df_aligned.iloc[0]['target_15m'] == 105.0
    
    assert df_aligned.iloc[4]['regime_15m'] == 'bull_trend'
