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
    Generate trading signals using wave analysis and confluence.
    
    Quality filters (not time-based):
    1. Wave impulse: min 3 bricks
    2. Retracement: shallow or healthy only
    3. Entry distance: within 1.5 bricks of P2
    4. Confluence: daily + 4H alignment
    5. Minimum confidence gate
    6. Regime alignment
    
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
        
        # WAVE ANALYSIS: Find valid wave entry setup
        wave_entry = find_valid_wave_entry(
            renko_df, idx, brick_size, min_bricks, max_entry_distance
        )
        
        if wave_entry is None:
            continue
        
        wave, retrace, tp1, tp2 = wave_entry
        
        # Skip deep retracements (already filtered in wave_analysis)
        if retrace.retrace_type == 'deep':
            continue
        
        # CONFLUENCE: Calculate multi-timeframe alignment
        confluence = calculate_confluence(
            df_1min, df_4h, df_daily, timestamp, min_confidence
        )
        
        # Determine signal direction from wave
        signal_direction = 'long' if wave.direction == 1 else 'short'
        
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
            wave_height=wave.wave_height,
            retrace_type=retrace.retrace_type,
            retrace_pct=retrace.retrace_pct,
            confluence=confluence,
            regime=regime,
            meta={
                'wave_bricks': wave.brick_count,
                'p1_price': wave.p1_price,
                'p2_price': wave.p2_price,
                'confidence': conf_score,
                'daily_direction': confluence.daily_direction,
                'vwap_position': confluence.vwap_position,
                'vp_position': confluence.vp_position
            }
        )
        
        signals.append(signal)
    
    return signals
