"""
Wave analysis for Renko-based trading system.

Implements successful backtest logic:
- Wave 1 impulse: min 3 bricks same direction
- Retracement bands: shallow (<33%), healthy (33-62%), skip deep (>62%)
- Entry distance cap: 1.5 bricks from P2 (wave end)
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import pandas as pd
import numpy as np


@dataclass
class Wave:
    """Renko wave structure."""
    start_idx: int
    end_idx: int
    direction: int  # +1 for up, -1 for down
    brick_count: int
    wave_height: float  # Total price movement
    p1_price: float  # Wave start
    p2_price: float  # Wave end
    timestamp: pd.Timestamp


@dataclass
class Retracement:
    """Retracement after wave impulse."""
    wave: Wave
    retrace_pct: float  # % of wave retraced
    retrace_type: str  # 'shallow', 'healthy', 'deep'
    current_price: float
    entry_valid: bool  # True if within 1.5 bricks of P2


def detect_wave(
    renko_df: pd.DataFrame,
    end_idx: int,
    min_bricks: int = 3
) -> Optional[Wave]:
    """
    Detect wave impulse from Renko bricks.
    
    Args:
        renko_df: Renko DataFrame with direction, brick_close
        end_idx: Current brick index (potential wave end)
        min_bricks: Minimum consecutive bricks for wave (default: 3)
        
    Returns:
        Wave object if valid impulse found, else None
    """
    if end_idx < min_bricks:
        return None
    
    # Look back for consecutive same-direction bricks
    current_direction = renko_df.iloc[end_idx]['direction']
    
    # Count consecutive bricks
    brick_count = 0
    start_idx = end_idx
    
    for i in range(end_idx, -1, -1):
        if renko_df.iloc[i]['direction'] == current_direction:
            brick_count += 1
            start_idx = i
        else:
            break
    
    # Must have min_bricks consecutive
    if brick_count < min_bricks:
        return None
    
    # P1 = actual swing turn price (last opposite-direction brick close, or swing low/high)
    # This is the brick BEFORE the wave started
    if start_idx > 0:
        # Use the brick close BEFORE the wave impulse started
        p1_price = renko_df.iloc[start_idx - 1]['brick_close']
    else:
        # Edge case: wave starts at beginning of data
        p1_price = renko_df.iloc[start_idx]['brick_close']
    
    # P2 = wave end price
    p2_price = renko_df.iloc[end_idx]['brick_close']
    
    # Wave height = full impulse from turn to end
    wave_height = abs(p2_price - p1_price)
    timestamp = renko_df.iloc[end_idx]['timestamp']
    
    return Wave(
        start_idx=start_idx,
        end_idx=end_idx,
        direction=int(current_direction),
        brick_count=brick_count,
        wave_height=wave_height,
        p1_price=p1_price,
        p2_price=p2_price,
        timestamp=timestamp
    )


def analyze_retracement(
    wave: Wave,
    current_price: float,
    brick_size: float,
    max_entry_distance: float = 1.5
) -> Retracement:
    """
    Analyze retracement from wave and determine entry validity.
    
    Retracement bands:
    - shallow: < 33% (very strong momentum)
    - healthy: 33-62% (ideal entry zone)
    - deep: > 62% (skip - momentum lost)
    
    Args:
        wave: Wave object
        current_price: Current market price
        brick_size: Renko brick size
        max_entry_distance: Max bricks from P2 to enter (default: 1.5)
        
    Returns:
        Retracement object with analysis
    """
    # Calculate retracement percentage
    if wave.direction == 1:  # Up wave
        retrace_amount = wave.p2_price - current_price
    else:  # Down wave
        retrace_amount = current_price - wave.p2_price
    
    retrace_pct = (retrace_amount / wave.wave_height) if wave.wave_height > 0 else 0
    
    # Classify retracement
    if retrace_pct < 0.33:
        retrace_type = 'shallow'
    elif retrace_pct < 0.62:
        retrace_type = 'healthy'
    else:
        retrace_type = 'deep'
    
    # Check entry distance from P2
    distance_from_p2 = abs(current_price - wave.p2_price)
    distance_in_bricks = distance_from_p2 / brick_size if brick_size > 0 else 0
    
    # Valid entry: not deep retrace AND within distance cap
    entry_valid = (retrace_type != 'deep') and (distance_in_bricks <= max_entry_distance)
    
    return Retracement(
        wave=wave,
        retrace_pct=retrace_pct,
        retrace_type=retrace_type,
        current_price=current_price,
        entry_valid=entry_valid
    )


def calculate_wave_targets(
    wave: Wave,
    retrace: Retracement
) -> Tuple[float, float]:
    """
    Calculate profit targets based on wave height.
    
    TP1 = 1.0× wave height (conservative)
    TP2 = 1.618× wave height (Fibonacci extension)
    
    Adjust based on retracement quality:
    - shallow retrace: use 1.25× and 1.618×
    - healthy retrace: use 1.0× and 1.618×
    
    Args:
        wave: Wave object
        retrace: Retracement object
        
    Returns:
        (tp1, tp2) target prices
    """
    # Base multipliers - use conservative 1.0× for both to improve win rate
    # (Shallow momentum already captured by earlier entry, no need for aggressive targets)
    tp1_mult = 1.0
    tp2_mult = 1.618
    
    # Calculate targets from P2 (wave end)
    if wave.direction == 1:  # Long
        tp1 = wave.p2_price + (wave.wave_height * tp1_mult)
        tp2 = wave.p2_price + (wave.wave_height * tp2_mult)
    else:  # Short
        tp1 = wave.p2_price - (wave.wave_height * tp1_mult)
        tp2 = wave.p2_price - (wave.wave_height * tp2_mult)
    
    return tp1, tp2


def find_valid_wave_entry(
    renko_df: pd.DataFrame,
    current_idx: int,
    brick_size: float,
    min_bricks: int = 3,
    max_entry_distance: float = 1.5
) -> Optional[Tuple[Wave, Retracement, float, float]]:
    """
    Find valid wave entry setup at current brick.
    
    Returns wave, retracement, tp1, tp2 if valid setup found.
    """
    # Detect wave
    wave = detect_wave(renko_df, current_idx, min_bricks)
    if wave is None:
        return None
    
    # Analyze retracement
    current_price = renko_df.iloc[current_idx]['brick_close']
    retrace = analyze_retracement(wave, current_price, brick_size, max_entry_distance)
    
    # Skip if not valid entry
    if not retrace.entry_valid:
        return None
    
    # Calculate targets
    tp1, tp2 = calculate_wave_targets(wave, retrace)
    
    return wave, retrace, tp1, tp2
