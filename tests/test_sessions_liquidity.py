"""Tests for session labeling and liquidity zone tracking."""

import pandas as pd
import pytest
from engine.sessions_liquidity import label_sessions, add_session_highs_lows


def test_label_sessions():
    """Test session labeling logic."""
    timestamps = pd.to_datetime([
        '2024-01-02 15:00:00',
        '2024-01-02 19:00:00',
        '2024-01-03 01:00:00',
        '2024-01-02 09:00:00',
    ], utc=True).tz_convert('America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100, 101, 102, 103],
        'high': [101, 102, 103, 104],
        'low': [99, 100, 101, 102],
        'close': [100.5, 101.5, 102.5, 103.5],
        'volume': [1000, 1000, 1000, 1000]
    })
    
    df = label_sessions(df)
    
    assert 'session' in df.columns
    assert df.loc[0, 'session'] == 'ny'
    assert df.loc[2, 'session'] == 'asia'


def test_add_session_highs_lows():
    """Test session high/low tracking."""
    timestamps = pd.to_datetime([
        '2024-01-02 20:00:00',
        '2024-01-02 21:00:00',
        '2024-01-02 05:00:00',
        '2024-01-02 10:00:00',
    ], utc=True).tz_convert('America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100, 101, 102, 103],
        'high': [105, 106, 107, 108],
        'low': [95, 96, 97, 98],
        'close': [100, 101, 102, 103],
        'volume': [1000, 1000, 1000, 1000]
    })
    
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    
    assert 'asia_high' in df.columns
    assert 'asia_low' in df.columns
    assert 'london_high' in df.columns
    assert 'london_low' in df.columns


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
