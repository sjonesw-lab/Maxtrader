"""
Multi-timeframe confluence analysis for successful backtest replication.

Implements:
- Daily trend via tanh-scaled slope
- 4H VWAP position proxy
- Volume Profile / POC proxy
- Confidence scoring [0, 1]
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional


@dataclass
class ConfluenceSignal:
    """Multi-timeframe confluence result."""
    daily_direction: str  # 'up' or 'down'
    daily_slope: float  # Raw slope
    slope_confidence: float  # tanh-scaled
    vwap_position: str  # 'above', 'below', 'at'
    vp_position: str  # 'above_value', 'below_value', 'at_value'
    total_confidence: float  # [0, 1]


def calculate_daily_trend(
    df_daily: pd.DataFrame,
    current_time: pd.Timestamp,
    lookback: int = 5
) -> Tuple[str, float, float]:
    """
    Calculate daily trend direction and confidence.
    
    Uses slope over last N bars with tanh scaling for confidence.
    
    Args:
        df_daily: Daily OHLCV data
        current_time: Current timestamp
        lookback: Bars to calculate slope (default: 5)
        
    Returns:
        (direction, raw_slope, confidence)
    """
    # Get bars up to current time
    mask = df_daily['timestamp'] <= current_time
    if mask.sum() < lookback:
        return 'unknown', 0.0, 0.4  # Baseline confidence
    
    recent = df_daily[mask].tail(lookback)
    
    if len(recent) < 2:
        return 'unknown', 0.0, 0.4
    
    # Calculate slope: (close[-1] - close[-5]) / close[-5]
    price_start = recent['close'].iloc[0]
    price_end = recent['close'].iloc[-1]
    
    slope = (price_end - price_start) / price_start if price_start > 0 else 0.0
    
    # Direction
    direction = 'up' if slope > 0 else 'down'
    
    # Confidence via tanh scaling (normalize large slopes)
    # tanh(abs(slope) / 0.02) scales slope to [0, 1]
    slope_scaled = np.tanh(abs(slope) / 0.02)
    
    # Confidence: 0.4 baseline + 0.4 * slope_scaled
    # This keeps headroom for other factors
    confidence = 0.4 + 0.4 * slope_scaled
    confidence = np.clip(confidence, 0.0, 1.0)
    
    return direction, slope, confidence


def calculate_vwap_position(
    df_4h: pd.DataFrame,
    current_time: pd.Timestamp,
    fallback_daily: Optional[pd.DataFrame] = None
) -> str:
    """
    Calculate VWAP position proxy using typical price.
    
    4H logic: position of last close vs average TP = (H+L+C)/3
    Fallback to daily if 4H not available.
    
    Args:
        df_4h: 4H OHLCV data
        current_time: Current timestamp
        fallback_daily: Daily data for fallback
        
    Returns:
        'above', 'below', or 'at'
    """
    # Try 4H first
    mask_4h = df_4h['timestamp'] <= current_time
    
    if mask_4h.sum() >= 3:
        recent_4h = df_4h[mask_4h].tail(10)
        
        # Calculate typical price
        tp = (recent_4h['high'] + recent_4h['low'] + recent_4h['close']) / 3
        avg_tp = tp.mean()
        
        last_close = recent_4h['close'].iloc[-1]
        
        if last_close > avg_tp * 1.001:  # 0.1% threshold
            return 'above'
        elif last_close < avg_tp * 0.999:
            return 'below'
        else:
            return 'at'
    
    # Fallback to daily
    if fallback_daily is not None:
        mask_daily = fallback_daily['timestamp'] <= current_time
        if mask_daily.sum() >= 3:
            recent_daily = fallback_daily[mask_daily].tail(5)
            tp = (recent_daily['high'] + recent_daily['low'] + recent_daily['close']) / 3
            avg_tp = tp.mean()
            last_close = recent_daily['close'].iloc[-1]
            
            if last_close > avg_tp * 1.001:
                return 'above'
            elif last_close < avg_tp * 0.999:
                return 'below'
    
    return 'at'


def calculate_vp_position(
    df_daily: pd.DataFrame,
    current_time: pd.Timestamp,
    lookback: int = 20
) -> str:
    """
    Calculate Volume Profile / POC position proxy.
    
    Uses mode of rounded closes as POC proxy.
    
    Args:
        df_daily: Daily OHLCV data
        current_time: Current timestamp
        lookback: Bars for VP calculation (default: 20)
        
    Returns:
        'above_value', 'below_value', or 'at_value'
    """
    mask = df_daily['timestamp'] <= current_time
    if mask.sum() < lookback:
        return 'at_value'
    
    recent = df_daily[mask].tail(lookback)
    
    # Round closes to 0.1 and find mode (POC proxy)
    rounded_closes = (recent['close'] / 0.1).round() * 0.1
    
    try:
        poc = rounded_closes.mode().iloc[0]
    except:
        poc = rounded_closes.median()
    
    last_close = recent['close'].iloc[-1]
    
    if last_close > poc * 1.002:  # 0.2% threshold
        return 'above_value'
    elif last_close < poc * 0.998:
        return 'below_value'
    else:
        return 'at_value'


def calculate_confluence(
    df_1min: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_daily: pd.DataFrame,
    current_time: pd.Timestamp,
    min_confidence: float = 0.40
) -> ConfluenceSignal:
    """
    Calculate complete multi-timeframe confluence.
    
    Args:
        df_1min: 1-minute data (for reference)
        df_4h: 4H data
        df_daily: Daily data
        current_time: Current timestamp
        min_confidence: Minimum confidence gate (default: 0.40)
        
    Returns:
        ConfluenceSignal with all metrics
    """
    # Daily trend
    direction, slope, slope_conf = calculate_daily_trend(df_daily, current_time)
    
    # VWAP position
    vwap_pos = calculate_vwap_position(df_4h, current_time, df_daily)
    
    # VP/POC position
    vp_pos = calculate_vp_position(df_daily, current_time)
    
    # Total confidence starts with slope confidence
    total_conf = slope_conf
    
    # Boost confidence if VWAP/VP align with trend
    if direction == 'up':
        if vwap_pos == 'above':
            total_conf += 0.05
        if vp_pos == 'above_value':
            total_conf += 0.05
    elif direction == 'down':
        if vwap_pos == 'below':
            total_conf += 0.05
        if vp_pos == 'below_value':
            total_conf += 0.05
    
    # Cap at 1.0
    total_conf = np.clip(total_conf, 0.0, 1.0)
    
    return ConfluenceSignal(
        daily_direction=direction,
        daily_slope=slope,
        slope_confidence=slope_conf,
        vwap_position=vwap_pos,
        vp_position=vp_pos,
        total_confidence=total_conf
    )


def check_confluence_alignment(
    confluence: ConfluenceSignal,
    signal_direction: str,
    min_confidence: float = 0.40
) -> Tuple[bool, float]:
    """
    Check if signal direction aligns with confluence.
    
    Args:
        confluence: ConfluenceSignal object
        signal_direction: 'long' or 'short'
        min_confidence: Minimum required confidence
        
    Returns:
        (is_aligned, confidence)
    """
    # Check direction alignment
    if signal_direction == 'long' and confluence.daily_direction != 'up':
        return False, confluence.total_confidence
    elif signal_direction == 'short' and confluence.daily_direction != 'down':
        return False, confluence.total_confidence
    
    # Check minimum confidence
    if confluence.total_confidence < min_confidence:
        return False, confluence.total_confidence
    
    return True, confluence.total_confidence
