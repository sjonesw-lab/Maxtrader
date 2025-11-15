"""
Shared base classes and utilities for all trading strategies.

Provides:
- BaseStrategy interface
- Unified Signal format
- Shared preprocessing (Renko, sessions, ICT)
- Common risk/target helpers
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np

from engine.renko import build_renko, get_renko_direction_series
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import (
    detect_liquidity_sweeps,
    detect_displacement,
    detect_fvgs,
    detect_mss,
    detect_order_blocks
)
from engine.regimes import detect_regime
from engine.timeframes import resample_to_timeframe


@dataclass
class StrategySignal:
    """
    Unified signal format for all strategies.
    
    Extends basic Signal with strategy-specific metadata.
    """
    timestamp: pd.Timestamp
    index: int
    direction: str  # 'long' or 'short'
    spot: float
    tp1: float  # First target
    tp2: float  # Second target (optional)
    stop: float  # Stop loss
    
    # Strategy metadata
    strategy: str  # 'normal_vol', 'high_vol', 'ultra_low_vol'
    confidence: float  # 0.0-1.0
    regime: str  # Current market regime
    setup_type: str  # e.g., 'wave_retrace', 'sweep_reclaim', 'vwap_fade'
    
    # Risk metrics
    risk_amount: float  # Dollar risk on trade
    reward_risk_ratio: float  # R:R at TP1
    
    # Additional context
    meta: Dict[str, Any] = None


@dataclass
class MarketContext:
    """
    Shared market context passed to all strategies.
    
    Contains preprocessed data available to all strategy logic.
    """
    df_1min: pd.DataFrame  # 1-minute bars with indicators
    df_4h: pd.DataFrame  # 4H bars
    df_daily: pd.DataFrame  # Daily bars
    renko_df: pd.DataFrame  # Renko bricks
    regime: str  # Current regime
    vix: float  # VIX value (if available)
    atr_pct: float  # ATR as % of price
    
    # Session levels
    session_highs: Dict[str, float] = None
    session_lows: Dict[str, float] = None
    
    # Current bar info
    current_bar: pd.Series = None
    current_price: float = 0.0
    current_time: pd.Timestamp = None


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    Each strategy implements generate_signals() method with specific logic.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize strategy with configuration.
        
        Args:
            config: Strategy-specific parameters (optional)
        """
        self.config = config or {}
        self.name = self.__class__.__name__
        
    @abstractmethod
    def generate_signals(self, context: MarketContext) -> List[StrategySignal]:
        """
        Generate trading signals based on market context.
        
        Args:
            context: Preprocessed market data and indicators
            
        Returns:
            List of StrategySignal objects
        """
        pass
    
    def calculate_targets(
        self,
        entry: float,
        direction: str,
        atr: float,
        mode: str = 'atr'
    ) -> tuple:
        """
        Calculate TP1, TP2, and stop based on entry and direction.
        
        Args:
            entry: Entry price
            direction: 'long' or 'short'
            atr: Current ATR
            mode: 'atr', 'fixed_pct', or 'range'
            
        Returns:
            (tp1, tp2, stop)
        """
        if mode == 'atr':
            if direction == 'long':
                tp1 = entry + (1.5 * atr)
                tp2 = entry + (2.5 * atr)
                stop = entry - (1.0 * atr)
            else:  # short
                tp1 = entry - (1.5 * atr)
                tp2 = entry - (2.5 * atr)
                stop = entry + (1.0 * atr)
                
        elif mode == 'fixed_pct':
            if direction == 'long':
                tp1 = entry * 1.01  # +1%
                tp2 = entry * 1.02  # +2%
                stop = entry * 0.993  # -0.7%
            else:  # short
                tp1 = entry * 0.99
                tp2 = entry * 0.98
                stop = entry * 1.007
                
        else:  # range-based (use ATR as fallback)
            return self.calculate_targets(entry, direction, atr, mode='atr')
            
        return tp1, tp2, stop
    
    def calculate_risk_reward(self, entry: float, tp1: float, stop: float) -> float:
        """
        Calculate risk-reward ratio.
        
        Args:
            entry: Entry price
            tp1: Target price
            stop: Stop loss price
            
        Returns:
            R:R ratio (reward/risk)
        """
        reward = abs(tp1 - entry)
        risk = abs(entry - stop)
        
        if risk == 0:
            return 0.0
            
        return reward / risk


