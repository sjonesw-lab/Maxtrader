"""
ICT (Inner Circle Trader) structure detection module.

Implements detection for:
- Liquidity sweeps (bullish/bearish)
- Displacement candles (ATR-based)
- Fair Value Gaps (FVG)
- Market Structure Shifts (MSS)
- Order Blocks (OB)
"""

import pandas as pd
import numpy as np


def detect_liquidity_sweeps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect liquidity sweeps of Asia or London session highs/lows.
    
    Bullish sweep:
    - Price wicks below Asia or London low (low < session_low)
    - Then closes back above that low (close > session_low)
    
    Bearish sweep:
    - Price wicks above Asia or London high (high > session_high)
    - Then closes back below that high (close < session_high)
    
    Args:
        df: DataFrame with asia_high, asia_low, london_high, london_low columns
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - sweep_bullish (bool)
            - sweep_bearish (bool)
            - sweep_source (str: 'asia', 'london', or None)
    """
    df = df.copy()
    
    df['sweep_bullish'] = False
    df['sweep_bearish'] = False
    df['sweep_source'] = None
    
    for idx in df.index:
        row = df.loc[idx]
        
        if pd.notna(row['asia_low']) and row['low'] < row['asia_low'] and row['close'] > row['asia_low']:
            df.at[idx, 'sweep_bullish'] = True
            df.at[idx, 'sweep_source'] = 'asia'
        elif pd.notna(row['london_low']) and row['low'] < row['london_low'] and row['close'] > row['london_low']:
            df.at[idx, 'sweep_bullish'] = True
            df.at[idx, 'sweep_source'] = 'london'
        
        if pd.notna(row['asia_high']) and row['high'] > row['asia_high'] and row['close'] < row['asia_high']:
            df.at[idx, 'sweep_bearish'] = True
            df.at[idx, 'sweep_source'] = 'asia'
        elif pd.notna(row['london_high']) and row['high'] > row['london_high'] and row['close'] < row['london_high']:
            df.at[idx, 'sweep_bearish'] = True
            df.at[idx, 'sweep_source'] = 'london'
    
    return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).
    
    Args:
        df: DataFrame with high, low, close columns
        period: ATR period (default: 14)
        
    Returns:
        pd.Series: ATR values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr_result: pd.Series = tr.rolling(window=period).mean()
    
    return atr_result


def detect_displacement(df: pd.DataFrame, atr_period: int = 14, threshold: float = 1.2) -> pd.DataFrame:
    """
    Detect displacement candles using ATR with directional logic.
    
    Bullish displacement:
    - Close > Open (bullish candle)
    - Candle body (close - open) > threshold * ATR
    - Close > previous candle high
    
    Bearish displacement:
    - Close < Open (bearish candle)
    - Candle body (open - close) > threshold * ATR
    - Close < previous candle low
    
    Args:
        df: DataFrame with OHLC data
        atr_period: ATR period (default: 14)
        threshold: ATR multiplier for displacement (default: 1.2)
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - displacement_bullish (bool)
            - displacement_bearish (bool)
            - atr (float)
    """
    df = df.copy()
    
    df['atr'] = calculate_atr(df, period=atr_period)
    
    df['prev_high'] = df['high'].shift(1)
    df['prev_low'] = df['low'].shift(1)
    
    df['displacement_bullish'] = (
        (df['close'] > df['open']) &
        ((df['close'] - df['open']) > threshold * df['atr']) &
        (df['close'] > df['prev_high'])
    )
    
    df['displacement_bearish'] = (
        (df['close'] < df['open']) &
        ((df['open'] - df['close']) > threshold * df['atr']) &
        (df['close'] < df['prev_low'])
    )
    
    df = df.drop(['prev_high', 'prev_low'], axis=1)
    
    return df


def detect_fvgs(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Fair Value Gaps (FVG) using 3-candle logic.
    
    Bullish FVG at index n: low[n] > high[n-2]
    Bearish FVG at index n: high[n] < low[n-2]
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - fvg_bullish (bool)
            - fvg_bearish (bool)
            - fvg_low (float)
            - fvg_high (float)
    """
    df = df.copy()
    
    df['fvg_bullish'] = False
    df['fvg_bearish'] = False
    df['fvg_low'] = np.nan
    df['fvg_high'] = np.nan
    
    for i in range(2, len(df)):
        if df.loc[i, 'low'] > df.loc[i-2, 'high']:
            df.at[i, 'fvg_bullish'] = True
            df.at[i, 'fvg_low'] = df.loc[i-2, 'high']
            df.at[i, 'fvg_high'] = df.loc[i, 'low']
        
        if df.loc[i, 'high'] < df.loc[i-2, 'low']:
            df.at[i, 'fvg_bearish'] = True
            df.at[i, 'fvg_low'] = df.loc[i, 'high']
            df.at[i, 'fvg_high'] = df.loc[i-2, 'low']
    
    return df


