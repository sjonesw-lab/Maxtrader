"""
Session labeling and liquidity zone tracking for ICT trading methodology.

Implements:
- Session labeling (Asia, London, NY)
- Session high/low tracking for liquidity analysis
"""

import pandas as pd
import numpy as np
from typing import Tuple


def label_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'session' column with values: 'asia', 'london', 'ny', or 'other',
    based on bar time in America/New_York.
    
    Sessions (all times in America/New_York):
    - Asia: 18:00 – 03:00
    - London: 03:00 – 09:30
    - NY: 09:30 – 16:00
    - Other: 16:00 – 18:00
    
    Args:
        df: DataFrame with tz-aware timestamp column
        
    Returns:
        pd.DataFrame: DataFrame with added 'session' column
    """
    df = df.copy()
    
    df['hour'] = df['timestamp'].dt.hour
    df['minute'] = df['timestamp'].dt.minute
    df['time_decimal'] = df['hour'] + df['minute'] / 60.0
    
    def classify_session(row):
        t = row['time_decimal']
        
        if (t >= 9.5) and (t < 16.0):
            return 'ny'
        elif (t >= 3.0) and (t < 9.5):
            return 'london'
        elif (t >= 18.0) or (t < 3.0):
            return 'asia'
        else:
            return 'other'
    
    df['session'] = df.apply(classify_session, axis=1)
    
    df = df.drop(['hour', 'minute', 'time_decimal'], axis=1)
    
    return df


def add_session_highs_lows(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each trading day:
      - Compute Asia high/low within that day's Asia session.
      - Compute London high/low within that day's London session.
    Then forward-fill those levels across the rest of the day.
    
    Note: Asia session spans midnight (18:00-03:00), so we define a "trading day"
    by adding 6 hours to each timestamp before taking the date. This ensures:
    - Bars from 18:00 day N → trading_day N+1
    - Bars from 00:00-03:00 day N → trading_day N
    - The entire Asia session (18:00 N-1 to 03:00 N) groups under trading_day N
    - London/NY bars on day N see Asia levels from the completed prior session
    - No look-ahead bias
    
    Args:
        df: DataFrame with 'session' column (from label_sessions)
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - asia_high, asia_low
            - london_high, london_low
    """
    df = df.copy()
    
    df['trading_day'] = df['timestamp'].apply(
        lambda ts: (ts + pd.Timedelta(hours=6)).date()
    )
    
    df['asia_high'] = np.nan
    df['asia_low'] = np.nan
    df['london_high'] = np.nan
    df['london_low'] = np.nan
    
    for trading_day in df['trading_day'].unique():
        day_mask = df['trading_day'] == trading_day
        
        asia_mask = day_mask & (df['session'] == 'asia')
        if asia_mask.any():
            asia_data = df.loc[asia_mask]
            asia_high = asia_data['high'].max()
            asia_low = asia_data['low'].min()
            
            df.loc[day_mask, 'asia_high'] = asia_high
            df.loc[day_mask, 'asia_low'] = asia_low
        
        london_mask = day_mask & (df['session'] == 'london')
        if london_mask.any():
            london_data = df.loc[london_mask]
            london_high = london_data['high'].max()
            london_low = london_data['low'].min()
            
            df.loc[day_mask, 'london_high'] = london_high
            df.loc[day_mask, 'london_low'] = london_low
    
    df['asia_high'] = df.groupby('trading_day')['asia_high'].ffill()
    df['asia_low'] = df.groupby('trading_day')['asia_low'].ffill()
    df['london_high'] = df.groupby('trading_day')['london_high'].ffill()
    df['london_low'] = df.groupby('trading_day')['london_low'].ffill()
    
    df = df.drop('trading_day', axis=1)
    
    return df
