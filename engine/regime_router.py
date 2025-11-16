"""
Regime Router - Selects trading strategy based on volatility regime.

Routes to appropriate strategy:
- Normal Vol (VIX 13-30, ATR ≥0.5%): Wave-based Renko patterns
- High Vol (VIX >30): Liquidity sweeps + reclaims
- Ultra-Low Vol (VIX <13 OR ATR <0.5%): VWAP mean-reversion

Regime Detection:
- VIX primary indicator (when available)
- ATR % as fallback/confirmation
- 30-minute Renko regime for market structure context
"""

from typing import List, Optional, Tuple
import pandas as pd
import numpy as np

from engine.strategy_shared import (
    BaseStrategy,
    StrategySignal,
    MarketContext,
    preprocess_market_data
)
from engine.strategy_high_vol import HighVolStrategy
from engine.strategy_ultra_low_vol import UltraLowVolStrategy


class RegimeRouter:
    """
    Routes to appropriate trading strategy based on volatility regime.
    
    Determines regime from VIX and ATR, then delegates signal generation
    to the correct strategy.
    """
    
    def __init__(
        self,
        normal_vol_strategy: BaseStrategy,
        high_vol_strategy: Optional[BaseStrategy] = None,
        ultra_low_vol_strategy: Optional[BaseStrategy] = None,
        vix_high_threshold: float = 30.0,
        vix_low_threshold: float = 13.0,
        atr_low_threshold: float = 0.5
    ):
        """
        Initialize regime router with strategies.
        
        Args:
            normal_vol_strategy: Strategy for normal volatility (required)
            high_vol_strategy: Strategy for high volatility (optional)
            ultra_low_vol_strategy: Strategy for ultra-low volatility (optional)
            vix_high_threshold: VIX above this = high vol (default: 30)
            vix_low_threshold: VIX below this = ultra-low vol (default: 13)
            atr_low_threshold: ATR % below this = ultra-low vol (default: 0.5)
        """
        self.normal_vol = normal_vol_strategy
        self.high_vol = high_vol_strategy or HighVolStrategy()
        self.ultra_low_vol = ultra_low_vol_strategy or UltraLowVolStrategy()
        
        self.vix_high = vix_high_threshold
        self.vix_low = vix_low_threshold
        self.atr_low = atr_low_threshold
        
    def detect_regime(self, vix: float, atr_pct: float) -> str:
        """
        Detect volatility regime from VIX and ATR.
        
        Rules:
        1. VIX >30 → HIGH_VOL
        2. VIX <8 OR ATR <0.05% → EXTREME_CALM_PAUSE (no trading)
        3. VIX 8-13 OR ATR 0.05-0.5% → ULTRA_LOW_VOL  
        4. Otherwise → NORMAL_VOL
        
        Args:
            vix: VIX value
            atr_pct: ATR as percentage of price
            
        Returns:
            'HIGH_VOL', 'EXTREME_CALM_PAUSE', 'ULTRA_LOW_VOL', or 'NORMAL_VOL'
        """
        # High volatility (crashes, extreme moves)
        if vix > self.vix_high:
            return 'HIGH_VOL'
        
        # Extreme calm (VIX <8 or ATR <0.05%) - PAUSE TRADING
        # Per architect: Too calm for mean-reversion edge, stand down
        if vix < 8.0 or atr_pct < 0.05:
            return 'EXTREME_CALM_PAUSE'
        
        # Ultra-low volatility (VIX 8-13, ATR 0.05-0.5%)
        if vix < self.vix_low or atr_pct < self.atr_low:
            return 'ULTRA_LOW_VOL'
        
        # Normal volatility (wave patterns work best)
        return 'NORMAL_VOL'
    
    def route_to_strategy(
        self,
        context: MarketContext,
        regime: Optional[str] = None
    ) -> Tuple[Optional[BaseStrategy], str]:
        """
        Route to appropriate strategy based on regime.
        
        Args:
            context: Market context with VIX and ATR
            regime: Override regime detection (optional)
            
        Returns:
            (strategy, regime_name) or (None, 'EXTREME_CALM_PAUSE')
        """
        if regime is None:
            regime = self.detect_regime(context.vix, context.atr_pct)
        
        if regime == 'EXTREME_CALM_PAUSE':
            return None, regime  # No trading in extreme calm
        elif regime == 'HIGH_VOL':
            return self.high_vol, regime
        elif regime == 'ULTRA_LOW_VOL':
            return self.ultra_low_vol, regime
        else:
            return self.normal_vol, regime
    
    def generate_signals(
        self,
        context: MarketContext,
        regime_override: Optional[str] = None
    ) -> List[StrategySignal]:
        """
        Generate signals using regime-appropriate strategy.
        
        Returns empty list if regime is EXTREME_CALM_PAUSE.
        
        Args:
            context: Market context
            regime_override: Force specific regime (optional)
            
        Returns:
            List of StrategySignal objects
        """
        strategy, regime = self.route_to_strategy(context, regime_override)
        
        # Update context regime
        context.regime = regime
        
        # EXTREME_CALM_PAUSE: Return empty list (no trading)
        if strategy is None:
            return []
        
        # Generate signals
        signals = strategy.generate_signals(context)
        
        # Tag all signals with regime
        for signal in signals:
            signal.regime = regime
        
        return signals


