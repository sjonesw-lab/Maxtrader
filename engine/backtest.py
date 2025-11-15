"""
Backtesting engine for options-based trading strategies.

Runs strategy signals through options execution and calculates performance.
"""

from typing import List, Dict, Any, Optional
from datetime import time
import pandas as pd
import numpy as np
from dataclasses import dataclass

from engine.strategy import Signal
from engine.options_engine import (
    OptionPosition,
    generate_strikes,
    select_best_structure,
    simulate_option_pnl_over_path,
    calculate_rr_at_target
)


@dataclass
class TradeResult:
    """Result of a single trade."""
    signal: Signal
    position: OptionPosition
    pnl: float
    entry_cost: float
    exit_time: pd.Timestamp
    r_multiple: float


class Backtest:
    """Backtest engine for options strategies."""
    
    def __init__(self, df: pd.DataFrame, min_rr_ratio: float = 1.6):
        """
        Initialize backtest.
        
        Args:
            df: Full market data DataFrame
            min_rr_ratio: Minimum reward-to-risk ratio threshold (default: 1.6)
        """
        self.df = df
        self.min_rr_ratio = min_rr_ratio
        self.trades: List[TradeResult] = []
        
    def run(self, signals: List[Signal], max_bars_held: int = 60) -> Dict[str, Any]:
        """
        Run backtest on all signals.
        
        Args:
            signals: List of trading signals
            max_bars_held: Maximum bars to hold position (default: 60 = 1 hour)
            
        Returns:
            Dictionary with performance metrics
        """
        self.trades = []
        
        for signal in signals:
            trade_result = self._execute_signal(signal, max_bars_held)
            if trade_result:
                self.trades.append(trade_result)
        
        return self._calculate_metrics()
    
    def _execute_signal(self, signal: Signal, max_bars_held: int) -> Optional[TradeResult]:
        """
        Execute a single signal and calculate PnL.
        
        Args:
            signal: Trading signal
            max_bars_held: Maximum bars to hold
            
        Returns:
            TradeResult or None
        """
        entry_idx = signal.index
        entry_time = signal.timestamp
        
        # Check EOD cutoff (stop trading by 3:55 PM to allow 20min before close)
        if entry_time.time() >= time(15, 55):
            return None  # Too close to market close
        
        strikes = generate_strikes(signal.spot, num_strikes=20, increment=1.0)
        
        position = select_best_structure(
            direction=signal.direction,
            spot=signal.spot,
            target=signal.target,
            strikes=strikes,
            entry_time=entry_time,
            mode="auto"
        )
        
        position.target = signal.target
        
        # Calculate R:R with configurable threshold
        rr_ratio = calculate_rr_at_target(position, signal.target)
        if rr_ratio < self.min_rr_ratio:
            return None  # Filtered by R:R
        
        # Force exit by 3:55 PM (20 minutes before 4:15 PM close)
        eod_time = entry_time.replace(hour=15, minute=55, second=0, microsecond=0)
        max_exit_time = entry_time + pd.Timedelta(minutes=max_bars_held)
        exit_cutoff = min(eod_time, max_exit_time)
        
        future_mask = (
            (self.df['timestamp'] > entry_time) &
            (self.df['timestamp'] <= exit_cutoff)
        )
        future_data = self.df.loc[future_mask]
        
        if len(future_data) == 0:
            return None
        
        price_path = future_data['close']
        
        pnl = simulate_option_pnl_over_path(position, price_path, signal.target)
        
        position.exit_time = future_data['timestamp'].iloc[-1]
        
        r_multiple = pnl / abs(position.entry_cost) if position.entry_cost != 0 else 0
        
        return TradeResult(
            signal=signal,
            position=position,
            pnl=pnl,
            entry_cost=position.entry_cost,
            exit_time=position.exit_time,
            r_multiple=r_multiple
        )
    
    def _calculate_metrics(self) -> Dict[str, Any]:
        """
        Calculate performance metrics.
        
        Returns:
            Dictionary with metrics
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_pnl': 0.0,
                'avg_r_multiple': 0.0,
                'total_pnl': 0.0,
                'max_drawdown': 0.0,
                'equity_curve': []
            }
        
        pnls = [t.pnl for t in self.trades]
        r_multiples = [t.r_multiple for t in self.trades]
        
        wins = [p for p in pnls if p > 0]
        
        equity_curve = np.cumsum(pnls)
        
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = running_max - equity_curve
        max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0.0
        
        return {
            'total_trades': len(self.trades),
            'win_rate': len(wins) / len(self.trades) if self.trades else 0.0,
            'avg_pnl': np.mean(pnls),
            'avg_r_multiple': np.mean(r_multiples),
            'total_pnl': sum(pnls),
            'max_drawdown': max_drawdown,
            'equity_curve': equity_curve.tolist(),
            'trades': self.trades
        }
