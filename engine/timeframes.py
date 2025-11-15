"""
Multi-timeframe data preparation module.

Resamples 1-minute bars to 3-minute and 15-minute timeframes
while preserving session metadata and ensuring proper alignment.
"""

import pandas as pd
from typing import Tuple


def resample_to_timeframe(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample 1-minute OHLCV bars to a higher timeframe.
    
    Args:
        df: DataFrame with 1-minute bars (timestamp index, OHLCV columns)
        timeframe: Target timeframe ('3min', '15min', etc.)
        
    Returns:
        Resampled DataFrame with aggregated bars
    """
    if 'timestamp' not in df.columns:
        raise ValueError("DataFrame must have 'timestamp' column")
    
    df_copy = df.copy()
    df_copy = df_copy.set_index('timestamp')
    
    resampled = df_copy.resample(timeframe, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    resampled = resampled.reset_index()
    
    return resampled


def prepare_multi_timeframe_data(df_1min: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Prepare synchronized 1-min, 3-min, and 15-min dataframes.
    
    Args:
        df_1min: Base 1-minute OHLCV data with timestamp column
        
    Returns:
        Tuple of (df_1min, df_3min, df_15min) with aligned timestamps
    """
    df_3min = resample_to_timeframe(df_1min, '3min')
    df_15min = resample_to_timeframe(df_1min, '15min')
    
    return df_1min, df_3min, df_15min


def align_timeframe_context(df_lower: pd.DataFrame, df_higher: pd.DataFrame, 
                            columns_to_merge: list) -> pd.DataFrame:
    """
    Align higher timeframe context onto lower timeframe bars.
    
    Uses forward-fill to propagate higher timeframe values down to
    lower timeframe bars for synchronized multi-timeframe analysis.
    
    Args:
        df_lower: Lower timeframe DataFrame (e.g., 3-min)
        df_higher: Higher timeframe DataFrame (e.g., 15-min)
        columns_to_merge: List of column names to merge from higher TF
        
    Returns:
        df_lower with higher timeframe columns added
    """
    if 'timestamp' not in df_lower.columns or 'timestamp' not in df_higher.columns:
        raise ValueError("Both DataFrames must have 'timestamp' column")
    
    df_result = df_lower.copy()
    
    df_higher_subset = df_higher[['timestamp'] + columns_to_merge].copy()
    df_higher_subset.columns = ['timestamp'] + [f'{col}_15m' for col in columns_to_merge]
    
    df_result = pd.merge_asof(
        df_result.sort_values('timestamp'),
        df_higher_subset.sort_values('timestamp'),
        on='timestamp',
        direction='backward'
    )
    
    return df_result
