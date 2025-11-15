"""
Ultra-Low Volatility Strategy (VIX <13 or ATR <0.5%).

Designed for dead calm markets with minimal range and grind price action.

Approach:
- VWAP mean-reversion: Fade extremes back to value
- Range trading: Buy low end, sell high end
- Grind-with-trend: Small pullbacks in established trend
- Targets are small (0.5-0.75 ATR) to match environment
- Risk: 1-1.5% per trade, max 3-4 positions

Setup Types:
1. VWAP Fade: Price pushes ±2 std dev from VWAP → fade back
2. Range Extreme: Price at range edge + small sweep → fade inside
3. Grind Pullback: Uptrend, dip to VWAP → rejoin trend
4. Box Breakout: Well-defined range, clean breakout with volume

Key Concepts:
- Define intraday range (first 60-90 minutes)
- Use VWAP as anchor/magnet
- Look for small liquidity grabs at edges
- Join slow trends on tiny retracements
"""

from typing import List, Optional
import pandas as pd
import numpy as np

from engine.strategy_shared import (
    BaseStrategy,
    StrategySignal,
    MarketContext,
    calculate_vwap
)


class UltraLowVolStrategy(BaseStrategy):
    """
    Strategy for ultra-low volatility markets (VIX <13).
    
    Trades VWAP mean-reversion and range boundaries.
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize Ultra-Low Vol strategy.
        
        Config options:
        - vwap_std_threshold: Std devs from VWAP to trigger fade (default: 2.0)
        - range_definition_bars: Bars to define initial range (default: 90)
        - risk_pct: Risk per trade as % (default: 1.25%)
        - target_atr_mult: ATR multiplier for targets (default: 0.6)
        - min_range_pct: Minimum range size as % (default: 0.3%)
        """
        super().__init__(config)
        
        cfg = config or {}
        self.vwap_std_threshold = cfg.get('vwap_std_threshold', 1.5)  # ARCHITECT FIX: Relaxed from 2.0
        self.range_definition_bars = cfg.get('range_definition_bars', 60)  # ARCHITECT FIX: Reduced from 90
        self.risk_pct = cfg.get('risk_pct', 0.0125)  # 1.25%
        self.target_atr_mult = cfg.get('target_atr_mult', 0.6)
        self.min_range_pct = cfg.get('min_range_pct', 0.002)  # ARCHITECT FIX: Relaxed from 0.3% to 0.2%
        
    def generate_signals(self, context: MarketContext) -> List[StrategySignal]:
        """
        Generate ultra-low vol signals based on mean-reversion and range.
        
        Logic:
        1. Define intraday range (first 90 minutes or session)
        2. Calculate VWAP and standard deviation
        3. Check for VWAP fade setups (price at ±2 std dev)
        4. Check for range extreme fades
        5. Check for grind-with-trend pullbacks
        6. Entry on confirmation (small reclaim or volume spike)
        7. Stop just beyond range boundary
        8. Target at VWAP or opposite range edge
        
        Args:
            context: Market data and indicators
            
        Returns:
            List of StrategySignal objects
        """
        signals = []
        df = context.df_1min
        
        if len(df) < 100:
            return signals
        
        # Define range and VWAP
        range_info = self._define_range(df)
        if not range_info:
            return signals
        
        vwap_info = self._calculate_vwap_bands(df, range_info['start_idx'])
        
        # Current bar
        current_bar = df.iloc[-1]
        current_price = current_bar['close']
        
        # Check VWAP fade setups
        vwap_signal = self._check_vwap_fade(
            df, current_bar, vwap_info, range_info, context
        )
        if vwap_signal:
            signals.append(vwap_signal)
        
        # Check range extreme fades
        range_signal = self._check_range_fade(
            df, current_bar, range_info, vwap_info, context
        )
        if range_signal:
            signals.append(range_signal)
        
        # Check grind-with-trend setups
        trend_signal = self._check_grind_pullback(
            df, current_bar, vwap_info, context
        )
        if trend_signal:
            signals.append(trend_signal)
        
        return signals
    
    def _define_range(self, df: pd.DataFrame) -> Optional[dict]:
        """
        Define intraday trading range.
        
        ARCHITECT FIX: Use adaptive range - either first N bars or all available if less.
        
        Returns:
            Dictionary with range_high, range_low, range_mid, start_idx
        """
        # ARCHITECT FIX: Handle partial days - use what's available
        n_bars = min(self.range_definition_bars, len(df))
        
        if n_bars < 30:  # Need at least 30 bars
            return None
        
        # Define range from first N bars
        range_bars = df.head(n_bars)
        
        range_high = range_bars['high'].max()
        range_low = range_bars['low'].min()
        range_mid = (range_high + range_low) / 2
        range_size = range_high - range_low
        
        # ARCHITECT FIX: Relaxed range check (was 0.3%, now 0.2%)
        if range_size / range_mid < self.min_range_pct:
            return None
        
        return {
            'high': range_high,
            'low': range_low,
            'mid': range_mid,
            'size': range_size,
            'start_idx': n_bars
        }
    
    def _calculate_vwap_bands(self, df: pd.DataFrame, start_idx: int) -> dict:
        """
        Calculate VWAP and standard deviation bands.
        
        ARCHITECT FIX: Use rolling window to avoid tiny sigma on early bars.
        
        Args:
            df: 1-minute data
            start_idx: Starting index for VWAP calculation
            
        Returns:
            Dictionary with vwap, upper_band, lower_band, std
        """
        # ARCHITECT FIX: Use larger rolling window (last 100 bars) instead of from start_idx
        session_df = df.tail(min(100, len(df)))
        
        if len(session_df) == 0:
            return {'vwap': 0, 'upper_band': 0, 'lower_band': 0, 'std': 0}
        
        # Calculate VWAP
        typical_price = (session_df['high'] + session_df['low'] + session_df['close']) / 3
        
        if session_df['volume'].sum() == 0:
            vwap = typical_price.mean()
        else:
            vwap = (typical_price * session_df['volume']).sum() / session_df['volume'].sum()
        
        # Calculate std deviation of price from VWAP
        price_dev = typical_price - vwap
        std = price_dev.std()
        
        # ARCHITECT FIX: Bands at ±1.5 std dev (was 2.0)
        upper_band = vwap + (self.vwap_std_threshold * std)
        lower_band = vwap - (self.vwap_std_threshold * std)
        
        return {
            'vwap': vwap,
            'upper_band': upper_band,
            'lower_band': lower_band,
            'std': std
        }
    
    def _check_vwap_fade(
        self,
        df: pd.DataFrame,
        current_bar: pd.Series,
        vwap_info: dict,
        range_info: dict,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        Check for VWAP fade setup.
        
        Long setup: Price below lower band → small sweep → close back inside
        Short setup: Price above upper band → small sweep → close back inside
        
        Args:
            df: 1-minute data
            current_bar: Current bar
            vwap_info: VWAP and bands
            range_info: Range info
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        vwap = vwap_info['vwap']
        upper_band = vwap_info['upper_band']
        lower_band = vwap_info['lower_band']
        
        price = current_bar['close']
        
        # Long setup: Below lower band, fade back to VWAP
        if price < lower_band:
            # Check if we've seen a small sweep and reclaim
            if current_bar['low'] < lower_band and current_bar['close'] > lower_band:
                # Fading back inside
                entry = price
                stop = current_bar['low'] - (0.0005 * entry)  # Just below sweep
                tp1 = vwap  # Target VWAP
                tp2 = upper_band  # Optimistic: opposite band
                
                # Calculate R:R
                rr = self.calculate_risk_reward(entry, tp1, stop)
                
                # Need at least 1:1 R:R
                if rr < 1.0:
                    return None
                
                return StrategySignal(
                    timestamp=current_bar['timestamp'],
                    index=len(df) - 1,
                    direction='long',
                    spot=entry,
                    tp1=tp1,
                    tp2=tp2,
                    stop=stop,
                    strategy='ultra_low_vol',
                    confidence=0.65,
                    regime=context.regime,
                    setup_type='vwap_fade_long',
                    risk_amount=entry * self.risk_pct,
                    reward_risk_ratio=rr,
                    meta={
                        'vwap': vwap,
                        'lower_band': lower_band,
                        'deviation': (lower_band - price) / vwap
                    }
                )
        
        # Short setup: Above upper band, fade back to VWAP
        elif price > upper_band:
            if current_bar['high'] > upper_band and current_bar['close'] < upper_band:
                # Fading back inside
                entry = price
                stop = current_bar['high'] + (0.0005 * entry)
                tp1 = vwap
                tp2 = lower_band
                
                rr = self.calculate_risk_reward(entry, tp1, stop)
                
                if rr < 1.0:
                    return None
                
                return StrategySignal(
                    timestamp=current_bar['timestamp'],
                    index=len(df) - 1,
                    direction='short',
                    spot=entry,
                    tp1=tp1,
                    tp2=tp2,
                    stop=stop,
                    strategy='ultra_low_vol',
                    confidence=0.65,
                    regime=context.regime,
                    setup_type='vwap_fade_short',
                    risk_amount=entry * self.risk_pct,
                    reward_risk_ratio=rr,
                    meta={
                        'vwap': vwap,
                        'upper_band': upper_band,
                        'deviation': (price - upper_band) / vwap
                    }
                )
        
        return None
    
    def _check_range_fade(
        self,
        df: pd.DataFrame,
        current_bar: pd.Series,
        range_info: dict,
        vwap_info: dict,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        Check for range extreme fade setup.
        
        Long: Price at range low → small sweep → fade to mid/high
        Short: Price at range high → small sweep → fade to mid/low
        
        Args:
            df: 1-minute data
            current_bar: Current bar
            range_info: Range boundaries
            vwap_info: VWAP info
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        range_high = range_info['high']
        range_low = range_info['low']
        range_mid = range_info['mid']
        
        price = current_bar['close']
        vwap = vwap_info['vwap']
        
        # Define "extreme" as within 10% of range
        range_size = range_high - range_low
        extreme_threshold = range_size * 0.1
        
        # Long setup: Near range low
        if abs(price - range_low) < extreme_threshold:
            # Check for small sweep of range low
            if current_bar['low'] < range_low and current_bar['close'] > range_low:
                entry = price
                stop = current_bar['low'] - (0.0005 * entry)
                
                # Target VWAP or range mid, whichever is closer
                tp1 = min(vwap, range_mid) if vwap > entry else range_mid
                tp2 = max(vwap, range_high * 0.95)  # Near range high
                
                rr = self.calculate_risk_reward(entry, tp1, stop)
                
                if rr < 1.0:
                    return None
                
                return StrategySignal(
                    timestamp=current_bar['timestamp'],
                    index=len(df) - 1,
                    direction='long',
                    spot=entry,
                    tp1=tp1,
                    tp2=tp2,
                    stop=stop,
                    strategy='ultra_low_vol',
                    confidence=0.60,
                    regime=context.regime,
                    setup_type='range_fade_long',
                    risk_amount=entry * self.risk_pct,
                    reward_risk_ratio=rr,
                    meta={
                        'range_low': range_low,
                        'range_high': range_high,
                        'vwap': vwap
                    }
                )
        
        # Short setup: Near range high
        elif abs(price - range_high) < extreme_threshold:
            if current_bar['high'] > range_high and current_bar['close'] < range_high:
                entry = price
                stop = current_bar['high'] + (0.0005 * entry)
                
                tp1 = max(vwap, range_mid) if vwap < entry else range_mid
                tp2 = min(vwap, range_low * 1.05)
                
                rr = self.calculate_risk_reward(entry, tp1, stop)
                
                if rr < 1.0:
                    return None
                
                return StrategySignal(
                    timestamp=current_bar['timestamp'],
                    index=len(df) - 1,
                    direction='short',
                    spot=entry,
                    tp1=tp1,
                    tp2=tp2,
                    stop=stop,
                    strategy='ultra_low_vol',
                    confidence=0.60,
                    regime=context.regime,
                    setup_type='range_fade_short',
                    risk_amount=entry * self.risk_pct,
                    reward_risk_ratio=rr,
                    meta={
                        'range_low': range_low,
                        'range_high': range_high,
                        'vwap': vwap
                    }
                )
        
        return None
    
    def _check_grind_pullback(
        self,
        df: pd.DataFrame,
        current_bar: pd.Series,
        vwap_info: dict,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        Check for grind-with-trend pullback setup.
        
        In slow grinding trend, look for small pullbacks to VWAP to rejoin.
        
        Long: Daily uptrend + price dips to VWAP → rejoin up
        Short: Daily downtrend + price pops to VWAP → rejoin down
        
        Args:
            df: 1-minute data
            current_bar: Current bar
            vwap_info: VWAP info
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        # Check daily trend
        df_daily = context.df_daily
        if len(df_daily) < 5:
            return None
        
        # Simple trend: 5-day close direction
        daily_slope = (df_daily['close'].iloc[-1] - df_daily['close'].iloc[-5]) / df_daily['close'].iloc[-5]
        
        vwap = vwap_info['vwap']
        price = current_bar['close']
        
        # Long setup: Uptrend + dip to VWAP
        if daily_slope > 0.005:  # 0.5% uptrend over 5 days
            # Price should be near or just touched VWAP from above
            if abs(price - vwap) / vwap < 0.002:  # Within 0.2% of VWAP
                # Check if we dipped below and reclaimed
                if current_bar['low'] < vwap and current_bar['close'] > vwap:
                    entry = price
                    stop = vwap * 0.997  # 0.3% below VWAP
                    
                    # Small targets in grind
                    atr = context.atr_pct * entry / 100
                    tp1 = entry + (0.5 * atr)  # 0.5 ATR
                    tp2 = entry + (0.75 * atr)  # 0.75 ATR
                    
                    rr = self.calculate_risk_reward(entry, tp1, stop)
                    
                    if rr < 0.8:  # Accept lower R:R in grind
                        return None
                    
                    return StrategySignal(
                        timestamp=current_bar['timestamp'],
                        index=len(df) - 1,
                        direction='long',
                        spot=entry,
                        tp1=tp1,
                        tp2=tp2,
                        stop=stop,
                        strategy='ultra_low_vol',
                        confidence=0.55,
                        regime=context.regime,
                        setup_type='grind_pullback_long',
                        risk_amount=entry * self.risk_pct,
                        reward_risk_ratio=rr,
                        meta={
                            'vwap': vwap,
                            'daily_slope': daily_slope,
                            'trend': 'up'
                        }
                    )
        
        # Short setup: Downtrend + pop to VWAP
        elif daily_slope < -0.005:
            if abs(price - vwap) / vwap < 0.002:
                if current_bar['high'] > vwap and current_bar['close'] < vwap:
                    entry = price
                    stop = vwap * 1.003
                    
                    atr = context.atr_pct * entry / 100
                    tp1 = entry - (0.5 * atr)
                    tp2 = entry - (0.75 * atr)
                    
                    rr = self.calculate_risk_reward(entry, tp1, stop)
                    
                    if rr < 0.8:
                        return None
                    
                    return StrategySignal(
                        timestamp=current_bar['timestamp'],
                        index=len(df) - 1,
                        direction='short',
                        spot=entry,
                        tp1=tp1,
                        tp2=tp2,
                        stop=stop,
                        strategy='ultra_low_vol',
                        confidence=0.55,
                        regime=context.regime,
                        setup_type='grind_pullback_short',
                        risk_amount=entry * self.risk_pct,
                        reward_risk_ratio=rr,
                        meta={
                            'vwap': vwap,
                            'daily_slope': daily_slope,
                            'trend': 'down'
                        }
                    )
        
        return None
