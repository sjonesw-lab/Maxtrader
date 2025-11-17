#!/usr/bin/env python3
"""
Fully Automated Dual-Strategy Paper Trading System
Executes both conservative (3% risk, 100% longs) and aggressive (4% risk, 75/25 mix)
"""

import os
import sys
sys.path.insert(0, '.')

import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from dashboard.notifier import notifier


class AutomatedDualTrader:
    """
    Fully automated dual strategy trader.
    
    NOTE: Alpaca paper trading doesn't support options, so we:
    1. Track simulated options positions internally
    2. Use small stock positions as proxies for risk tracking
    3. Calculate P&L based on actual price movements
    """
    
    def __init__(self, state_file='/tmp/trader_state.json'):
        # Alpaca clients
        self.api_key = os.environ.get('ALPACA_API_KEY')
        self.api_secret = os.environ.get('ALPACA_API_SECRET')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET must be set in environment")
        
        self.trading_client = TradingClient(self.api_key, self.api_secret, paper=True)
        self.data_client = StockHistoricalDataClient(self.api_key, self.api_secret)
        
        # Configuration
        self.symbol = 'QQQ'
        self.conservative_risk_pct = 3.0
        self.aggressive_risk_pct = 4.0
        self.atr_multiple = 5.0
        self.max_hold_minutes = 60
        
        # State tracking
        self.state_file = state_file
        self.positions = {
            'conservative': [],
            'aggressive': []
        }
        self.stats = {
            'conservative': {'trades': 0, 'wins': 0, 'total_pnl': 0.0},
            'aggressive': {'trades': 0, 'wins': 0, 'total_pnl': 0.0}
        }
        
        # Market data buffer
        self.bars_buffer = pd.DataFrame()
        self.last_signal_check = None
        
        # Load previous state if exists
        self.load_state()
    
    def get_account_balance(self) -> float:
        """Get current account equity."""
        account = self.trading_client.get_account()
        return float(account.equity)
    
    def is_market_open(self) -> bool:
        """Check if market is open."""
        clock = self.trading_client.get_clock()
        return clock.is_open
    
    def get_recent_bars(self, hours=2) -> pd.DataFrame:
        """Fetch recent 1-minute bars."""
        request = StockBarsRequest(
            symbol_or_symbols=self.symbol,
            timeframe=TimeFrame.Minute,
            start=datetime.now() - timedelta(hours=hours),
            end=datetime.now()
        )
        
        bars = self.data_client.get_stock_bars(request)
        df = bars.df.reset_index()
        df = df.rename(columns={'timestamp': 'timestamp'})
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        return df
    
    def calculate_atr(self, df: pd.DataFrame, period=14) -> float:
        """Calculate ATR."""
        if len(df) < period + 1:
            return 0.5
        
        df = df.copy()
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        atr = df['tr'].rolling(window=period).mean().iloc[-1]
        return atr if not pd.isna(atr) else 0.5
    
    def detect_signals(self, df: pd.DataFrame) -> List[Dict]:
        """Detect ICT confluence signals."""
        # Prep data
        df = df.copy()
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=14).mean()
        
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_all_structures(df, displacement_threshold=1.0)
        
        signals = []
        
        # Check last 10 bars for new signals (need 5 bars lookahead for confluence)
        for i in range(max(0, len(df) - 10), len(df) - 5):
            timestamp = df.iloc[i]['timestamp']
            
            # Skip if we already checked this period
            if self.last_signal_check and timestamp <= self.last_signal_check:
                continue
            
            # Bullish signal
            if df.iloc[i]['sweep_bullish']:
                window = df.iloc[i:i+6]
                if window['displacement_bullish'].any() and window['mss_bullish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'timestamp': timestamp,
                        'direction': 'LONG',
                        'price': price,
                        'atr': atr,
                        'target': price + (self.atr_multiple * atr)
                    })
            
            # Bearish signal
            if df.iloc[i]['sweep_bearish']:
                window = df.iloc[i:i+6]
                if window['displacement_bearish'].any() and window['mss_bearish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'timestamp': timestamp,
                        'direction': 'SHORT',
                        'price': price,
                        'atr': atr,
                        'target': price - (self.atr_multiple * atr)
                    })
        
        if signals:
            self.last_signal_check = max(s['timestamp'] for s in signals)
        
        return signals
    
    def execute_conservative(self, signal: Dict, balance: float):
        """Execute conservative strategy (100% longs, 3% risk)."""
        risk_budget = balance * (self.conservative_risk_pct / 100)
        
        # Simulated options: $2 premium estimate
        premium_per_contract = 2.0
        num_contracts = int(risk_budget / (premium_per_contract * 100))
        num_contracts = max(1, min(num_contracts, 10))
        
        total_cost = num_contracts * premium_per_contract * 100
        
        position = {
            'strategy': 'conservative',
            'entry_time': datetime.now(),
            'entry_price': signal['price'],
            'direction': signal['direction'],
            'target_price': signal['target'],
            'num_contracts': num_contracts,
            'premium_paid': total_cost,
            'atr': signal['atr'],
            'status': 'open'
        }
        
        self.positions['conservative'].append(position)
        
        # Notification
        notifier.send_notification(
            f"💼 CONSERVATIVE Entry\n"
            f"{signal['direction']} {num_contracts} contracts\n"
            f"Entry: ${signal['price']:.2f}\n"
            f"Target: ${signal['target']:.2f}\n"
            f"Risk: ${total_cost:.2f}",
            title="Conservative Entry",
            priority=0
        )
        
        print(f"✅ Conservative {signal['direction']}: {num_contracts} contracts @ ${signal['price']:.2f}")
    
    def execute_aggressive(self, signal: Dict, balance: float):
        """Execute aggressive strategy (75% longs + 25% spreads, 4% risk)."""
        risk_budget = balance * (self.aggressive_risk_pct / 100)
        
        long_budget = risk_budget * 0.75
        spread_budget = risk_budget * 0.25
        
        long_premium = 2.0
        spread_cost = 0.8
        
        num_longs = int(long_budget / (long_premium * 100))
        num_spreads = int(spread_budget / (spread_cost * 100))
        
        num_longs = max(1, min(num_longs, 10))
        num_spreads = max(1, min(num_spreads, 10))
        
        total_cost = (num_longs * long_premium * 100) + (num_spreads * spread_cost * 100)
        
        position = {
            'strategy': 'aggressive',
            'entry_time': datetime.now(),
            'entry_price': signal['price'],
            'direction': signal['direction'],
            'target_price': signal['target'],
            'num_longs': num_longs,
            'num_spreads': num_spreads,
            'total_cost': total_cost,
            'atr': signal['atr'],
            'status': 'open'
        }
        
        self.positions['aggressive'].append(position)
        
        # Notification
        notifier.send_notification(
            f"🚀 AGGRESSIVE Entry\n"
            f"{signal['direction']} {num_longs}L+{num_spreads}S\n"
            f"Entry: ${signal['price']:.2f}\n"
            f"Target: ${signal['target']:.2f}\n"
            f"Risk: ${total_cost:.2f}",
            title="Aggressive Entry",
            priority=0
        )
        
        print(f"✅ Aggressive {signal['direction']}: {num_longs} longs + {num_spreads} spreads @ ${signal['price']:.2f}")
    
    def check_exits(self, current_price: float):
        """Check and execute exits for both strategies."""
        now = datetime.now()
        
        # Conservative exits
        for pos in self.positions['conservative']:
            if pos['status'] != 'open':
                continue
            
            time_elapsed = (now - pos['entry_time']).total_seconds() / 60
            hit_target = False
            
            if pos['direction'] == 'LONG' and current_price >= pos['target_price']:
                hit_target = True
            elif pos['direction'] == 'SHORT' and current_price <= pos['target_price']:
                hit_target = True
            
            if hit_target or time_elapsed >= self.max_hold_minutes:
                self.close_position(pos, current_price, hit_target)
        
        # Aggressive exits
        for pos in self.positions['aggressive']:
            if pos['status'] != 'open':
                continue
            
            time_elapsed = (now - pos['entry_time']).total_seconds() / 60
            hit_target = False
            
            if pos['direction'] == 'LONG' and current_price >= pos['target_price']:
                hit_target = True
            elif pos['direction'] == 'SHORT' and current_price <= pos['target_price']:
                hit_target = True
            
            if hit_target or time_elapsed >= self.max_hold_minutes:
                self.close_position(pos, current_price, hit_target)
    
    def close_position(self, position: Dict, exit_price: float, hit_target: bool):
        """Close a position and calculate P&L."""
        strategy = position['strategy']
        
        # Calculate P&L based on actual price movement
        price_change = abs(exit_price - position['entry_price'])
        
        if strategy == 'conservative':
            if hit_target:
                # Target hit: full intrinsic value
                exit_value = price_change * 100 * position['num_contracts']
            else:
                # Partial: estimate remaining value
                exit_value = position['premium_paid'] * 0.3  # Time decay
            
            pnl = exit_value - position['premium_paid']
        
        else:  # aggressive
            if hit_target:
                # Longs get full movement, spreads get capped
                long_value = price_change * 100 * position['num_longs']
                spread_value = min(price_change, 5.0) * 100 * position['num_spreads']
                exit_value = long_value + spread_value
            else:
                exit_value = position['total_cost'] * 0.3
            
            pnl = exit_value - position['total_cost']
        
        # Update position
        position['status'] = 'closed'
        position['exit_time'] = datetime.now()
        position['exit_price'] = exit_price
        position['pnl'] = pnl
        position['hit_target'] = hit_target
        
        # Update stats
        self.stats[strategy]['trades'] += 1
        self.stats[strategy]['total_pnl'] += pnl
        if pnl > 0:
            self.stats[strategy]['wins'] += 1
        
        # Notification
        emoji = "🎯" if hit_target else "⏱️"
        color = "🟢" if pnl > 0 else "🔴"
        
        notifier.send_notification(
            f"{emoji} {strategy.upper()} Exit {color}\n"
            f"P&L: ${pnl:+.2f}\n"
            f"Exit: ${exit_price:.2f}\n"
            f"{'Target HIT' if hit_target else 'Time limit'}",
            title=f"{strategy.title()} Exit",
            priority=0
        )
        
        print(f"{color} {strategy.upper()} closed: ${pnl:+.2f} ({'target' if hit_target else 'time'})")
        
        self.save_state()
    
    def save_state(self):
        """Save current state to file."""
        state = {
            'positions': self.positions,
            'stats': self.stats,
            'last_updated': datetime.now().isoformat()
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, default=str)
    
    def load_state(self):
        """Load previous state if exists."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.positions = state.get('positions', {'conservative': [], 'aggressive': []})
                    self.stats = state.get('stats', self.stats)
                    print(f"✅ State loaded: {self.stats}")
        except Exception as e:
            print(f"⚠️ Could not load state: {e}")
    
    def get_status(self) -> Dict:
        """Get current status for dashboard."""
        return {
            'conservative': {
                **self.stats['conservative'],
                'win_rate': (self.stats['conservative']['wins'] / max(1, self.stats['conservative']['trades'])) * 100,
                'active_positions': len([p for p in self.positions['conservative'] if p['status'] == 'open'])
            },
            'aggressive': {
                **self.stats['aggressive'],
                'win_rate': (self.stats['aggressive']['wins'] / max(1, self.stats['aggressive']['trades'])) * 100,
                'active_positions': len([p for p in self.positions['aggressive'] if p['status'] == 'open'])
            }
        }
    
    def run(self, check_interval=60):
        """Main trading loop."""
        print("\n" + "="*70)
        print("🤖 AUTOMATED DUAL-STRATEGY TRADER")
        print("="*70)
        print(f"Conservative: 3% risk, 100% longs")
        print(f"Aggressive: 4% risk, 75% longs + 25% spreads")
        print(f"Target: 5x ATR per trade")
        print(f"Started: {datetime.now()}")
        print("="*70 + "\n")
        
        # Startup notification
        balance = self.get_account_balance()
        notifier.send_notification(
            f"Automated trader started\n"
            f"Account: ${balance:,.2f}\n"
            f"Conservative: 3% risk\n"
            f"Aggressive: 4% risk",
            title="🤖 Trader Started",
            priority=1
        )
        
        while True:
            try:
                # Check market status
                if not self.is_market_open():
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Market closed, waiting...")
                    time.sleep(300)  # Check every 5 min
                    continue
                
                # Get current data
                df = self.get_recent_bars()
                if len(df) == 0:
                    print("No data available, retrying...")
                    time.sleep(check_interval)
                    continue
                
                current_price = df.iloc[-1]['close']
                balance = self.get_account_balance()
                
                # Check for exits first
                self.check_exits(current_price)
                
                # Check for new signals
                signals = self.detect_signals(df)
                
                for signal in signals:
                    print(f"\n🎯 SIGNAL: {signal['direction']} @ ${signal['price']:.2f}, target ${signal['target']:.2f}")
                    
                    # Execute both strategies
                    self.execute_conservative(signal, balance)
                    self.execute_aggressive(signal, balance)
                    
                    self.save_state()
                
                # Status update
                status = self.get_status()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Price: ${current_price:.2f} | "
                      f"Conservative: {status['conservative']['active_positions']} open | "
                      f"Aggressive: {status['aggressive']['active_positions']} open")
                
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                print("\n\n🛑 Trader stopped by user")
                self.save_state()
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                notifier.send_notification(
                    f"Error in trading loop:\n{str(e)[:200]}",
                    title="⚠️ Trader Error",
                    priority=2
                )
                time.sleep(check_interval)


if __name__ == '__main__':
    trader = AutomatedDualTrader()
    trader.run(check_interval=60)
