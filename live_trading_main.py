"""
Live trading engine for MaxTrader Liquidity Options Engine v4.

Combines real-time Polygon data stream with ICT structure detection
and Alpaca options execution.
"""

import warnings
warnings.filterwarnings('ignore')

import os
import pandas as pd
from collections import deque
from datetime import datetime, time
import pytz

from engine.polygon_stream import PolygonStreamHandler
from engine.alpaca_execution import AlpacaOptionsExecutor
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_liquidity_sweeps, detect_displacement, detect_fvgs, detect_mss
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy import generate_signals_relaxed


class LiveTradingEngine:
    """Real-time trading engine with ICT signals and options execution."""
    
    def __init__(self, symbol: str = "QQQ", paper: bool = True, max_bars: int = 1000):
        """
        Initialize live trading engine.
        
        Args:
            symbol: Symbol to trade (default: QQQ)
            paper: Use paper trading (default: True)
            max_bars: Maximum bars to keep in memory (default: 1000)
        """
        self.symbol = symbol
        self.max_bars = max_bars
        self.bar_buffer = deque(maxlen=max_bars)
        
        self.stream = PolygonStreamHandler(symbol=symbol, callback=self.on_new_bar)
        self.executor = AlpacaOptionsExecutor(paper=paper)
        
        self.active_positions = {}
        self.ny_tz = pytz.timezone('America/New_York')
        
        print("=" * 70)
        print("MaxTrader Live Trading Engine v4")
        print("=" * 70)
        print(f"Symbol: {symbol}")
        print(f"Mode: {'Paper Trading' if paper else 'Live Trading'}")
        print()
        
        account = self.executor.get_account_info()
        print(f"Account Buying Power: ${account['buying_power']:.2f}")
        print()
    
    def on_new_bar(self, bar: pd.Series):
        """
        Handle new 1-minute bar from Polygon stream.
        
        Args:
            bar: New OHLCV bar
        """
        self.bar_buffer.append(bar)
        
        if len(self.bar_buffer) < 100:
            print(f"Warming up... {len(self.bar_buffer)}/100 bars")
            return
        
        if not self.is_trading_hours(bar['timestamp']):
            return
        
        df = pd.DataFrame(list(self.bar_buffer))
        df = df.reset_index(drop=True)
        
        df = self._build_features(df)
        
        signals = generate_signals_relaxed(
            df,
            require_fvg=False,
            displacement_threshold=1.0,
            extended_window=True,
            enable_regime_filter=True
        )
        
        if signals:
            latest_signal = signals[-1]
            if latest_signal.index == len(df) - 1:
                self._execute_signal(latest_signal)
        
        self._check_exits(df)
    
    def _build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build ICT structures and regime detection on dataframe."""
        renko_df = build_renko(df, mode="atr", k=1.0)
        renko_direction = get_renko_direction_series(df, renko_df)
        df['renko_direction'] = renko_direction
        df['regime'] = detect_regime(df, renko_direction, lookback=20)
        
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_liquidity_sweeps(df)
        df = detect_displacement(df, atr_period=14, threshold=1.0)
        df = detect_fvgs(df)
        df = detect_mss(df)
        
        return df
    
    def _execute_signal(self, signal):
        """Execute trading signal via Alpaca options."""
        if signal.timestamp in self.active_positions:
            print(f"Signal already executed at {signal.timestamp}")
            return
        
        print("\n" + "=" * 70)
        print(f"NEW SIGNAL @ {signal.timestamp}")
        print("=" * 70)
        print(f"Direction: {signal.direction.upper()}")
        print(f"Spot: ${signal.spot:.2f}")
        print(f"Target: ${signal.target:.2f}")
        print(f"Regime: {signal.meta.get('regime', 'unknown')}")
        print(f"Source: {signal.source_session} sweep")
        print()
        
        order_id = self.executor.place_long_option(
            symbol=self.symbol,
            direction=signal.direction,
            spot=signal.spot,
            qty=1
        )
        
        if order_id:
            self.active_positions[signal.timestamp] = {
                'signal': signal,
                'order_id': order_id,
                'entry_time': signal.timestamp,
                'bars_held': 0
            }
            print(f"Position opened: {order_id}")
        else:
            print("Failed to execute signal")
    
    def _check_exits(self, df: pd.DataFrame):
        """Check if active positions should be exited."""
        current_bar = df.iloc[-1]
        
        to_close = []
        
        for entry_time, position in self.active_positions.items():
            position['bars_held'] += 1
            
            signal = position['signal']
            current_price = current_bar['close']
            
            target_hit = False
            if signal.direction == 'long' and current_price >= signal.target:
                target_hit = True
            elif signal.direction == 'short' and current_price <= signal.target:
                target_hit = True
            
            max_bars_exceeded = position['bars_held'] >= 60
            
            if target_hit or max_bars_exceeded:
                reason = "target hit" if target_hit else "max bars held"
                print(f"\nClosing position (opened at {entry_time}): {reason}")
                
                order_status = self.executor.get_order_status(position['order_id'])
                if order_status and order_status['status'] == 'filled':
                    positions = self.executor.get_positions()
                    
                    for p in positions:
                        if 'QQQ' in p['symbol']:
                            self.executor.close_position(p['symbol'])
                
                to_close.append(entry_time)
        
        for entry_time in to_close:
            del self.active_positions[entry_time]
    
    def is_trading_hours(self, ts: pd.Timestamp) -> bool:
        """Check if within trading hours (09:30-16:00 ET)."""
        hour = ts.hour
        minute = ts.minute
        
        market_open = time(9, 30)
        market_close = time(16, 0)
        
        current_time = ts.time()
        
        return market_open <= current_time < market_close
    
    def start(self):
        """Start live trading engine."""
        print("Starting live data stream...")
        print("Press Ctrl+C to stop")
        print("=" * 70)
        print()
        
        try:
            self.stream.start()
        except KeyboardInterrupt:
            print("\n\nStopping live trading engine...")
            self.stream.stop()
            print("Goodbye!")


def main():
    engine = LiveTradingEngine(symbol="QQQ", paper=True)
    engine.start()


if __name__ == '__main__':
    main()
