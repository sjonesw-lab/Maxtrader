"""
Multi-timeframe regime context module.

Builds Renko and detects regimes on 15-minute bars,
then aligns the context to 3-minute bars for trading.
"""

import pandas as pd
from engine.timeframes import resample_to_timeframe, align_timeframe_context
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime


def build_regime_context(
    df_1min: pd.DataFrame,
    renko_k: float = 1.0,
    regime_lookback: int = 20
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build 15-minute regime context and align to 3-minute bars.
    
    Data flow:
    1. Resample 1min → 15min for trend detection
    2. Build Renko from 15min bars
    3. Detect regime on 15min timeframe
    4. Resample 1min → 3min for entries
    5. Align 15min regime context onto 3min bars
    
    Args:
        df_1min: 1-minute OHLCV DataFrame with timestamp column
        renko_k: Renko brick size multiplier (default: 1.0)
        regime_lookback: Lookback period for regime detection (default: 20)
        
    Returns:
        Tuple of (df_3min, df_15min) with regime context
    """
    if 'timestamp' not in df_1min.columns:
        raise ValueError("df_1min must have 'timestamp' column")
    
    df_15min = resample_to_timeframe(df_1min, '15min')
    
    renko_df = build_renko(df_15min, mode="atr", k=renko_k)
    
    renko_direction = get_renko_direction_series(df_15min, renko_df)
    
    regime_series = detect_regime(
        df_15min,
        renko_direction,
        lookback=regime_lookback
    )
    
    df_15min = df_15min.copy()
    df_15min['regime'] = regime_series
    df_15min['renko_direction'] = renko_direction
    
    df_3min = resample_to_timeframe(df_1min, '3min')
    
    df_3min = align_timeframe_context(
        df_3min,
        df_15min,
        columns_to_merge=['regime', 'renko_direction']
    )
    
    df_3min = df_3min.rename(columns={
        'regime_15m': 'regime',
        'renko_direction_15m': 'renko_direction'
    })
    
    return df_3min, df_15min


def add_session_labels_to_3min(df_1min: pd.DataFrame, df_3min: pd.DataFrame) -> pd.DataFrame:
    """
    Propagate session labels from 1-min to 3-min bars.
    
    Args:
        df_1min: 1-minute data with 'session' column
        df_3min: 3-minute data to add sessions to
        
    Returns:
        df_3min with session column added
    """
    if 'session' not in df_1min.columns:
        raise ValueError("df_1min must have 'session' column")
    
    df_3min = align_timeframe_context(
        df_3min,
        df_1min[['timestamp', 'session']],
        columns_to_merge=['session']
    )
    
    df_3min = df_3min.rename(columns={'session_15m': 'session'})
    
    return df_3min
