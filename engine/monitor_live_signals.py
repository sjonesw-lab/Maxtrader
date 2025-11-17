#!/usr/bin/env python3
"""
Live ICT Signal Monitor for Paper Trading
Monitors real-time QQQ data and alerts on ICT confluence signals
"""

import os
import sys
sys.path.insert(0, '.')

from alpaca.data.live import StockDataStream
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import pandas as pd
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from dashboard.notifier import notifier


class LiveSignalMonitor:
    """Monitor live market data for ICT signals."""
    
    def __init__(self):
        self.api_key = os.environ.get('ALPACA_API_KEY')
        self.api_secret = os.environ.get('ALPACA_API_SECRET')
        
        self.data_client = StockHistoricalDataClient(
            self.api_key,
            self.api_secret
        )
        
        # Buffer for 1-minute bars
        self.bars_buffer = []
        self.last_signal_time = None
        
    def get_recent_bars(self, symbol='QQQ', lookback_hours=2):
        """Fetch recent bars for analysis."""
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=datetime.now() - timedelta(hours=lookback_hours),
            end=datetime.now()
        )
        
        bars = self.data_client.get_stock_bars(request)
        df = bars.df.reset_index()
        df = df.rename(columns={'timestamp': 'timestamp', 'symbol': 'symbol'})
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        
        return df
    
    def calculate_atr(self, df, period=14):
        """Calculate ATR."""
        df = df.copy()
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=period).mean()
        return df
    
    def check_for_signals(self, df):
        """Check for ICT confluence signals."""
        # Add sessions and ICT structures
        df = self.calculate_atr(df)
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_all_structures(df, displacement_threshold=1.0)
        
        signals = []
        
        # Check last 10 bars for signals
        for i in range(max(0, len(df) - 10), len(df) - 5):
            # Bullish signal
            if df.iloc[i]['sweep_bullish']:
                window = df.iloc[i:i+6]
                if window['displacement_bullish'].any() and window['mss_bullish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    target_distance = 5.0 * atr
                    
                    signals.append({
                        'timestamp': df.iloc[i]['timestamp'],
                        'direction': 'LONG',
                        'price': df.iloc[i]['close'],
                        'target': df.iloc[i]['close'] + target_distance,
                        'target_distance': target_distance,
                        'atr': atr
                    })
            
            # Bearish signal
            if df.iloc[i]['sweep_bearish']:
                window = df.iloc[i:i+6]
                if window['displacement_bearish'].any() and window['mss_bearish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    target_distance = 5.0 * atr
                    
                    signals.append({
                        'timestamp': df.iloc[i]['timestamp'],
                        'direction': 'SHORT',
                        'price': df.iloc[i]['close'],
                        'target': df.iloc[i]['close'] - target_distance,
                        'target_distance': target_distance,
                        'atr': atr
                    })
        
        return signals
    
    def alert_signal(self, signal):
        """Send alert for new signal."""
        msg = f"""
🎯 ICT CONFLUENCE SIGNAL DETECTED!

Direction: {signal['direction']}
Entry Price: ${signal['price']:.2f}
Target Price: ${signal['target']:.2f}
Target Distance: ${signal['target_distance']:.2f} (5x ATR)
ATR: ${signal['atr']:.2f}

⚠️ MANUAL REVIEW REQUIRED
Review signal and execute if valid.
        """
        
        print(f"\n{'='*60}")
        print(msg)
        print(f"{'='*60}\n")
        
        # Send Pushover notification
        notifier.send_notification(
            message=msg.strip(),
            title=f"🎯 {signal['direction']} Signal Detected",
            priority=1
        )
    
    def run(self, check_interval=60):
        """Run monitoring loop."""
        print("\n" + "="*60)
        print("MaxTrader Live Signal Monitor")
        print("="*60)
        print(f"Monitoring QQQ for ICT confluence signals...")
        print(f"Check interval: {check_interval} seconds")
        print(f"Started at: {datetime.now()}")
        print("="*60 + "\n")
        
        import time
        
        while True:
            try:
                # Get recent bars
                df = self.get_recent_bars()
                
                if len(df) > 0:
                    # Check for signals
                    signals = self.check_for_signals(df)
                    
                    # Alert on new signals
                    for signal in signals:
                        signal_time = signal['timestamp']
                        
                        # Only alert if we haven't alerted for this time period
                        if self.last_signal_time is None or signal_time > self.last_signal_time:
                            self.alert_signal(signal)
                            self.last_signal_time = signal_time
                    
                    current_price = df.iloc[-1]['close']
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] QQQ: ${current_price:.2f} | Bars: {len(df)} | Signals: {len(signals)}")
                
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                print("\n\nMonitoring stopped by user.")
                break
            except Exception as e:
                print(f"Error: {str(e)}")
                time.sleep(check_interval)


if __name__ == '__main__':
    monitor = LiveSignalMonitor()
    monitor.run(check_interval=60)  # Check every minute
