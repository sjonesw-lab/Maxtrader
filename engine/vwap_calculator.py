"""
VWAP Calculation Utilities for Intraday Mean Reversion.

Provides session-based VWAP calculation and ATR-based deviation bands
for identifying mean-reversion opportunities.
"""

import pandas as pd
import numpy as np
from datetime import time


def calculate_session_vwap(df: pd.DataFrame, session_start: time = time(9, 30), 
                           session_end: time = time(16, 0)) -> pd.Series:
    """
    Calculate cumulative VWAP for the current trading session (vectorized).
    
    VWAP = cumsum(Price * Volume) / cumsum(Volume)
    
    Args:
        df: DataFrame with timestamp, close, volume columns
        session_start: Session start time (default: 9:30 AM)
        session_end: Session end time (default: 4:00 PM)
        
    Returns:
        pd.Series: VWAP values for each bar
    """
    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date
    df['time'] = df['timestamp'].dt.time
    
    in_session = (df['time'] >= session_start) & (df['time'] <= session_end)
    
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['pv'] = df['typical_price'] * df['volume']
    
    df['vwap'] = np.nan
    
    for date, group_df in df[in_session].groupby('date'):
        group_indices = group_df.index
        cum_pv = group_df['pv'].cumsum().values
        cum_vol = group_df['volume'].cumsum().values
        
        vwap_vals = np.divide(cum_pv, cum_vol, where=cum_vol > 0, out=np.full_like(cum_pv, np.nan))
        df.loc[group_indices, 'vwap'] = vwap_vals
    
    return df['vwap']


def calculate_daily_atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Calculate daily ATR from 1-minute bars, forward-filled to all bars (vectorized).
    
    For days with < period of historical data, uses available ATR with smaller window.
    
    Args:
        df: DataFrame with timestamp, high, low, close columns
        period: ATR period in days (default: 20)
        
    Returns:
        pd.Series: Daily ATR values forward-filled to each intraday bar
    """
    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date
    
    daily_data = []
    for date, group in df.groupby('date'):
        daily_data.append({
            'date': date,
            'high': group['high'].max(),
            'low': group['low'].min(),
            'close': group['close'].iloc[-1]
        })
    
    daily = pd.DataFrame(daily_data)
    daily['date'] = pd.to_datetime(daily['date'])
    daily = daily.sort_values('date').reset_index(drop=True)
    
    daily['h-l'] = daily['high'] - daily['low']
    daily['h-pc'] = abs(daily['high'] - daily['close'].shift(1))
    daily['l-pc'] = abs(daily['low'] - daily['close'].shift(1))
    daily['tr'] = daily[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    
    daily['atr'] = daily['tr'].rolling(window=period, min_periods=1).mean()
    
    daily_dict = dict(zip(daily['date'].dt.date, daily['atr'].values))
    
    df['daily_atr'] = df['date'].map(daily_dict)
    
    return df['daily_atr']


def calculate_session_range(df: pd.DataFrame, current_idx: int) -> tuple:
    """
    Calculate session range statistics for non-trend day filtering.
    
    Args:
        df: DataFrame with timestamp, high, low, open, close columns
        current_idx: Current bar index
        
    Returns:
        tuple: (session_range, open_to_high, open_to_low, session_open)
    """
    current_time = pd.to_datetime(df.loc[current_idx, 'timestamp'])
    current_date = current_time.date()
    
    session_mask = pd.to_datetime(df['timestamp']).dt.date == current_date
    session_df = df[session_mask]
    
    if len(session_df) == 0:
        return 0, 0, 0, df.loc[current_idx, 'close']
    
    session_high = session_df['high'].max()
    session_low = session_df['low'].min()
    session_open = session_df.iloc[0]['open']
    
    session_range = session_high - session_low
    open_to_high = session_high - session_open
    open_to_low = session_open - session_low
    
    return session_range, open_to_high, open_to_low, session_open


def is_non_trend_day(df: pd.DataFrame, current_idx: int, daily_atr: float,
                     max_range_atr: float = 1.0, max_open_ext_atr: float = 0.7,
                     cutoff_time: time = time(11, 0)) -> bool:
    """
    Determine if current day qualifies as a non-trend (range-bound) day.
    
    Criteria:
    - Session range < max_range_atr * daily_atr
    - Open-to-high extension < max_open_ext_atr * daily_atr
    - Open-to-low extension < max_open_ext_atr * daily_atr
    - Must be checked after cutoff_time
    
    Args:
        df: DataFrame with OHLC data
        current_idx: Current bar index
        daily_atr: Daily ATR value
        max_range_atr: Maximum session range as fraction of ATR
        max_open_ext_atr: Maximum open extension as fraction of ATR
        cutoff_time: Time to enable trend filter (default: 11:00 AM)
        
    Returns:
        bool: True if non-trend day (mean-reversion valid)
    """
    if pd.isna(daily_atr) or daily_atr <= 0:
        return False
    
    current_time = pd.to_datetime(df.loc[current_idx, 'timestamp']).time()
    
    if current_time < cutoff_time:
        return True
    
    session_range, open_to_high, open_to_low, _ = calculate_session_range(df, current_idx)
    
    range_threshold = max_range_atr * daily_atr
    ext_threshold = max_open_ext_atr * daily_atr
    
    if session_range > range_threshold:
        return False
    
    if open_to_high > ext_threshold or open_to_low > ext_threshold:
        return False
    
    return True
