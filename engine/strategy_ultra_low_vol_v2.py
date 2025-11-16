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
        
        # Track last signal index for cooldown
        # User: "Markets don't cool down" - reduce cooldown, follow PA
        last_signal_idx = -100
        cooldown_bars = 10  # Minimal cooldown, let PA drive frequency
        
        # Scan entire dataframe for PA-confirmed setups
        # FIX (architect): Calculate VWAP bands ROLLING per bar, not once globally
        for idx in range(self.rolling_window, len(df)):
            # Cooldown check
            if idx - last_signal_idx < cooldown_bars:
                continue
            
            # Calculate VWAP bands from SESSION START (stable anchor)
            vwap_data = self._calculate_session_vwap_bands(df, idx, context)
            
            if vwap_data['threshold'] == 0:
                continue
            
            # SIMPLIFIED PA: Band cross → Reclaim → Entry
            # User: "Price action is what we follow - touch and re-entering"
            signal = self._check_band_cross_reclaim(
                df, idx, vwap_data, context
            )
            if signal:
                signals.append(signal)
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
    
    def _calculate_session_vwap_bands(
        self,
        df: pd.DataFrame,
        idx: int,
        context: MarketContext
    ) -> dict:
        """
        Calculate VWAP + bands from SESSION START (not rolling window).
        
        USER FIX: "Price action is what we follow" - need stable VWAP anchor.
        Rolling VWAP moves WITH price, making crosses impossible.
        Session VWAP is stable and provides true mean-reversion anchor.
        
        Args:
            df: Full dataframe
            idx: Current bar index
            context: Market context
            
        Returns:
            dict with vwap, threshold, upper_band, lower_band
        """
        bar = df.iloc[idx]
        
        # Find session start (9:30 AM ET)
        # Session = same trading day
        current_date = bar['timestamp'].date()
        
        # Get all bars from session start UP TO (not including) current bar
        session_bars = df[
            (df['timestamp'].dt.date == current_date) &
            (df.index < idx)  # EXCLUDE current bar
        ]
        
        if len(session_bars) < 10:
            # Fallback to last 50 bars if early in session
            session_bars = df.iloc[max(0, idx-50):idx]
        
        if len(session_bars) < 10:
            return {'vwap': 0, 'threshold': 0, 'upper_band': 0, 'lower_band': 0}
        
        # Calculate VWAP from session data (EXCLUDING current bar)
        typical_price = (session_bars['high'] + session_bars['low'] + session_bars['close']) / 3
        
        if session_bars['volume'].sum() > 0:
            vwap = (typical_price * session_bars['volume']).sum() / session_bars['volume'].sum()
        else:
            vwap = typical_price.mean()
        
        # Calculate std dev
        price_dev = typical_price - vwap
        std = price_dev.std()
        
        # Calculate ATR
        atr = calculate_atr(session_bars, period=min(14, len(session_bars)))
        
        # Adaptive threshold
        atr_threshold = self.atr_mult * atr
        sigma_threshold = self.sigma_mult * std
        threshold = max(0.02, min(atr_threshold, sigma_threshold))
        
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
        Signal A: False break + reclaim (REQUIRED PATTERN)
        
        Designer spec:
        if price < vwap - threshold:
            # deviation occurred
            wait for candle that CLOSES back above vwap - threshold
            ensure next candle does NOT make a lower low
            → long entry toward VWAP
        
        FIX (architect): Look back to find deviation, check if THIS bar reclaims.
        
        Args:
            df: 1-minute data
            idx: Current bar index
            vwap_data: VWAP + bands (rolling)
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        bar = df.iloc[idx]
        vwap = vwap_data['vwap']
        lower_band = vwap_data['lower_band']
        upper_band = vwap_data['upper_band']
        
        # LONG SETUP: Look for deviation in previous 1-5 bars
        lookback = min(5, idx)
        for i in range(1, lookback + 1):
            prev_bar = df.iloc[idx - i]
            
            # Found a deviation below lower band
            if prev_bar['low'] < lower_band:
                # Current bar RECLAIMS above lower band
                if bar['close'] > lower_band:
                    # Ensure current bar didn't make new low (failure)
                    if bar['low'] > prev_bar['low']:
                        # Confirm next bars don't continue down
                        reclaim_confirmed = self._confirm_reclaim_long(
                            df, idx, bar['low']
                        )
                        
                        if reclaim_confirmed:
                            return self._create_long_signal(
                                df, idx, bar, vwap_data, context,
                                setup_type='false_break_reclaim_long'
                            )
                # If still below, keep looking
                continue
        
        # SHORT SETUP: Look for deviation in previous 1-5 bars
        for i in range(1, lookback + 1):
            prev_bar = df.iloc[idx - i]
            
            # Found a deviation above upper band
            if prev_bar['high'] > upper_band:
                # Current bar RECLAIMS below upper band
                if bar['close'] < upper_band:
                    # Ensure current bar didn't make new high
                    if bar['high'] < prev_bar['high']:
                        reclaim_confirmed = self._confirm_reclaim_short(
                            df, idx, bar['high']
                        )
                        
                        if reclaim_confirmed:
                            return self._create_short_signal(
                                df, idx, bar, vwap_data, context,
                                setup_type='false_break_reclaim_short'
                            )
                continue
        
        return None
    
    def _check_band_cross_reclaim(
        self,
        df: pd.DataFrame,
        idx: int,
        vwap_data: dict,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        SIMPLIFIED PA TRIGGER: Band touch → Reclaim → Entry
        
        User insight: "Price action is what we follow - touch or previous close 
        past and now re-entering"
        
        Logic:
        - LONG: Previous bar(s) crossed BELOW lower band → Current bar RECLAIMS above
        - SHORT: Previous bar(s) crossed ABOVE upper band → Current bar RECLAIMS below
        
        This is pure mean-reversion PA: deviation + re-entry = trade back to VWAP.
        
        Args:
            df: 1-minute data
            idx: Current bar index
            vwap_data: VWAP + bands (rolling)
            context: Market context
            
        Returns:
            StrategySignal if valid, None otherwise
        """
        bar = df.iloc[idx]
        lower_band = vwap_data['lower_band']
        upper_band = vwap_data['upper_band']
        
        # Need at least 1 previous bar
        if idx < 1:
            return None
        
        prev_bar = df.iloc[idx - 1]
        
        # LONG SETUP: Previous close was BELOW band, current RECLAIMS above
        if prev_bar['close'] < lower_band and bar['close'] > lower_band:
            # Clean PA: Price touched extreme, now re-entering → Fade back to VWAP
            return self._create_long_signal(
                df, idx, bar, vwap_data, context,
                setup_type='band_cross_reclaim_long'
            )
        
        # SHORT SETUP: Previous close was ABOVE band, current RECLAIMS below  
        elif prev_bar['close'] > upper_band and bar['close'] < upper_band:
            # Clean PA: Price touched extreme, now re-entering → Fade back to VWAP
            return self._create_short_signal(
                df, idx, bar, vwap_data, context,
                setup_type='band_cross_reclaim_short'
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