def preprocess_market_data(
    df_1min: pd.DataFrame,
    vix: Optional[float] = None,
    renko_k: float = 4.0,
    regime_lookback: int = 20
) -> MarketContext:
    """
    Preprocess market data for all strategies.
    
    Builds all shared features:
    - Multi-timeframe data (4H, daily)
    - Renko bricks
    - Session labels and levels
    - ICT structures
    - Regime detection
    
    Args:
        df_1min: 1-minute OHLCV data
        vix: VIX value (optional)
        renko_k: ATR multiplier for Renko bricks
        regime_lookback: Lookback for regime detection
        
    Returns:
        MarketContext with all preprocessed data
    """
    # Multi-timeframe
    df_4h = resample_to_timeframe(df_1min, '4h')
    df_daily = resample_to_timeframe(df_1min, '1d')
    
    # Renko bricks
    renko_df = build_renko(df_1min, mode='atr', k=renko_k)
    
    # Session labels and levels
    df_1min = label_sessions(df_1min)
    df_1min = add_session_highs_lows(df_1min)
    
    # ICT structures
    df_1min = detect_liquidity_sweeps(df_1min)
    df_1min = detect_displacement(df_1min, atr_period=14, threshold=1.2)
    df_1min = detect_fvgs(df_1min)
    df_1min = detect_mss(df_1min)
    df_1min = detect_order_blocks(df_1min)
    
    # Regime detection
    renko_direction = get_renko_direction_series(df_1min, renko_df)
    df_30min = resample_to_timeframe(df_1min, '30min')
    renko_30min = build_renko(df_30min, mode="atr", k=1.0)
    renko_direction_30min = get_renko_direction_series(df_30min, renko_30min)
    regime_30min = detect_regime(df_30min, renko_direction_30min, lookback=regime_lookback)
    
    # Align regime to 1-min
    df_1min['regime'] = 'sideways'
    for idx in range(len(df_1min)):
        ts = df_1min['timestamp'].iloc[idx]
        mask = df_30min['timestamp'] <= ts
        if mask.any():
            regime_idx = mask.sum() - 1
            if regime_idx < len(regime_30min):
                df_1min.loc[df_1min.index[idx], 'regime'] = regime_30min.iloc[regime_idx]
    
    # Calculate ATR % of price
    if len(df_1min) > 14:
        latest_close = df_1min['close'].iloc[-1]
        atr = calculate_atr(df_1min, period=14)
        atr_pct = (atr / latest_close) * 100 if latest_close > 0 else 0.0
    else:
        atr_pct = 0.0
    
    # Extract session levels
    latest_bar = df_1min.iloc[-1]
    session_highs = {
        'asia': latest_bar.get('asia_high', 0),
        'london': latest_bar.get('london_high', 0),
        'ny': latest_bar.get('ny_high', 0)
    }
    session_lows = {
        'asia': latest_bar.get('asia_low', 0),
        'london': latest_bar.get('london_low', 0),
        'ny': latest_bar.get('ny_low', 0)
    }
    
    # Create context
    context = MarketContext(
        df_1min=df_1min,
        df_4h=df_4h,
        df_daily=df_daily,
        renko_df=renko_df,
        regime=df_1min['regime'].iloc[-1] if len(df_1min) > 0 else 'sideways',
        vix=vix or 15.0,  # Default VIX if not provided
        atr_pct=atr_pct,
        session_highs=session_highs,
        session_lows=session_lows,
        current_bar=latest_bar,
        current_price=latest_bar['close'],
        current_time=latest_bar['timestamp']
    )
    
    return context


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate Average True Range.
    
    Args:
        df: DataFrame with OHLC data
        period: ATR period (default: 14)
        
    Returns:
        ATR value
    """
    if len(df) < period:
        return 0.0
        
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    
    return atr if not pd.isna(atr) else 0.0


def calculate_vwap(df: pd.DataFrame, session_start: Optional[pd.Timestamp] = None) -> float:
    """
    Calculate VWAP (Volume Weighted Average Price).
    
    Args:
        df: DataFrame with OHLCV data
        session_start: Start of session (optional, uses all data if None)
        
    Returns:
        VWAP value
    """
    if session_start:
        df = df[df['timestamp'] >= session_start]
    
    if len(df) == 0:
        return 0.0
    
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical_price * df['volume']).sum() / df['volume'].sum()
    
    return vwap if not pd.isna(vwap) else 0.0


def find_swing_high(df: pd.DataFrame, lookback: int = 20) -> Optional[float]:
    """
    Find recent swing high.
    
    Args:
        df: DataFrame with price data
        lookback: Bars to search (default: 20)
        
    Returns:
        Swing high price or None
    """
    if len(df) < 3:
        return None
        
    recent = df.tail(min(lookback, len(df)))
    return recent['high'].max()


def find_swing_low(df: pd.DataFrame, lookback: int = 20) -> Optional[float]:
    """
    Find recent swing low.
    
    Args:
        df: DataFrame with price data
        lookback: Bars to search (default: 20)
        
    Returns:
        Swing low price or None
    """
    if len(df) < 3:
        return None
        
    recent = df.tail(min(lookback, len(df)))
    return recent['low'].min()
