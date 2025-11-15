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
from engine.ict_confluence import (
    calculate_ict_confluence, 
    calculate_ict_targets,
    combine_wave_and_ict_targets,
    ICTConfluence
)


@dataclass
class WaveSignal:
    """Trading signal from wave analysis."""
    brick_index: int
    timestamp: pd.Timestamp
    direction: str  # 'long' or 'short'
    spot: float
    tp1: float  # First target
    tp2: float  # Extension target
    stop: float  # Stop loss (for fixed % mode)
    wave_height: float
    retrace_type: str
    retrace_pct: float
    confluence: ConfluenceSignal
    regime: str
    ict_confluence: Optional[ICTConfluence] = None
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
    session_end: tuple = (15, 45),
    use_ict_boost: bool = True,
    target_mode: str = 'wave',
    require_sweep: bool = False,
    use_volume_filter: bool = False,
    avoid_lunch_chop: bool = False,
    use_dynamic_targets: bool = False
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
        use_ict_boost: Enable ICT confluence boost (default: True)
        target_mode: 'wave' for wave-based targets or 'fixed_pct' for % targets (default: 'wave')
        require_sweep: Only trade when liquidity sweep present (default: False)
        use_volume_filter: Require above-average volume on wave (default: False)
        avoid_lunch_chop: Skip 12:00-13:30 ET lunch period (default: False)
        use_dynamic_targets: Scale targets to ATR-based realistic moves (default: False)
        
    Returns:
        List of WaveSignal objects
    """
    signals = []
    active_wave = None  # Track the current wave waiting for retracement
    
    # Calculate volume moving average if using volume filter
    volume_ma = None
    if use_volume_filter and 'volume' in df_1min.columns:
        volume_ma = df_1min['volume'].rolling(window=20).mean()
    
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
        
        # TIME-OF-DAY FILTER: Avoid lunch chop (12:00-13:30 ET)
        if avoid_lunch_chop:
            lunch_start = 12 * 60  # 12:00
            lunch_end = 13 * 60 + 30  # 13:30
            if lunch_start <= time_in_minutes <= lunch_end:
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
        wave_tp1, wave_tp2 = calculate_wave_targets(active_wave, retrace)
        
        # CONFLUENCE: Calculate multi-timeframe alignment
        confluence = calculate_confluence(
            df_1min, df_4h, df_daily, timestamp, min_confidence
        )
        
        # Determine signal direction from wave
        signal_direction = 'long' if active_wave.direction == 1 else 'short'
        
        # Check confluence alignment
        is_aligned, wave_conf_score = check_confluence_alignment(
            confluence, signal_direction, min_confidence
        )
        
        if not is_aligned:
            continue
        
        # TARGET CALCULATION: Dynamic ATR-based, fixed %, or wave-based
        if use_dynamic_targets:
            # Dynamic targets based on realistic 2-hour QQQ moves (0.3-0.5%)
            # TP1: 0.35%, TP2: 0.5%, Stop: 0.25%
            if signal_direction == 'long':
                tp1 = current_price * 1.0035  # +0.35%
                tp2 = current_price * 1.005   # +0.5%
                stop = current_price * 0.9975  # -0.25%
            else:  # short
                tp1 = current_price * 0.9965  # -0.35%
                tp2 = current_price * 0.995   # -0.5%
                stop = current_price * 1.0025  # +0.25%
        elif target_mode == 'fixed_pct':
            # Fixed % targets (v3 proven approach)
            # TP1: +1%, TP2: +2%, Stop: -0.7%
            if signal_direction == 'long':
                tp1 = current_price * 1.01  # +1%
                tp2 = current_price * 1.02  # +2%
                stop = current_price * 0.993  # -0.7%
            else:  # short
                tp1 = current_price * 0.99  # -1%
                tp2 = current_price * 0.98  # -2%
                stop = current_price * 1.007  # +0.7%
        else:
            # Wave-based targets (v4 approach)
            tp1, tp2 = wave_tp1, wave_tp2
            # No stop for wave-based (options premium defines max loss)
            stop = 0.0
        
        # ICT BOOST: Calculate ICT confluence and compare targets
        ict_conf = None
        final_conf_score = wave_conf_score
        
        if use_ict_boost:
            # Calculate ICT structure confluence
            from engine.ict_confluence import blend_confidence_scores
            ict_conf = calculate_ict_confluence(
                df_1min, timestamp, signal_direction, lookback_bars=10
            )
            
            # Blend confidence scores multiplicatively
            final_conf_score = blend_confidence_scores(wave_conf_score, ict_conf.confluence_score)
            
            # Re-check minimum confidence after ICT boost
            if final_conf_score < min_confidence:
                continue
            
            # Only use ICT targets if in wave mode
            if target_mode == 'wave':
                # Calculate ICT-based targets
                ict_tp1, ict_tp2 = calculate_ict_targets(
                    df_1min, timestamp, signal_direction, current_price, lookback_bars=20
                )
                
                # Combine wave and ICT targets (closer TP1, farther TP2)
                tp1, tp2 = combine_wave_and_ict_targets(
                    wave_tp1, wave_tp2, ict_tp1, ict_tp2, current_price, signal_direction
                )
        
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
        
        # LIQUIDITY SWEEP FILTER: Only trade if sweep present (rare, high quality)
        if require_sweep:
            has_sweep = regime_row.get('sweep', False)
            if not has_sweep:
                continue
        
        # VOLUME FILTER: Require above-average volume on wave impulse
        if use_volume_filter and volume_ma is not None:
            # Check volume at wave formation (around P1-P2 range)
            wave_start_mask = df_1min['timestamp'] <= timestamp
            if wave_start_mask.any():
                wave_idx = wave_start_mask.sum() - 1
                if wave_idx >= 0 and wave_idx < len(volume_ma):
                    current_vol = df_1min['volume'].iloc[wave_idx]
                    avg_vol = volume_ma.iloc[wave_idx]
                    # Require volume at least 1.2x average
                    if pd.notna(avg_vol) and current_vol < avg_vol * 1.2:
                        continue
        
        # CREATE SIGNAL
        signal = WaveSignal(
            brick_index=idx,
            timestamp=timestamp,
            direction=signal_direction,
            spot=brick['brick_close'],
            tp1=tp1,
            tp2=tp2,
            stop=stop,
            wave_height=active_wave.wave_height,
            retrace_type=retrace.retrace_type,
            retrace_pct=retrace.retrace_pct,
            confluence=confluence,
            regime=regime,
            ict_confluence=ict_conf,
            meta={
                'wave_bricks': active_wave.brick_count,
                'p1_price': active_wave.p1_price,
                'p2_price': active_wave.p2_price,
                'confidence': final_conf_score,
                'wave_confidence': wave_conf_score,
                'ict_confluence_score': ict_conf.confluence_score if ict_conf else 0.0,
                'daily_direction': confluence.daily_direction,
                'vwap_position': confluence.vwap_position,
                'vp_position': confluence.vp_position,
                'wave_tp1': wave_tp1,
                'wave_tp2': wave_tp2,
                'target_mode': target_mode
            }
        )
        
        signals.append(signal)
        
        # Clear active wave after signaling (one signal per wave)
        active_wave = None
    
    return signals
