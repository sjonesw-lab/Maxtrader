"""
Wave-based Renko strategy with multi-timeframe confluence.

Implements successful backtest logic:
- Wave detection: 3+ brick impulse
- Retracement filters: shallow/healthy only
- Multi-timeframe confluence: daily + 4H
- Proper wave-based targets
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import numpy as np

from engine.wave_analysis import find_valid_wave_entry, Wave, Retracement
from engine.confluence import calculate_confluence, check_confluence_alignment, ConfluenceSignal


@dataclass
class WaveSignal:
    """Trading signal from wave analysis."""
    brick_index: int
    timestamp: pd.Timestamp
    direction: str  # 'long' or 'short'
    spot: float
    tp1: float  # First target
    tp2: float  # Extension target
    wave_height: float
    retrace_type: str
    retrace_pct: float
    confluence: ConfluenceSignal
    regime: str
    meta: dict = None


def generate_wave_signals(
    df_1min: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_daily: pd.DataFrame,
    renko_df: pd.DataFrame,
    regime_series: pd.Series,
    brick_size: float,
    min_bricks: int = 3,
    max_entry_distance: float = 1.5,
    min_confidence: float = 0.40,
    session_start: tuple = (9, 45),
    session_end: tuple = (15, 45)
) -> List[WaveSignal]:
    """
    Generate trading signals using wave analysis with proper retracement detection.
    
    State-machine approach:
    1. Detect completed wave impulses (3+ consecutive bricks)
    2. Cache completed waves
    3. Monitor subsequent bricks for retracements
    4. Signal when price retraces into shallow (0-33%) or healthy (33-62%) zones
    5. Skip if retracement goes deep (>62%)
    
    Quality filters:
    - Wave impulse: min 3 bricks
    - Retracement: shallow or healthy only
    - Entry distance: within 1.5 bricks of P2
    - Confluence: daily + 4H alignment
    - Minimum confidence gate
    - Regime alignment
    
    Args:
        df_1min: 1-minute OHLCV data
        df_4h: 4H OHLCV data
        df_daily: Daily OHLCV data
        renko_df: Renko brick DataFrame
        regime_series: Regime labels (from 30-min Renko)
        brick_size: Renko brick size
        min_bricks: Minimum bricks for wave (default: 3)
        max_entry_distance: Max bricks from P2 (default: 1.5)
        min_confidence: Minimum confluence confidence (default: 0.40)
        session_start: (hour, minute) for session start (default: 9:45 AM)
        session_end: (hour, minute) for session end (default: 3:45 PM)
        
    Returns:
        List of WaveSignal objects
    """
    signals = []
    active_wave = None  # Track the current wave waiting for retracement
    
    for idx in range(min_bricks, len(renko_df)):
        brick = renko_df.iloc[idx]
        timestamp = brick['timestamp']
        
        # SESSION FILTER: Only trade during core hours
        hour = timestamp.hour
        minute = timestamp.minute
        time_in_minutes = hour * 60 + minute
        start_time = session_start[0] * 60 + session_start[1]
        end_time = session_end[0] * 60 + session_end[1]
        
        if not (start_time <= time_in_minutes <= end_time):
            continue
        
        current_price = brick['brick_close']
        current_direction = brick['direction']
        
        # STATE 1: Check if we just completed a new wave impulse
        from engine.wave_analysis import detect_wave
        potential_wave = detect_wave(renko_df, idx, min_bricks)
        
        # If new wave detected and different from active_wave, cache it
        if potential_wave is not None:
            # Check if this is a NEW completed wave (not already tracked)
            if active_wave is None or potential_wave.end_idx > active_wave.end_idx:
                active_wave = potential_wave
                # Don't signal yet - wait for retracement
                continue
        
        # STATE 2: If we have an active wave, check for retracement
        if active_wave is None:
            continue
        
        # Check if current brick is moving opposite to wave (retracement)
        is_retracing = (active_wave.direction == 1 and current_direction == -1) or \
                       (active_wave.direction == -1 and current_direction == 1)
        
        # Also check if price has moved away from P2 (continuation, not retracement)
        if active_wave.direction == 1:  # Up wave
            if current_price > active_wave.p2_price:
                # Price continued higher - invalidate wave, look for new one
                active_wave = None
                continue
        else:  # Down wave
            if current_price < active_wave.p2_price:
                # Price continued lower - invalidate wave, look for new one
                active_wave = None
                continue
        
        # Analyze current retracement
        from engine.wave_analysis import analyze_retracement, calculate_wave_targets
        retrace = analyze_retracement(active_wave, current_price, brick_size, max_entry_distance)
        
        # Skip if retracement is too deep (>62%) - invalidate wave
        if retrace.retrace_type == 'deep':
            active_wave = None
            continue
        
        # Skip if not a valid entry (too far from P2)
        if not retrace.entry_valid:
            continue
        
        # Only signal on shallow or healthy retracements
        if retrace.retrace_type not in ['shallow', 'healthy']:
            continue
        
        # Calculate wave targets
        tp1, tp2 = calculate_wave_targets(active_wave, retrace)
        
        # CONFLUENCE: Calculate multi-timeframe alignment
        confluence = calculate_confluence(
            df_1min, df_4h, df_daily, timestamp, min_confidence
        )
        
        # Determine signal direction from wave
        signal_direction = 'long' if active_wave.direction == 1 else 'short'
        
        # Check confluence alignment
        is_aligned, conf_score = check_confluence_alignment(
            confluence, signal_direction, min_confidence
        )
        
        if not is_aligned:
            continue
        
        # REGIME FILTER: Get regime at this timestamp
        regime_mask = df_1min['timestamp'] <= timestamp
        if not regime_mask.any():
            continue
        
        regime_row = df_1min[regime_mask].iloc[-1]
        regime = regime_row.get('regime', 'unknown')
        
        # Regime alignment (allow sideways for both directions)
        if signal_direction == 'long' and regime not in ['bull_trend', 'sideways']:
            continue
        elif signal_direction == 'short' and regime not in ['bear_trend', 'sideways']:
            continue
        
        # CREATE SIGNAL
        signal = WaveSignal(
            brick_index=idx,
            timestamp=timestamp,
            direction=signal_direction,
            spot=brick['brick_close'],
            tp1=tp1,
            tp2=tp2,
            wave_height=active_wave.wave_height,
            retrace_type=retrace.retrace_type,
            retrace_pct=retrace.retrace_pct,
            confluence=confluence,
            regime=regime,
            meta={
                'wave_bricks': active_wave.brick_count,
                'p1_price': active_wave.p1_price,
                'p2_price': active_wave.p2_price,
                'confidence': conf_score,
                'daily_direction': confluence.daily_direction,
                'vwap_position': confluence.vwap_position,
                'vp_position': confluence.vp_position
            }
        )
        
        signals.append(signal)
        
        # Clear active wave after signaling (one signal per wave)
        active_wave = None
    
    return signals
