"""
Trading strategy module for signal generation.

Combines all ICT structures to generate trading signals
during NY open window (09:30-11:00).
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import numpy as np


@dataclass
class Signal:
    """Trading signal."""
    index: int
    timestamp: pd.Timestamp
    direction: str
    spot: float
    target: float
    source_session: Optional[str]
    meta: dict


def in_ny_open_window(ts: pd.Timestamp) -> bool:
    """
    Check if timestamp is within NY open trading window (09:30-11:00).
    
    Args:
        ts: Timestamp to check (must be tz-aware America/New_York)
        
    Returns:
        True if in window, False otherwise
    """
    hour = ts.hour
    minute = ts.minute
    time_decimal = hour + minute / 60.0
    
    return (time_decimal >= 9.5) and (time_decimal < 11.0)


def find_target(
    df: pd.DataFrame,
    current_idx: int,
    direction: str,
    lookback: int = 100
) -> Optional[float]:
    """
    Find target price based on recent swing highs/lows.
    
    For long: nearest prior swing high / liquidity zone above
    For short: nearest prior swing low / liquidity zone below
    
    Args:
        df: DataFrame with market data
        current_idx: Current bar index
        direction: 'long' or 'short'
        lookback: Number of bars to look back
        
    Returns:
        Target price or None
    """
    start_idx = max(0, current_idx - lookback)
    recent_data = df.iloc[start_idx:current_idx]
    
    if len(recent_data) == 0:
        return None
    
    current_price = df.loc[current_idx, 'close']
    
    if direction == 'long':
        candidates = []
        
        for idx in recent_data.index:
            if pd.notna(recent_data.loc[idx, 'asia_high']):
                candidates.append(recent_data.loc[idx, 'asia_high'])
            if pd.notna(recent_data.loc[idx, 'london_high']):
                candidates.append(recent_data.loc[idx, 'london_high'])
        
        highs_above = [c for c in candidates if c > current_price]
        
        if highs_above:
            return min(highs_above)
        
        return current_price * 1.01
    
    else:
        candidates = []
        
        for idx in recent_data.index:
            if pd.notna(recent_data.loc[idx, 'asia_low']):
                candidates.append(recent_data.loc[idx, 'asia_low'])
            if pd.notna(recent_data.loc[idx, 'london_low']):
                candidates.append(recent_data.loc[idx, 'london_low'])
        
        lows_below = [c for c in candidates if c < current_price]
        
        if lows_below:
            return max(lows_below)
        
        return current_price * 0.99


def generate_signals(df: pd.DataFrame, enable_ob_filter: bool = False) -> List[Signal]:
    """
    Generate trading signals using ICT structures within NY window.
    
    LONG signal requires:
    1. Time in NY window (09:30-11:00)
    2. Bullish sweep of Asia OR London low
    3. Bullish displacement candle after sweep
    4. Bullish FVG created by displacement
    5. Bullish MSS (price breaking prior swing high)
    6. (Optional) Price interacts with bullish OB zone
    
    SHORT signal is the mirror.
    
    Args:
        df: DataFrame with all ICT features
        enable_ob_filter: Require OB confluence (default: False)
        
    Returns:
        List of Signal objects
    """
    signals = []
    
    for idx in df.index:
        row = df.loc[idx]
        
        if not in_ny_open_window(row['timestamp']):
            continue
        
        bullish_setup = (
            row['sweep_bullish'] and
            row['displacement_bullish'] and
            row['fvg_bullish'] and
            row['mss_bullish']
        )
        
        if enable_ob_filter:
            bullish_setup = bullish_setup and row['ob_bullish']
        
        if bullish_setup:
            target = find_target(df, idx, 'long')
            
            if target is not None:
                signal = Signal(
                    index=idx,
                    timestamp=row['timestamp'],
                    direction='long',
                    spot=row['close'],
                    target=target,
                    source_session=row['sweep_source'],
                    meta={
                        'sweep': 'bullish',
                        'displacement': 'bullish',
                        'fvg': 'bullish',
                        'mss': 'bullish',
                        'ob': row['ob_bullish']
                    }
                )
                signals.append(signal)
        
        bearish_setup = (
            row['sweep_bearish'] and
            row['displacement_bearish'] and
            row['fvg_bearish'] and
            row['mss_bearish']
        )
        
        if enable_ob_filter:
            bearish_setup = bearish_setup and row['ob_bearish']
        
        if bearish_setup:
            target = find_target(df, idx, 'short')
            
            if target is not None:
                signal = Signal(
                    index=idx,
                    timestamp=row['timestamp'],
                    direction='short',
                    spot=row['close'],
                    target=target,
                    source_session=row['sweep_source'],
                    meta={
                        'sweep': 'bearish',
                        'displacement': 'bearish',
                        'fvg': 'bearish',
                        'mss': 'bearish',
                        'ob': row['ob_bearish']
                    }
                )
                signals.append(signal)
    
    return signals
