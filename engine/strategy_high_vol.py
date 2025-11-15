"""
High Volatility Strategy (VIX >30).

Designed for COVID-like crash conditions with extreme volatility.

Approach:
- Small, tight, high-quality setups only
- Focus on liquidity sweeps + reclaims (stop hunts that fail)
- Institutional flow alignment
- Conservative targets at VWAP or range mid
- Tight risk: 0.5-1% per trade, max 2-3 positions

Setup Types:
1. Sweep + Reclaim: Price sweeps key level → wick → closes back inside
2. IFVG Retest: After sweep, price retests FVG and holds
3. Displacement Reversal: Strong move in one direction, fade the extreme

Key Levels:
- Prior day high/low
- Overnight session high/low  
- Recent swing highs/lows (15min-1H)
- Session boundaries (Asia/London/NY)
"""

from typing import List, Optional
import pandas as pd
import numpy as np

from engine.strategy_shared import (
    BaseStrategy,
    StrategySignal,
    MarketContext,
    calculate_vwap,
    find_swing_high,
    find_swing_low
)


class HighVolStrategy(BaseStrategy):
    """
    Strategy for high volatility markets (VIX >30).
    
    Trades liquidity sweeps and reclaims with tight risk.
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize High Vol strategy.
        
        Config options:
        - min_wick_ratio: Minimum wick/body ratio for sweep (default: 2.0)
        - reclaim_bars: Max bars to wait for reclaim (default: 3)
        - risk_pct: Risk per trade as % (default: 0.75%)
        - target_mode: 'vwap', 'range_mid', or 'atr' (default: 'vwap')
        - atr_target_mult: ATR multiplier for targets (default: 1.0)
        """
        super().__init__(config)
        
        self.min_wick_ratio = config.get('min_wick_ratio', 2.0)
        self.reclaim_bars = config.get('reclaim_bars', 3)
        self.risk_pct = config.get('risk_pct', 0.0075)  # 0.75%
        self.target_mode = config.get('target_mode', 'vwap')
        self.atr_target_mult = config.get('atr_target_mult', 1.0)
        
    def generate_signals(self, context: MarketContext) -> List[StrategySignal]:
        """
        Generate high vol signals based on sweep + reclaim setups.
        
        Logic:
        1. Identify key levels (prior day, swings, sessions)
        2. Detect sweeps: price briefly violates level with wick
        3. Confirm reclaim: next 1-3 bars close back inside
        4. Optional: Check for IFVG near sweep for higher confidence
        5. Entry on reclaim close
        6. Stop just beyond sweep extreme
        7. Target at VWAP or range mid
        
        Args:
            context: Market data and indicators
            
        Returns:
            List of StrategySignal objects
        """
        signals = []
        df = context.df_1min
        
        if len(df) < 50:
            return signals
        
        # Calculate key levels
        key_levels = self._identify_key_levels(context)
        
        # Calculate VWAP for targets
        vwap = calculate_vwap(df)
        
        # Check last 5 bars for sweep + reclaim patterns
        for i in range(-5, 0):
            idx = len(df) + i
            if idx < 10:
                continue
                
            bar = df.iloc[idx]
            
            # Check for sweep of each key level
            for level_name, level_price in key_levels.items():
                sweep_signal = self._check_sweep_reclaim(
                    df, idx, level_price, level_name, vwap, context
                )
                
                if sweep_signal:
                    signals.append(sweep_signal)
        
        return signals
    
    def _identify_key_levels(self, context: MarketContext) -> dict:
        """
        Identify key liquidity levels to watch for sweeps.
        
        Returns:
            Dictionary of {level_name: price}
        """
        df = context.df_1min
        levels = {}
        
        # Prior day high/low (if available)
        df_daily = context.df_daily
        if len(df_daily) >= 2:
            levels['prior_day_high'] = df_daily['high'].iloc[-2]
            levels['prior_day_low'] = df_daily['low'].iloc[-2]
        
        # Session highs/lows
        if context.session_highs:
            if context.session_highs.get('asia', 0) > 0:
                levels['asia_high'] = context.session_highs['asia']
            if context.session_lows.get('asia', 0) > 0:
                levels['asia_low'] = context.session_lows['asia']
        
        # Recent swing highs/lows (last 50 bars)
        swing_high = find_swing_high(df.tail(50), lookback=50)
        swing_low = find_swing_low(df.tail(50), lookback=50)
        
        if swing_high:
            levels['swing_high'] = swing_high
        if swing_low:
            levels['swing_low'] = swing_low
        
        return levels
    
    def _check_sweep_reclaim(
        self,
        df: pd.DataFrame,
        idx: int,
        level: float,
        level_name: str,
        vwap: float,
        context: MarketContext
    ) -> Optional[StrategySignal]:
        """
        Check if bar swept a level and if subsequent bars reclaimed.
        
        Sweep criteria:
        1. High/low breaches level
        2. Close is back on the "good" side of level (wick sweep)
        3. Wick is at least 2x the body size
        
        Reclaim criteria:
        1. Within next 1-3 bars, price closes decisively inside
        2. No re-sweep of the level
        
        Args:
            df: 1-minute data
            idx: Bar index to check
            level: Price level
            level_name: Name of level (for metadata)
            vwap: Current VWAP
            context: Market context
            
        Returns:
            StrategySignal if valid setup, None otherwise
        """
        bar = df.iloc[idx]
        
        # Check for bullish sweep (sweep low, reclaim above)
        if bar['low'] < level and bar['close'] > level:
            # Wick must be significant (at least 2x body)
            body = abs(bar['close'] - bar['open'])
            lower_wick = bar['open'] - bar['low'] if bar['close'] > bar['open'] else bar['close'] - bar['low']
            
            if lower_wick < body * self.min_wick_ratio:
                return None
            
            # Check reclaim in next bars
            reclaimed = self._check_reclaim(df, idx, level, direction='long')
            
            if reclaimed:
                # Valid bullish setup
                entry = bar['close']
                stop = bar['low'] - (0.001 * entry)  # Just below sweep low
                
                # Target based on mode
                if self.target_mode == 'vwap' and vwap > entry:
                    tp1 = vwap
                    tp2 = vwap + (vwap - entry)  # Same distance beyond VWAP
                elif self.target_mode == 'range_mid':
                    range_high = df['high'].tail(20).max()
                    range_low = df['low'].tail(20).min()
                    tp1 = (range_high + range_low) / 2
                    tp2 = range_high
                else:  # ATR-based
                    atr = context.atr_pct * entry / 100
                    tp1 = entry + (self.atr_target_mult * atr)
                    tp2 = entry + (1.5 * self.atr_target_mult * atr)
                
                # Calculate R:R
                rr = self.calculate_risk_reward(entry, tp1, stop)
                
                # Only take if R:R >= 1.5:1
                if rr < 1.5:
                    return None
                
                return StrategySignal(
                    timestamp=bar['timestamp'],
                    index=idx,
                    direction='long',
                    spot=entry,
                    tp1=tp1,
                    tp2=tp2,
                    stop=stop,
                    strategy='high_vol',
                    confidence=0.7,  # High vol setups have decent confidence
                    regime=context.regime,
                    setup_type=f'sweep_reclaim_{level_name}',
                    risk_amount=entry * self.risk_pct,
                    reward_risk_ratio=rr,
                    meta={
                        'level': level,
                        'level_name': level_name,
                        'sweep_low': bar['low'],
                        'vwap': vwap
                    }
                )
        
        # Check for bearish sweep (sweep high, reclaim below)
        elif bar['high'] > level and bar['close'] < level:
            # Wick must be significant
            body = abs(bar['close'] - bar['open'])
            upper_wick = bar['high'] - bar['close'] if bar['close'] > bar['open'] else bar['high'] - bar['open']
            
            if upper_wick < body * self.min_wick_ratio:
                return None
            
            # Check reclaim
            reclaimed = self._check_reclaim(df, idx, level, direction='short')
            
            if reclaimed:
                # Valid bearish setup
                entry = bar['close']
                stop = bar['high'] + (0.001 * entry)  # Just above sweep high
                
                # Target based on mode
                if self.target_mode == 'vwap' and vwap < entry:
                    tp1 = vwap
                    tp2 = vwap - (entry - vwap)
                elif self.target_mode == 'range_mid':
                    range_high = df['high'].tail(20).max()
                    range_low = df['low'].tail(20).min()
                    tp1 = (range_high + range_low) / 2
                    tp2 = range_low
                else:  # ATR-based
                    atr = context.atr_pct * entry / 100
                    tp1 = entry - (self.atr_target_mult * atr)
                    tp2 = entry - (1.5 * self.atr_target_mult * atr)
                
                # Calculate R:R
                rr = self.calculate_risk_reward(entry, tp1, stop)
                
                # Only take if R:R >= 1.5:1
                if rr < 1.5:
                    return None
                
                return StrategySignal(
                    timestamp=bar['timestamp'],
                    index=idx,
                    direction='short',
                    spot=entry,
                    tp1=tp1,
                    tp2=tp2,
                    stop=stop,
                    strategy='high_vol',
                    confidence=0.7,
                    regime=context.regime,
                    setup_type=f'sweep_reclaim_{level_name}',
                    risk_amount=entry * self.risk_pct,
                    reward_risk_ratio=rr,
                    meta={
                        'level': level,
                        'level_name': level_name,
                        'sweep_high': bar['high'],
                        'vwap': vwap
                    }
                )
        
        return None
    
    def _check_reclaim(
        self,
        df: pd.DataFrame,
        sweep_idx: int,
        level: float,
        direction: str
    ) -> bool:
        """
        Check if level was reclaimed after sweep.
        
        For long: Next 1-3 bars close above level without re-sweeping low
        For short: Next 1-3 bars close below level without re-sweeping high
        
        Args:
            df: DataFrame
            sweep_idx: Index of sweep bar
            level: Level price
            direction: 'long' or 'short'
            
        Returns:
            True if reclaimed, False otherwise
        """
        # Check next few bars
        for i in range(1, self.reclaim_bars + 1):
            next_idx = sweep_idx + i
            
            if next_idx >= len(df):
                return False
            
            next_bar = df.iloc[next_idx]
            
            if direction == 'long':
                # Must close above level
                if next_bar['close'] > level * 1.0005:  # 0.05% above
                    # Check no re-sweep of low
                    if next_bar['low'] > df.iloc[sweep_idx]['low']:
                        return True
            else:  # short
                # Must close below level
                if next_bar['close'] < level * 0.9995:  # 0.05% below
                    # Check no re-sweep of high
                    if next_bar['high'] < df.iloc[sweep_idx]['high']:
                        return True
        
        return False
