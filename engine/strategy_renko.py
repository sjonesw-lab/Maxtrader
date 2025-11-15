"""
Hybrid Renko-based trading strategy combining original MaxTrader momentum system
with optional ICT confluence for enhanced precision.

Signal Generation:
- Triggers on Renko brick formations (not fixed time intervals)
- Momentum/impulse from consecutive brick sequences
- Regime filtering from 30-min timeframe
- ATR-based targets (2-4 brick multiples)
- Optional ICT confluence boost
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import numpy as np


@dataclass
class RenkoSignal:
    """Trading signal generated from Renko brick formation."""
    brick_index: int
    timestamp: pd.Timestamp
    direction: str  # 'long' or 'short'
    spot: float
    target: float
    brick_count_to_target: int
    momentum_strength: float
    regime: str
    has_ict_confluence: bool = False
    meta: dict = None


def detect_momentum_impulse(
    renko_df: pd.DataFrame,
    brick_idx: int,
    lookback: int = 5,
    min_consecutive: int = 3
) -> tuple[bool, bool, float]:
    """
    Detect momentum impulse from consecutive Renko bricks.
    
    Original MaxTrader logic:
    - Look for runs of consecutive same-direction bricks
    - Bullish impulse: 3+ consecutive up bricks
    - Bearish impulse: 3+ consecutive down bricks
    
    Args:
        renko_df: Renko DataFrame with 'direction' column
        brick_idx: Current brick index
        lookback: How many bricks to analyze
        min_consecutive: Minimum consecutive bricks for impulse
        
    Returns:
        (bullish_impulse, bearish_impulse, momentum_strength)
    """
    if brick_idx < lookback:
        return False, False, 0.0
    
    window = renko_df.iloc[max(0, brick_idx - lookback):brick_idx + 1]
    directions = window['direction'].values
    
    # Count consecutive same-direction bricks from most recent
    up_streak = 0
    down_streak = 0
    current_direction = directions[-1]  # Most recent brick direction
    
    for d in reversed(directions):
        if d == current_direction:
            if d == 1:
                up_streak += 1
            elif d == -1:
                down_streak += 1
        else:
            break  # Streak ended
    
    bullish_impulse = up_streak >= min_consecutive
    bearish_impulse = down_streak >= min_consecutive
    
    # Momentum strength = ratio of consecutive bricks to lookback
    momentum_strength = max(up_streak, down_streak) / lookback
    
    return bullish_impulse, bearish_impulse, momentum_strength


def calculate_atr_target(
    df_1min: pd.DataFrame,
    current_time: pd.Timestamp,
    direction: str,
    brick_size: float,
    target_multiplier: float = 2.5,
    atr_period: int = 14
) -> float:
    """
    Calculate target price using ATR-based logic.
    
    Original MaxTrader approach:
    - Targets = 2-4 Renko bricks OR 1.5-2.5x ATR
    - Uses whichever is larger for asymmetric payoff
    
    Args:
        df_1min: 1-minute OHLCV data
        current_time: Signal timestamp
        direction: 'long' or 'short'
        brick_size: Current Renko brick size
        target_multiplier: ATR multiple for target (default: 2.5)
        atr_period: ATR calculation period
        
    Returns:
        Target price
    """
    # Get recent data up to signal time
    recent = df_1min[df_1min['timestamp'] <= current_time].tail(atr_period * 2)
    
    if len(recent) < atr_period:
        # Fallback: use brick-based target
        current_price = recent['close'].iloc[-1]
        brick_target = brick_size * 3  # 3-brick target
        if direction == 'long':
            return current_price + brick_target
        else:
            return current_price - brick_target
    
    # Calculate ATR
    high = recent['high']
    low = recent['low']
    close = recent['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period).mean().iloc[-1]
    
    current_price = recent['close'].iloc[-1]
    
    # Choose larger of brick-target or ATR-target
    brick_target = brick_size * 3
    atr_target = atr * target_multiplier
    
    target_distance = max(brick_target, atr_target)
    
    if direction == 'long':
        return current_price + target_distance
    else:
        return current_price - target_distance


def check_ict_confluence(
    df_1min: pd.DataFrame,
    timestamp: pd.Timestamp,
    direction: str
) -> bool:
    """
    Optional: Check if ICT structures confirm the Renko signal.
    
    This is an enhancement, not a requirement.
    If ICT structures align, signal quality is boosted.
    
    Args:
        df_1min: 1-minute data with ICT features
        timestamp: Signal timestamp
        direction: 'long' or 'short'
        
    Returns:
        True if ICT structures confirm direction
    """
    # Find corresponding row in 1-min data
    mask = df_1min['timestamp'] == timestamp
    
    if not mask.any():
        return False
    
    row = df_1min[mask].iloc[0]
    
    # Check for ICT confluence (if columns exist)
    has_sweep = 'sweep_bullish' in row and 'sweep_bearish' in row
    has_displacement = 'displacement_bullish' in row and 'displacement_bearish' in row
    
    if not (has_sweep and has_displacement):
        return False
    
    if direction == 'long':
        return row.get('sweep_bullish', False) and row.get('displacement_bullish', False)
    else:
        return row.get('sweep_bearish', False) and row.get('displacement_bearish', False)


def generate_renko_signals(
    df_1min: pd.DataFrame,
    renko_df: pd.DataFrame,
    regime_series: pd.Series,
    brick_size: float,
    min_momentum: float = 0.6,
    enable_ict_filter: bool = False
) -> List[RenkoSignal]:
    """
    Generate trading signals from Renko brick formations.
    
    Hybrid approach:
    1. Renko momentum impulse (original system)
    2. Regime filter (keep trend bias)
    3. ATR-based targets (2-4 bricks or 1.5-2.5x ATR)
    4. Optional ICT confluence boost
    
    Args:
        df_1min: 1-minute OHLCV data (for ATR and ICT)
        renko_df: Renko DataFrame with timestamp, brick_close, direction
        regime_series: Regime labels aligned to 1-min data
        brick_size: Renko brick size
        min_momentum: Minimum momentum strength (default: 0.6)
        enable_ict_filter: Require ICT confluence (default: False)
        
    Returns:
        List of RenkoSignal objects
    """
    signals = []
    
    for idx in range(len(renko_df)):
        brick = renko_df.iloc[idx]
        timestamp = brick['timestamp']
        
        # NY SESSION FILTER: Only trade 9:45 AM - 3:45 PM ET (per successful config)
        hour = timestamp.hour
        minute = timestamp.minute
        time_in_minutes = hour * 60 + minute
        start_time = 9 * 60 + 45  # 9:45 AM = 585 minutes
        end_time = 15 * 60 + 45   # 3:45 PM = 945 minutes
        
        if not (start_time <= time_in_minutes <= end_time):
            continue  # Skip signals outside NY core trading hours
        
        # Detect momentum impulse (original 3+ brick logic)
        bullish_impulse, bearish_impulse, momentum_strength = detect_momentum_impulse(
            renko_df, idx, lookback=5, min_consecutive=3
        )
        
        if momentum_strength < min_momentum:
            continue
        
        # Get regime at this timestamp
        regime_mask = df_1min['timestamp'] <= timestamp
        if not regime_mask.any():
            continue
        
        regime_row = df_1min[regime_mask].iloc[-1]
        regime = regime_row.get('regime', 'unknown')
        
        # Long signal: bullish impulse + (bull_trend or sideways regime)
        if bullish_impulse and regime in ['bull_trend', 'sideways']:
            direction = 'long'
        # Short signal: bearish impulse + (bear_trend or sideways regime)
        elif bearish_impulse and regime in ['bear_trend', 'sideways']:
            direction = 'short'
        else:
            continue
        
        # Optional: Check ICT confluence
        has_ict = check_ict_confluence(df_1min, timestamp, direction)
        
        if enable_ict_filter and not has_ict:
            continue
        
        # Calculate ATR-based target
        target = calculate_atr_target(
            df_1min, timestamp, direction, brick_size, target_multiplier=2.5
        )
        
        spot = brick['brick_close']
        brick_count = 3  # Default 3-brick target
        
        signal = RenkoSignal(
            brick_index=idx,
            timestamp=timestamp,
            direction=direction,
            spot=spot,
            target=target,
            brick_count_to_target=brick_count,
            momentum_strength=momentum_strength,
            regime=regime,
            has_ict_confluence=has_ict,
            meta={
                'brick_direction': int(brick['direction']),
                'brick_size': brick_size
            }
        )
        
        signals.append(signal)
    
    return signals
