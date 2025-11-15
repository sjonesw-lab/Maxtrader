"""
ICT confluence scoring and target calculation.

Provides additional signal quality filters and alternative target generation
based on ICT structures (sweeps, displacement, FVG, MSS, order blocks).
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import pandas as pd
import numpy as np


@dataclass
class ICTConfluence:
    """ICT structure confluence score."""
    has_sweep: bool
    has_displacement: bool
    has_fvg: bool
    has_mss: bool
    has_order_block: bool
    confluence_score: float  # [0, 1]
    sweep_source: Optional[str] = None
    structure_detail: Optional[dict] = None


def calculate_ict_confluence(
    df_1min: pd.DataFrame,
    timestamp: pd.Timestamp,
    direction: str,
    lookback_bars: int = 10
) -> ICTConfluence:
    """
    Calculate ICT structure confluence for a given signal.
    
    Checks for presence of:
    - Liquidity sweep
    - Displacement candle
    - Fair Value Gap (FVG)
    - Market Structure Shift (MSS)
    - Order Block (OB)
    
    Each structure adds to confluence score if aligned with direction.
    
    Args:
        df_1min: 1-minute data with ICT structure columns
        timestamp: Signal timestamp
        direction: 'long' or 'short'
        lookback_bars: How many bars to look back for structures
        
    Returns:
        ICTConfluence object with scores and structure flags
    """
    # Verify required columns exist
    required_cols = [
        'sweep_bullish', 'sweep_bearish', 'displacement_bullish', 'displacement_bearish',
        'fvg_bullish', 'fvg_bearish', 'mss_bullish', 'mss_bearish',
        'ob_bullish', 'ob_bearish', 'sweep_source'
    ]
    
    missing = [col for col in required_cols if col not in df_1min.columns]
    if missing:
        # Return zero confluence if ICT columns missing
        return ICTConfluence(
            has_sweep=False,
            has_displacement=False,
            has_fvg=False,
            has_mss=False,
            has_order_block=False,
            confluence_score=0.0
        )
    
    # Find index for this timestamp
    mask = df_1min['timestamp'] <= timestamp
    if not mask.any():
        return ICTConfluence(
            has_sweep=False,
            has_displacement=False,
            has_fvg=False,
            has_mss=False,
            has_order_block=False,
            confluence_score=0.0
        )
    
    current_idx = df_1min[mask].index[-1]
    start_idx = max(0, current_idx - lookback_bars)
    lookback_df = df_1min.iloc[start_idx:current_idx+1]  # Use iloc for clean slicing
    
    # Check for structures aligned with direction
    if direction == 'long':
        has_sweep = lookback_df['sweep_bullish'].any()
        has_displacement = lookback_df['displacement_bullish'].any()
        has_fvg = lookback_df['fvg_bullish'].any()
        has_mss = lookback_df['mss_bullish'].any()
        has_order_block = lookback_df['ob_bullish'].any()
        
        # Get sweep source if exists
        sweep_rows = lookback_df[lookback_df['sweep_bullish']]
        sweep_source = sweep_rows['sweep_source'].iloc[-1] if len(sweep_rows) > 0 else None
        
    else:  # short
        has_sweep = lookback_df['sweep_bearish'].any()
        has_displacement = lookback_df['displacement_bearish'].any()
        has_fvg = lookback_df['fvg_bearish'].any()
        has_mss = lookback_df['mss_bearish'].any()
        has_order_block = lookback_df['ob_bearish'].any()
        
        # Get sweep source if exists
        sweep_rows = lookback_df[lookback_df['sweep_bearish']]
        sweep_source = sweep_rows['sweep_source'].iloc[-1] if len(sweep_rows) > 0 else None
    
    # Calculate confluence score (weighted by structure importance)
    weights = {
        'sweep': 0.25,      # Liquidity sweep is critical
        'displacement': 0.25,  # Strong momentum confirmation
        'mss': 0.20,        # Structure shift
        'fvg': 0.15,        # Gap fill opportunity
        'order_block': 0.15  # Institutional zone
    }
    
    score = 0.0
    if has_sweep:
        score += weights['sweep']
    if has_displacement:
        score += weights['displacement']
    if has_mss:
        score += weights['mss']
    if has_fvg:
        score += weights['fvg']
    if has_order_block:
        score += weights['order_block']
    
    structure_detail = {
        'sweep': has_sweep,
        'displacement': has_displacement,
        'mss': has_mss,
        'fvg': has_fvg,
        'order_block': has_order_block
    }
    
    return ICTConfluence(
        has_sweep=has_sweep,
        has_displacement=has_displacement,
        has_fvg=has_fvg,
        has_mss=has_mss,
        has_order_block=has_order_block,
        confluence_score=score,
        sweep_source=sweep_source,
        structure_detail=structure_detail
    )


def calculate_ict_targets(
    df_1min: pd.DataFrame,
    timestamp: pd.Timestamp,
    direction: str,
    entry_price: float,
    lookback_bars: int = 20
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate profit targets based on ICT structures.
    
    Target logic:
    - TP1: Next session high/low or recent swing
    - TP2: Extended swing or FVG fill target
    
    Args:
        df_1min: 1-minute data with session and swing data
        timestamp: Signal timestamp
        direction: 'long' or 'short'
        entry_price: Entry price
        lookback_bars: Bars to analyze for target selection
        
    Returns:
        (tp1, tp2) tuple or (None, None) if no valid targets
    """
    # Verify required columns
    required_cols = ['asia_high', 'asia_low', 'london_high', 'london_low']
    missing = [col for col in required_cols if col not in df_1min.columns]
    if missing:
        return None, None
    
    # Find current position
    mask = df_1min['timestamp'] <= timestamp
    if not mask.any():
        return None, None
    
    current_idx = df_1min[mask].index[-1]
    
    # Look back for structures (no look-ahead bias)
    start_idx = max(0, current_idx - lookback_bars)
    lookback_df = df_1min.iloc[start_idx:current_idx+1]
    
    if direction == 'long':
        # TP1: Recent session high or swing high
        session_high = lookback_df['asia_high'].max()
        london_high = lookback_df['london_high'].max()
        
        # Get highest valid swing point
        swing_target = max(
            session_high if pd.notna(session_high) else entry_price,
            london_high if pd.notna(london_high) else entry_price
        )
        
        # TP1: Conservative target (next resistance)
        tp1 = swing_target if swing_target > entry_price else entry_price * 1.005
        
        # TP2: Extended target (1.618x move)
        move_size = tp1 - entry_price
        tp2 = entry_price + (move_size * 1.618)
        
    else:  # short
        # TP1: Recent session low or swing low
        session_low = lookback_df['asia_low'].min()
        london_low = lookback_df['london_low'].min()
        
        # Get lowest valid swing point
        swing_target = min(
            session_low if pd.notna(session_low) else entry_price,
            london_low if pd.notna(london_low) else entry_price
        )
        
        # TP1: Conservative target (next support)
        tp1 = swing_target if swing_target < entry_price else entry_price * 0.995
        
        # TP2: Extended target (1.618x move)
        move_size = entry_price - tp1
        tp2 = entry_price - (move_size * 1.618)
    
    return tp1, tp2


