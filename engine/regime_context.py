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
    entry_timeframe: str = '5min',
    trend_timeframe: str = '30min',
    renko_k: float = 1.0,
    regime_lookback: int = 20
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build multi-timeframe regime context and align to entry timeframe bars.
    
    Data flow:
    1. Resample 1min → 30min for trend detection
    2. Build Renko from 30min bars
    3. Detect regime on 30min timeframe
    4. Resample 1min → entry timeframe (2/3/5min) for entries
    5. Align 30min regime context onto entry timeframe bars
    
    Args:
        df_1min: 1-minute OHLCV DataFrame with timestamp column
        entry_timeframe: Timeframe for entry signals ('2min', '3min', '5min')
        trend_timeframe: Timeframe for trend/regime detection (default: '30min')
        renko_k: Renko brick size multiplier (default: 1.0)
        regime_lookback: Lookback period for regime detection (default: 20)
        
    Returns:
        Tuple of (df_entry, df_trend) with regime context
    """
    if 'timestamp' not in df_1min.columns:
        raise ValueError("df_1min must have 'timestamp' column")
    
    df_trend = resample_to_timeframe(df_1min, trend_timeframe)
    
    renko_df = build_renko(df_trend, mode="atr", k=renko_k)
    
    renko_direction = get_renko_direction_series(df_trend, renko_df)
    
    regime_series = detect_regime(
        df_trend,
        renko_direction,
        lookback=regime_lookback
    )
    
    df_trend = df_trend.copy()
    df_trend['regime'] = regime_series
    df_trend['renko_direction'] = renko_direction
    
    df_entry = resample_to_timeframe(df_1min, entry_timeframe)
    
    df_entry = align_timeframe_context(
        df_entry,
        df_trend,
        columns_to_merge=['regime', 'renko_direction']
    )
    
    # Rename columns with generic suffix (works for any trend timeframe)
    # align_timeframe_context adds "_15m" suffix by default, rename to clean names
    rename_map = {}
    for col in df_entry.columns:
        if col.endswith('_15m'):
            clean_name = col.replace('_15m', '')
            rename_map[col] = clean_name
    
    df_entry = df_entry.rename(columns=rename_map)
    
    return df_entry, df_trend


def add_session_labels_to_entry_tf(df_1min: pd.DataFrame, df_entry: pd.DataFrame) -> pd.DataFrame:
    """
    Propagate session labels from 1-min to entry timeframe bars.
    
    Args:
        df_1min: 1-minute data with 'session' column
        df_entry: Entry timeframe data to add sessions to
        
    Returns:
        df_entry with session column added
    """
    if 'session' not in df_1min.columns:
        raise ValueError("df_1min must have 'session' column")
    
    df_entry = align_timeframe_context(
        df_entry,
        df_1min[['timestamp', 'session']],
        columns_to_merge=['session']
    )
    
    df_entry = df_entry.rename(columns={'session_15m': 'session'})
    
    return df_entry
