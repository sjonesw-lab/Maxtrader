"""
Tests for multi-timeframe regime context.
"""

import pandas as pd
import pytest
from engine.regime_context import build_regime_context, add_session_labels_to_3min


def test_build_regime_context():
    """Test building 15-min regime context aligned to 3-min bars."""
    data = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=90, freq='1min', tz='America/New_York'),
        'open': [570.0 + i * 0.1 for i in range(90)],
        'high': [570.5 + i * 0.1 for i in range(90)],
        'low': [569.5 + i * 0.1 for i in range(90)],
        'close': [570.2 + i * 0.1 for i in range(90)],
        'volume': [1000] * 90
    }
    df_1min = pd.DataFrame(data)
    
    df_3min, df_15min = build_regime_context(df_1min, renko_k=1.0, regime_lookback=10)
    
    assert len(df_3min) >= 30
    assert len(df_15min) >= 6
    
    assert 'regime' in df_3min.columns
    assert 'renko_direction' in df_3min.columns
    
    assert 'regime' in df_15min.columns
    assert 'renko_direction' in df_15min.columns
    
    regimes = df_3min['regime'].unique()
    assert all(r in ['bull_trend', 'bear_trend', 'sideways'] for r in regimes)


def test_add_session_labels_to_3min():
    """Test propagating session labels from 1-min to 3-min bars."""
    data_1min = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=30, freq='1min', tz='America/New_York'),
        'open': [570.0] * 30,
        'high': [570.5] * 30,
        'low': [569.5] * 30,
        'close': [570.2] * 30,
        'volume': [1000] * 30,
        'session': ['NY'] * 30
    }
    df_1min = pd.DataFrame(data_1min)
    
    data_3min = {
        'timestamp': pd.date_range('2025-01-01 09:30', periods=10, freq='3min', tz='America/New_York'),
        'close': [570.0] * 10
    }
    df_3min = pd.DataFrame(data_3min)
    
    df_3min = add_session_labels_to_3min(df_1min, df_3min)
    
    assert 'session' in df_3min.columns
    assert all(df_3min['session'] == 'NY')