def calculate_vix_proxy(df_daily: pd.DataFrame, lookback: int = 20) -> float:
    """
    Calculate VIX proxy from daily price data.
    
    Uses realized volatility (std dev of returns) * sqrt(252) * 100
    to approximate VIX.
    
    Args:
        df_daily: Daily OHLCV data
        lookback: Rolling window (default: 20)
        
    Returns:
        VIX proxy value
    """
    if len(df_daily) < lookback + 1:
        return 15.0  # Default VIX
    
    # Calculate daily returns
    returns = df_daily['close'].pct_change().dropna()
    
    if len(returns) < lookback:
        return 15.0
    
    # Rolling volatility
    vol = returns.tail(lookback).std()
    
    # Annualize and scale to VIX (%)
    vix_proxy = vol * np.sqrt(252) * 100
    
    return vix_proxy


def get_regime_stats(regime: str) -> dict:
    """
    Get expected performance stats for regime.
    
    Based on historical validation:
    - Normal Vol: 95.7% WR (Aug-Nov 2025)
    - High Vol: 40.6% WR (COVID 2020) - target: 85%+ with new strategy
    - Ultra-Low Vol: 25% WR (Dec 2024) - target: 60%+ with new strategy
    
    Args:
        regime: 'NORMAL_VOL', 'HIGH_VOL', or 'ULTRA_LOW_VOL'
        
    Returns:
        Dictionary with expected_wr, max_positions, risk_pct
    """
    if regime == 'NORMAL_VOL':
        return {
            'expected_wr': 0.95,
            'max_positions': 3,
            'risk_pct': 0.02,  # 2% per trade
            'strategy': 'wave_renko'
        }
    elif regime == 'HIGH_VOL':
        return {
            'expected_wr': 0.85,  # Target
            'max_positions': 2,
            'risk_pct': 0.0075,  # 0.75% per trade
            'strategy': 'sweep_reclaim'
        }
    else:  # ULTRA_LOW_VOL
        return {
            'expected_wr': 0.60,  # Target
            'max_positions': 4,
            'risk_pct': 0.0125,  # 1.25% per trade
            'strategy': 'vwap_mean_reversion'
        }


if __name__ == '__main__':
    """
    Test regime detection and routing.
    """
    print("=" * 70)
    print("Regime Router Test")
    print("=" * 70)
    print()
    
    # Test regime detection
    test_cases = [
        (35.0, 1.5, 'HIGH_VOL'),
        (25.0, 0.8, 'NORMAL_VOL'),
        (12.0, 0.3, 'ULTRA_LOW_VOL'),
        (15.0, 0.4, 'ULTRA_LOW_VOL'),  # ATR triggers low vol
        (18.0, 1.0, 'NORMAL_VOL'),
    ]
    
    router = RegimeRouter(normal_vol_strategy=None)
    
    print("Regime Detection Tests:")
    print(f"{'VIX':<8} {'ATR%':<8} {'Expected':<20} {'Detected':<20} {'Match':<8}")
    print("-" * 70)
    
    for vix, atr_pct, expected in test_cases:
        detected = router.detect_regime(vix, atr_pct)
        match = '✓' if detected == expected else '✗'
        print(f"{vix:<8.1f} {atr_pct:<8.2f} {expected:<20} {detected:<20} {match:<8}")
    
    print()
    print("Regime Stats:")
    print("-" * 70)
    
    for regime in ['NORMAL_VOL', 'HIGH_VOL', 'ULTRA_LOW_VOL']:
        stats = get_regime_stats(regime)
        print(f"{regime}:")
        print(f"  Expected WR: {stats['expected_wr']*100:.1f}%")
        print(f"  Max Positions: {stats['max_positions']}")
        print(f"  Risk Per Trade: {stats['risk_pct']*100:.2f}%")
        print(f"  Strategy: {stats['strategy']}")
        print()
