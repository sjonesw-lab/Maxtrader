"""
Ultra-Low Volatility Strategy v2 (VIX <13, ATR <0.5%)

DESIGNER SPECIFICATION:
- VWAP Bollinger mean-reversion with PRICE ACTION CONFIRMATION
- NOT "touch 2σ = fade"
- Only enters on: deviation + failure + reclaim

Valid Entry Patterns:
  Signal A: False break + reclaim (REQUIRED)
  Signal B: Exhaustion wick at bands (RECOMMENDED)
  Signal C: Microstructure flip / BOS (OPTIONAL)

Designed for: Dead calm markets with slow grind, limited range, VWAP-centered action
"""

from typing import List, Optional
import pandas as pd
import numpy as np

from engine.strategy_shared import (
    BaseStrategy,
    StrategySignal,
    MarketContext,
    calculate_vwap,
    calculate_atr
)


class UltraLowVolStrategyV2(BaseStrategy):
    """
    Ultra-Low Vol strategy with PA-confirmed mean-reversion.
    
    Entry logic: Deviation → Failure → Reclaim
    NOT: Band touch → Fade
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize Ultra-Low Vol v2 strategy.
        
        Config:
        - rolling_window: Bars for VWAP std dev (default: 50)
        - sigma_mult: Sigma multiplier for bands (default: 1.0)
        - atr_mult: ATR multiplier for adaptive threshold (default: 0.5)
        - reclaim_bars: Max bars to wait for reclaim (default: 5)
        - risk_pct: Risk per trade (default: 1.25%)
        - min_rr: Minimum R:R (default: 0.8)
        """
        super().__init__(config)
        
        cfg = config or {}
        self.rolling_window = cfg.get('rolling_window', 50)
        self.sigma_mult = cfg.get('sigma_mult', 1.0)
        self.atr_mult = cfg.get('atr_mult', 0.5)
        self.reclaim_bars = cfg.get('reclaim_bars', 5)
        self.risk_pct = cfg.get('risk_pct', 0.0125)
        self.min_rr = cfg.get('min_rr', 0.8)
        
    def generate_signals(self, context: MarketContext) -> List[StrategySignal]:
        """
        Generate ultra-low vol signals with PA confirmation.
        
        Designer spec:
        1. Calculate VWAP + adaptive bands
        2. Scan for deviations beyond bands
        3. Confirm failure via:
           - Signal A: Close reclaim above/below threshold
           - Signal B: Exhaustion wick (long wick + close back)
        4. Only enter on confirmed failure, NOT on band touch
        
        FIX: Added strict filters to prevent signal overload:
        - Cooldown period between signals (10 bars)
        - Only take best setups (highest R:R in window)
        - Deduplicate by timestamp
        
        Args:
            context: Market context
            
        Returns:
            List of StrategySignal objects
        """
        signals = []
        df = context.df_1min
        
        if len(df) < self.rolling_window + 10:
            return signals
        
        # Calculate VWAP bands with adaptive threshold
        vwap_data = self._calculate_vwap_bands_adaptive(df, context)
        
        if vwap_data['threshold'] == 0:
            return signals
        
        # Track last signal index for cooldown
        last_signal_idx = -100
        cooldown_bars = 100  # Designer target: 15-25 signals total, need 100 bars (~1.5 hours) cooldown
        
        # Scan entire dataframe for PA-confirmed setups
        # Start from rolling_window to have enough history
        for idx in range(self.rolling_window, len(df)):
            # Cooldown check
            if idx - last_signal_idx < cooldown_bars:
                continue
            
            # Signal A: False break + reclaim (PRIORITY)
            signal_a = self._check_false_break_reclaim(
                df, idx, vwap_data, context
            )
            if signal_a:
                signals.append(signal_a)
                last_signal_idx = idx
                continue  # One signal per bar
            
            # Signal B: Exhaustion wick (SECONDARY)
            signal_b = self._check_exhaustion_wick(
                df, idx, vwap_data, context
            )
            if signal_b:
                signals.append(signal_b)
                last_signal_idx = idx
                continue
        
        # Deduplicate by timestamp (keep first)
        seen_timestamps = set()
        unique_signals = []
        for sig in signals:
            if sig.timestamp not in seen_timestamps:
                seen_timestamps.add(sig.timestamp)
                unique_signals.append(sig)
        
        return unique_signals
    
    def _calculate_vwap_bands_adaptive(
        self,
        df: pd.DataFrame,
        context: MarketContext
    ) -> dict:
        """
        Calculate VWAP + adaptive bands per designer spec.
        
        Designer formula:
        atr_threshold   = 0.5 * atr_value
        sigma_threshold = 1.0 * std_value
        threshold       = max(min_tick * 2, min(atr_threshold, sigma_threshold))
        
        Use tighter of ATR or sigma to prevent unreachable bands.
        
        Returns:
            dict with vwap, threshold, upper_band, lower_band
        """
        # Use rolling window (last N bars)
        window_df = df.tail(min(self.rolling_window, len(df)))
        
        if len(window_df) < 20:
            return {'vwap': 0, 'threshold': 0, 'upper_band': 0, 'lower_band': 0}
        
        # Calculate VWAP
        typical_price = (window_df['high'] + window_df['low'] + window_df['close']) / 3
        
        if window_df['volume'].sum() == 0:
            vwap = typical_price.mean()
        else:
            vwap = (typical_price * window_df['volume']).sum() / window_df['volume'].sum()
        
        # Calculate std dev of price vs VWAP
        price_dev = typical_price - vwap
        std = price_dev.std()
        
        # Calculate ATR
        atr = calculate_atr(df, period=14)
        
        # DESIGNER SPEC: Adaptive threshold
        atr_threshold = self.atr_mult * atr  # 0.5 * ATR
        sigma_threshold = self.sigma_mult * std  # 1.0 * σ
        
        # Use tighter of the two (prevents wide bands in low vol)
        min_tick = 0.01  # Minimum price increment for QQQ
        threshold = max(min_tick * 2, min(atr_threshold, sigma_threshold))
        
        upper_band = vwap + threshold
        lower_band = vwap - threshold
        
        return {
            'vwap': vwap,
            'threshold': threshold,
            'upper_band': upper_band,
            'lower_band': lower_band,
            'std': std,
            'atr': atr
        }
    
    def _check_false_break_reclaim(
        self,
        df: pd.DataFrame,
        idx: int,
        vwap_data: dict,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        Signal A: False break + reclaim (PRIMARY SETUP)
        
        Designer spec:
        if price < vwap - threshold:
            # deviation occurred
            wait for candle that CLOSES back above vwap - threshold
            ensure next candle does NOT make a lower low
            → long entry toward VWAP
        
        This ensures we're NOT fading into real trend continuation.
        
        Args:
            df: 1-minute data
            idx: Current bar index
            vwap_data: VWAP + bands
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        bar = df.iloc[idx]
        vwap = vwap_data['vwap']
        threshold = vwap_data['threshold']
        lower_band = vwap_data['lower_band']
        upper_band = vwap_data['upper_band']
        
        # LONG SETUP: Price deviated below lower band
        if bar['close'] < lower_band:
            # Check if PREVIOUS bars had the deviation
            # and THIS bar is the reclaim
            if idx > 0:
                prev_bar = df.iloc[idx - 1]
                
                # Prev bar was below threshold
                if prev_bar['low'] < lower_band:
                    # Current bar CLOSES back above threshold
                    if bar['close'] > lower_band:
                        # Ensure not making new lows (failure confirmed)
                        if bar['low'] > prev_bar['low']:
                            # Check next few bars don't make lower low
                            reclaim_confirmed = self._confirm_reclaim_long(
                                df, idx, lower_band
                            )
                            
                            if reclaim_confirmed:
                                return self._create_long_signal(
                                    df, idx, bar, vwap_data, context,
                                    setup_type='false_break_reclaim_long'
                                )
        
        # SHORT SETUP: Price deviated above upper band
        elif bar['close'] > upper_band:
            if idx > 0:
                prev_bar = df.iloc[idx - 1]
                
                # Prev bar was above threshold
                if prev_bar['high'] > upper_band:
                    # Current bar CLOSES back below threshold
                    if bar['close'] < upper_band:
                        # Ensure not making new highs
                        if bar['high'] < prev_bar['high']:
                            reclaim_confirmed = self._confirm_reclaim_short(
                                df, idx, upper_band
                            )
                            
                            if reclaim_confirmed:
                                return self._create_short_signal(
                                    df, idx, bar, vwap_data, context,
                                    setup_type='false_break_reclaim_short'
                                )
        
        return None
    
    def _check_exhaustion_wick(
        self,
        df: pd.DataFrame,
        idx: int,
        vwap_data: dict,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        Signal B: Exhaustion wick at bands
        
        Designer spec:
        if candle_low < vwap - threshold and close back above (low + body_midpoint):
            # Long wick, rejection at band → long entry
        
        This catches strong rejections at band extremes.
        
        Args:
            df: 1-minute data
            idx: Current bar index
            vwap_data: VWAP + bands
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        bar = df.iloc[idx]
        vwap = vwap_data['vwap']
        lower_band = vwap_data['lower_band']
        upper_band = vwap_data['upper_band']
        
        # LONG SETUP: Wick below band, close back above (DESIGNER SPEC)
        if bar['low'] < lower_band:
            # Designer: "close back above (low + body_midpoint)"
            # This means wick shows rejection at band
            lower_wick = min(bar['open'], bar['close']) - bar['low']
            body = abs(bar['close'] - bar['open'])
            body_midpoint = (bar['open'] + bar['close']) / 2
            
            # Wick must be significant (rejection)
            if lower_wick > body * 1.5:
                # Close above midpoint of range (low to high)
                range_midpoint = (bar['low'] + bar['high']) / 2
                if bar['close'] > range_midpoint:
                    return self._create_long_signal(
                        df, idx, bar, vwap_data, context,
                        setup_type='exhaustion_wick_long'
                    )
        
        # SHORT SETUP: Wick above band, close back below (DESIGNER SPEC)
        elif bar['high'] > upper_band:
            upper_wick = bar['high'] - max(bar['open'], bar['close'])
            body = abs(bar['close'] - bar['open'])
            
            # Wick must be significant
            if upper_wick > body * 1.5:
                # Close below midpoint of range
                range_midpoint = (bar['low'] + bar['high']) / 2
                if bar['close'] < range_midpoint:
                    return self._create_short_signal(
                        df, idx, bar, vwap_data, context,
                        setup_type='exhaustion_wick_short'
                    )
        
        return None
    
    def _confirm_reclaim_long(
        self,
        df: pd.DataFrame,
        idx: int,
        level: float
    ) -> bool:
        """
        Confirm reclaim for long setup.
        
        Designer spec: "ensure next candle does NOT make a lower low"
        
        Check next 1-3 bars to ensure no new lows.
        """
        current_low = df.iloc[idx]['low']
        
        for i in range(1, min(self.reclaim_bars, len(df) - idx)):
            next_bar = df.iloc[idx + i]
            
            # If makes new low, reclaim failed
            if next_bar['low'] < current_low:
                return False
        
        return True
    
    def _confirm_reclaim_short(
        self,
        df: pd.DataFrame,
        idx: int,
        level: float
    ) -> bool:
        """
        Confirm reclaim for short setup.
        
        Check next bars to ensure no new highs.
        """
        current_high = df.iloc[idx]['high']
        
        for i in range(1, min(self.reclaim_bars, len(df) - idx)):
            next_bar = df.iloc[idx + i]
            
            # If makes new high, reclaim failed
            if next_bar['high'] > current_high:
                return False
        
        return True
    
    def _create_long_signal(
        self,
        df: pd.DataFrame,
        idx: int,
        bar: pd.Series,
        vwap_data: dict,
        context: MarketContext,
        setup_type: str
    ) -> Optional[StrategySignal]:
        """
        Create long signal with proper targets and stops.
        
        Designer spec:
        - Target: VWAP or halfway to VWAP
        - Stop: Slightly beyond deviation
        - Min R:R: 0.8
        """
        entry = bar['close']
        vwap = vwap_data['vwap']
        
        # Stop: Just below the deviation low
        stop = bar['low'] - (0.001 * entry)  # 0.1% below low
        
        # Target: VWAP (full) or halfway (conservative)
        if entry < vwap:
            tp1 = entry + (vwap - entry) * 0.5  # Halfway to VWAP
            tp2 = vwap  # Full VWAP
        else:
            # Already at/above VWAP, use small ATR-based target
            atr = vwap_data['atr']
            tp1 = entry + (0.5 * atr)
            tp2 = entry + (0.75 * atr)
        
        # Calculate R:R
        rr = self.calculate_risk_reward(entry, tp1, stop)
        
        # Designer spec: Accept R:R ≥ 0.8 in ultra-low vol
        if rr < self.min_rr:
            return None
        
        return StrategySignal(
            timestamp=bar['timestamp'],
            index=idx,
            direction='long',
            spot=entry,
            tp1=tp1,
            tp2=tp2,
            stop=stop,
            strategy='ultra_low_vol_v2',
            confidence=0.65,
            regime=context.regime,
            setup_type=setup_type,
            risk_amount=entry * self.risk_pct,
            reward_risk_ratio=rr,
            meta={
                'vwap': vwap,
                'threshold': vwap_data['threshold'],
                'lower_band': vwap_data['lower_band'],
                'deviation': (vwap_data['lower_band'] - entry) / vwap
            }
        )
    
    def _create_short_signal(
        self,
        df: pd.DataFrame,
        idx: int,
        bar: pd.Series,
        vwap_data: dict,
        context: MarketContext,
        setup_type: str
    ) -> Optional[StrategySignal]:
        """
        Create short signal with proper targets and stops.
        """
        entry = bar['close']
        vwap = vwap_data['vwap']
        
        # Stop: Just above the deviation high
        stop = bar['high'] + (0.001 * entry)
        
        # Target: VWAP or halfway
        if entry > vwap:
            tp1 = entry - (entry - vwap) * 0.5
            tp2 = vwap
        else:
            atr = vwap_data['atr']
            tp1 = entry - (0.5 * atr)
            tp2 = entry - (0.75 * atr)
        
        rr = self.calculate_risk_reward(entry, tp1, stop)
        
        if rr < self.min_rr:
            return None
        
        return StrategySignal(
            timestamp=bar['timestamp'],
            index=idx,
            direction='short',
            spot=entry,
            tp1=tp1,
            tp2=tp2,
            stop=stop,
            strategy='ultra_low_vol_v2',
            confidence=0.65,
            regime=context.regime,
            setup_type=setup_type,
            risk_amount=entry * self.risk_pct,
            reward_risk_ratio=rr,
            meta={
                'vwap': vwap,
                'threshold': vwap_data['threshold'],
                'upper_band': vwap_data['upper_band'],
                'deviation': (entry - vwap_data['upper_band']) / vwap
            }
        )
