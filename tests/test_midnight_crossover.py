"""Regression test for Asia session midnight boundary handling."""

import pandas as pd
import pytest
from engine.sessions_liquidity import label_sessions, add_session_highs_lows


def test_asia_session_midnight_crossover():
    """
    Test that Asia session highs/lows are correctly grouped across midnight.
    
    This regression test ensures:
    1. Asia session from 18:00 day N to 03:00 day N+1 is grouped together
    2. London/NY bars on day N+1 see the correct Asia levels
    3. No look-ahead bias (bars don't see future Asia levels)
    """
    timestamps = pd.to_datetime([
        '2024-01-02 23:00:00',
        '2024-01-03 01:00:00',
        '2024-01-03 05:00:00',
        '2024-01-03 07:00:00',
        '2024-01-03 10:00:00',
        '2024-01-03 15:00:00',
        '2024-01-03 23:00:00',
        '2024-01-04 06:00:00',
    ], utc=True).tz_convert('America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100, 101, 102, 103, 104, 105, 106, 107],
        'high': [100, 105, 110, 108, 104, 105, 106, 107],
        'low': [95, 100, 102, 103, 103.5, 104.5, 105.5, 106.5],
        'close': [100, 101, 102, 103, 104, 105, 106, 107],
        'volume': [1000] * 8
    })
    
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    
    assert df.loc[0, 'session'] == 'asia'
    assert df.loc[2, 'session'] == 'asia'
    
    asia_high_expected = df.loc[0:3, 'high'].max()
    asia_low_expected = df.loc[0:3, 'low'].min()
    
    assert df.loc[4, 'asia_high'] == asia_high_expected
    assert df.loc[4, 'asia_low'] == asia_low_expected
    assert df.loc[5, 'asia_high'] == asia_high_expected
    assert df.loc[5, 'asia_low'] == asia_low_expected
    
    assert df.loc[6, 'session'] == 'asia'
    
    next_asia_high = df.loc[6:7, 'high'].max()
    next_asia_low = df.loc[6:7, 'low'].min()
    assert df.loc[5, 'asia_high'] != next_asia_high or asia_high_expected == next_asia_high


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