def combine_wave_and_ict_targets(
    wave_tp1: float,
    wave_tp2: float,
    ict_tp1: Optional[float],
    ict_tp2: Optional[float],
    entry_price: float,
    direction: str
) -> Tuple[float, float]:
    """
    Select best targets by comparing wave-based and ICT-based targets.
    
    Strategy:
    - Use CLOSER target (by distance from entry) for TP1 (higher win rate)
    - Use FARTHER target (by distance from entry) for TP2 (asymmetric payoff)
    - Validates directional constraints (longs > entry, shorts < entry)
    
    Args:
        wave_tp1: Wave-based first target
        wave_tp2: Wave-based extension target
        ict_tp1: ICT-based first target (optional)
        ict_tp2: ICT-based extension target (optional)
        entry_price: Entry price for distance calculation
        direction: 'long' or 'short'
        
    Returns:
        (final_tp1, final_tp2) tuple
    """
    # Default to wave targets
    final_tp1 = wave_tp1
    final_tp2 = wave_tp2
    
    # If ICT targets available, compare by DISTANCE from entry
    if ict_tp1 is not None and ict_tp2 is not None:
        # Validate directional constraints
        if direction == 'long':
            # Long targets must be above entry
            if ict_tp1 <= entry_price or ict_tp2 <= entry_price:
                return final_tp1, final_tp2  # Skip invalid ICT targets
            
            # Compare distances from entry
            wave_tp1_dist = wave_tp1 - entry_price
            ict_tp1_dist = ict_tp1 - entry_price
            wave_tp2_dist = wave_tp2 - entry_price
            ict_tp2_dist = ict_tp2 - entry_price
            
            # TP1: closer target (higher win rate)
            final_tp1 = ict_tp1 if ict_tp1_dist < wave_tp1_dist else wave_tp1
            
            # TP2: farther target (bigger wins)
            final_tp2 = ict_tp2 if ict_tp2_dist > wave_tp2_dist else wave_tp2
            
        else:  # short
            # Short targets must be below entry
            if ict_tp1 >= entry_price or ict_tp2 >= entry_price:
                return final_tp1, final_tp2  # Skip invalid ICT targets
            
            # Compare distances from entry
            wave_tp1_dist = entry_price - wave_tp1
            ict_tp1_dist = entry_price - ict_tp1
            wave_tp2_dist = entry_price - wave_tp2
            ict_tp2_dist = entry_price - ict_tp2
            
            # TP1: closer target (higher win rate)
            final_tp1 = ict_tp1 if ict_tp1_dist < wave_tp1_dist else wave_tp1
            
            # TP2: farther target (bigger wins)
            final_tp2 = ict_tp2 if ict_tp2_dist > wave_tp2_dist else wave_tp2
    
    return final_tp1, final_tp2


def blend_confidence_scores(
    wave_confidence: float,
    ict_confluence_score: float
) -> float:
    """
    Blend wave and ICT confidence scores multiplicatively.
    
    Formula: final_conf = wave_conf * (0.5 + 0.5 * ict_score)
    
    This keeps:
    - Scores bounded in [0, 1]
    - Wave confidence as primary driver
    - ICT as 0-50% boost
    
    Args:
        wave_confidence: Base confidence from wave/multi-TF analysis
        ict_confluence_score: ICT structure score [0, 1]
        
    Returns:
        Blended confidence score [0, 1]
    """
    # Multiplicative blend: ICT can boost up to 50%
    blended = wave_confidence * (0.5 + 0.5 * ict_confluence_score)
    
    # Ensure bounded [0, 1]
    return max(0.0, min(1.0, blended))