def detect_mss(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Market Structure Shifts (MSS).
    
    Swing high at i: high[i] > high[i-1], high[i-2], high[i+1], high[i+2]
    Swing low at i: low[i] < low[i-1], low[i-2], low[i+1], low[i+2]
    
    Bullish MSS: After bearish/neutral structure, close above last swing high
    Bearish MSS: After bullish/neutral structure, close below last swing low
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - mss_bullish (bool)
            - mss_bearish (bool)
    """
    df = df.copy()
    
    df['swing_high'] = False
    df['swing_low'] = False
    df['swing_high_price'] = np.nan
    df['swing_low_price'] = np.nan
    
    for i in range(2, len(df) - 2):
        is_swing_high = (
            (df.loc[i, 'high'] > df.loc[i-1, 'high']) and
            (df.loc[i, 'high'] > df.loc[i-2, 'high']) and
            (df.loc[i, 'high'] > df.loc[i+1, 'high']) and
            (df.loc[i, 'high'] > df.loc[i+2, 'high'])
        )
        
        is_swing_low = (
            (df.loc[i, 'low'] < df.loc[i-1, 'low']) and
            (df.loc[i, 'low'] < df.loc[i-2, 'low']) and
            (df.loc[i, 'low'] < df.loc[i+1, 'low']) and
            (df.loc[i, 'low'] < df.loc[i+2, 'low'])
        )
        
        if is_swing_high:
            df.at[i, 'swing_high'] = True
            df.at[i, 'swing_high_price'] = df.loc[i, 'high']
        
        if is_swing_low:
            df.at[i, 'swing_low'] = True
            df.at[i, 'swing_low_price'] = df.loc[i, 'low']
    
    df['last_swing_high'] = df['swing_high_price'].ffill()
    df['last_swing_low'] = df['swing_low_price'].ffill()
    
    df['mss_bullish'] = False
    df['mss_bearish'] = False
    
    df['structure'] = 'neutral'
    
    for i in range(len(df)):
        if pd.notna(df.loc[i, 'last_swing_high']) and df.loc[i, 'close'] > df.loc[i, 'last_swing_high']:
            if df.loc[i-1 if i > 0 else i, 'structure'] in ['bearish', 'neutral']:
                df.at[i, 'mss_bullish'] = True
                df.at[i, 'structure'] = 'bullish'
        
        if pd.notna(df.loc[i, 'last_swing_low']) and df.loc[i, 'close'] < df.loc[i, 'last_swing_low']:
            if df.loc[i-1 if i > 0 else i, 'structure'] in ['bullish', 'neutral']:
                df.at[i, 'mss_bearish'] = True
                df.at[i, 'structure'] = 'bearish'
    
    df = df.drop(['swing_high', 'swing_low', 'swing_high_price', 'swing_low_price', 
                  'last_swing_high', 'last_swing_low', 'structure'], axis=1)
    
    return df


def detect_order_blocks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect Order Blocks (OB) - last opposite candle before displacement.
    
    Bullish OB: last bearish candle before a bullish displacement
    Bearish OB: last bullish candle before a bearish displacement
    
    Args:
        df: DataFrame with displacement columns
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - ob_bullish (bool)
            - ob_bearish (bool)
            - ob_low (float)
            - ob_high (float)
    """
    df = df.copy()
    
    df['ob_bullish'] = False
    df['ob_bearish'] = False
    df['ob_low'] = np.nan
    df['ob_high'] = np.nan
    
    df['is_bearish_candle'] = df['close'] < df['open']
    df['is_bullish_candle'] = df['close'] > df['open']
    
    for i in range(1, len(df)):
        if df.loc[i, 'displacement_bullish']:
            for j in range(i-1, max(-1, i-20), -1):
                if df.loc[j, 'is_bearish_candle']:
                    df.at[i, 'ob_bullish'] = True
                    df.at[i, 'ob_low'] = df.loc[j, 'low']
                    df.at[i, 'ob_high'] = df.loc[j, 'high']
                    break
        
        if df.loc[i, 'displacement_bearish']:
            for j in range(i-1, max(-1, i-20), -1):
                if df.loc[j, 'is_bullish_candle']:
                    df.at[i, 'ob_bearish'] = True
                    df.at[i, 'ob_low'] = df.loc[j, 'low']
                    df.at[i, 'ob_high'] = df.loc[j, 'high']
                    break
    
    df = df.drop(['is_bearish_candle', 'is_bullish_candle'], axis=1)
    
    return df
