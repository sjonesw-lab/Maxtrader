"""
Market regime detection for filtering trading signals.

Classifies market into bull_trend, bear_trend, or sideways regimes
using Renko direction, ATR, and price slope.
"""

import pandas as pd
import numpy as np
from typing import Optional


def detect_regime(
    df: pd.DataFrame,
    renko_direction: pd.Series,
    lookback: int = 20,
    trend_threshold: float = 0.3,
    slope_threshold: float = 0.0
) -> pd.Series:
    """
    Detect market regime for each bar.
    
    Classification logic:
    - bull_trend: Renko mostly up AND price slope positive
    - bear_trend: Renko mostly down AND price slope negative
    - sideways: Otherwise (mixed/choppy conditions)
    
    Args:
        df: DataFrame with OHLC data
        renko_direction: Series of Renko directions (+1/-1/0) aligned with df
        lookback: Number of bars for regime calculation (default: 20)
        trend_threshold: Threshold for trend strength (default: 0.3)
        slope_threshold: Threshold for price slope (default: 0.0)
        
    Returns:
        Series of regime labels: "bull_trend", "bear_trend", "sideways"
    """
    regimes = []
    
    # Calculate rolling slope of close prices
    price_slope = _calculate_price_slope(df['close'], lookback)
    
    # Calculate Renko trend strength (average direction over lookback)
    renko_strength = renko_direction.rolling(window=lookback, min_periods=1).mean()
    
    for idx in range(len(df)):
        slope = price_slope.iloc[idx] if not pd.isna(price_slope.iloc[idx]) else 0
        renko_avg = renko_strength.iloc[idx] if not pd.isna(renko_strength.iloc[idx]) else 0
        
        # Bull trend: strong up Renko + positive slope
        if renko_avg > trend_threshold and slope > slope_threshold:
            regime = "bull_trend"
        
        # Bear trend: strong down Renko + negative slope
        elif renko_avg < -trend_threshold and slope < -slope_threshold:
            regime = "bear_trend"
        
        # Sideways: everything else
        else:
            regime = "sideways"
        
        regimes.append(regime)
    
    return pd.Series(regimes, index=df.index)


def _calculate_price_slope(prices: pd.Series, lookback: int) -> pd.Series:
    """
    Calculate rolling price slope using linear regression.
    
    Args:
        prices: Series of prices
        lookback: Window size for slope calculation
        
    Returns:
        Series of slopes (normalized by price level)
    """
    slopes = []
    
    for idx in range(len(prices)):
        if idx < lookback - 1:
            slopes.append(0.0)
            continue
        
        # Get window of prices
        window = prices.iloc[idx - lookback + 1:idx + 1]
        
        if len(window) < 2:
            slopes.append(0.0)
            continue
        
        # Simple linear regression
        x = np.arange(len(window))
        y = window.values
        
        # Calculate slope
        if len(x) > 0 and len(y) > 0:
            slope = np.polyfit(x, y, 1)[0]
            
            # Normalize by current price to make comparable across price levels
            current_price = prices.iloc[idx]
            if current_price > 0:
                normalized_slope = slope / current_price
            else:
                normalized_slope = 0.0
        else:
            normalized_slope = 0.0
        
        slopes.append(normalized_slope)
    
    return pd.Series(slopes, index=prices.index)


def get_regime_stats(df: pd.DataFrame, regime_col: str = 'regime') -> dict:
    """
    Calculate statistics about regime distribution.
    
    Args:
        df: DataFrame with regime column
        regime_col: Name of regime column (default: 'regime')
        
    Returns:
        Dictionary with regime counts and percentages
    """
    regime_counts = df[regime_col].value_counts()
    total = len(df)
    
    stats = {
        'total_bars': total,
        'regime_counts': regime_counts.to_dict(),
        'regime_percentages': {
            regime: (count / total * 100) if total > 0 else 0
            for regime, count in regime_counts.items()
        }
    }
    
    return stats


def filter_by_regime(
    df: pd.DataFrame,
    direction: str,
    regime_col: str = 'regime',
    allow_sideways: bool = True
) -> pd.Series:
    """
    Create boolean mask for filtering signals by regime.
    
    Args:
        df: DataFrame with regime column
        direction: 'long' or 'short'
        regime_col: Name of regime column (default: 'regime')
        allow_sideways: Allow trades in sideways regime (default: True)
        
    Returns:
        Boolean Series indicating which bars pass regime filter
    """
    regimes = df[regime_col]
    
    if direction == 'long':
        if allow_sideways:
            mask = regimes.isin(['bull_trend', 'sideways'])
        else:
            mask = regimes == 'bull_trend'
    
    elif direction == 'short':
        if allow_sideways:
            mask = regimes.isin(['bear_trend', 'sideways'])
        else:
            mask = regimes == 'bear_trend'
    
    else:
        # Unknown direction, allow all
        mask = pd.Series(True, index=df.index)
    
    return mask
