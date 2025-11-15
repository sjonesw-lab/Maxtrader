"""
Renko chart builder for trend visualization and regime detection.

Supports ATR-based and fixed brick sizing.
"""

import pandas as pd
import numpy as np
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class RenkoBrick:
    """Single Renko brick."""
    timestamp: pd.Timestamp
    brick_close: float
    direction: int  # +1 for up, -1 for down


def build_renko(
    df: pd.DataFrame,
    mode: str = "atr",
    k: float = 1.0,
    fixed_brick_size: float = 1.0,
    atr_period: int = 14
) -> pd.DataFrame:
    """
    Build Renko chart from standard OHLCV data.
    
    Args:
        df: DataFrame with columns: timestamp, open, high, low, close
        mode: "atr" or "fixed" brick sizing
        k: Multiplier for ATR-based brick size (default: 1.0)
        fixed_brick_size: Fixed brick size when mode="fixed" (default: 1.0)
        atr_period: ATR period for dynamic brick sizing (default: 14)
        
    Returns:
        DataFrame with columns: timestamp, brick_close, direction
    """
    if len(df) == 0:
        return pd.DataFrame(columns=['timestamp', 'brick_close', 'direction'])
    
    # Calculate brick size
    if mode == "atr":
        brick_size = _calculate_atr_brick_size(df, k, atr_period)
    else:
        brick_size = fixed_brick_size
    
    # Build bricks
    bricks = _build_renko_bricks(df, brick_size)
    
    # Convert to DataFrame
    renko_df = pd.DataFrame([
        {
            'timestamp': brick.timestamp,
            'brick_close': brick.brick_close,
            'direction': brick.direction,
            'brick_size': brick_size  # Store brick size for target calculation
        }
        for brick in bricks
    ])
    
    return renko_df


def _calculate_atr_brick_size(df: pd.DataFrame, k: float, period: int) -> float:
    """Calculate ATR-based brick size."""
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    # Use median ATR to avoid early NaN issues
    median_atr = atr.median()
    
    brick_size = k * median_atr
    
    return max(brick_size, 0.01)  # Minimum brick size


def _build_renko_bricks(df: pd.DataFrame, brick_size: float) -> List[RenkoBrick]:
    """
    Build Renko bricks from price data.
    
    Algorithm:
    - Start with first close price
    - For each subsequent bar, check if price moved enough to form new brick(s)
    - Up brick: price rises by brick_size
    - Down brick: price falls by brick_size
    """
    bricks = []
    
    if len(df) == 0:
        return bricks
    
    # Initialize with first price
    current_brick_close = df['close'].iloc[0]
    current_timestamp = df['timestamp'].iloc[0]
    
    for idx in range(len(df)):
        row = df.iloc[idx]
        price = row['close']
        timestamp = row['timestamp']
        
        # Check for up bricks
        while price >= current_brick_close + brick_size:
            current_brick_close += brick_size
            bricks.append(RenkoBrick(
                timestamp=timestamp,
                brick_close=current_brick_close,
                direction=1
            ))
        
        # Check for down bricks
        while price <= current_brick_close - brick_size:
            current_brick_close -= brick_size
            bricks.append(RenkoBrick(
                timestamp=timestamp,
                brick_close=current_brick_close,
                direction=-1
            ))
    
    return bricks


def get_renko_direction_series(df: pd.DataFrame, renko_df: pd.DataFrame) -> pd.Series:
    """
    Align Renko directions with original DataFrame.
    
    For each bar in df, find the most recent Renko brick and return its direction.
    
    Args:
        df: Original OHLCV DataFrame
        renko_df: Renko DataFrame from build_renko
        
    Returns:
        Series of Renko directions aligned with df.index
    """
    if len(renko_df) == 0:
        return pd.Series(0, index=df.index)
    
    directions = []
    
    for idx in range(len(df)):
        timestamp = df['timestamp'].iloc[idx]
        
        # Find most recent Renko brick before or at this timestamp
        recent_bricks = renko_df[renko_df['timestamp'] <= timestamp]
        
        if len(recent_bricks) > 0:
            direction = recent_bricks['direction'].iloc[-1]
        else:
            direction = 0  # No brick yet
        
        directions.append(direction)
    
    return pd.Series(directions, index=df.index)


def calculate_renko_trend_strength(renko_df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """
    Calculate trend strength from Renko bricks.
    
    Trend strength = sum of last N brick directions / N
    Returns values from -1 (strong down) to +1 (strong up)
    
    Args:
        renko_df: Renko DataFrame
        lookback: Number of bricks to consider
        
    Returns:
        Series of trend strength values
    """
    if len(renko_df) == 0:
        return pd.Series(dtype=float)
    
    trend_strength = renko_df['direction'].rolling(window=lookback, min_periods=1).mean()
    
    return trend_strength
