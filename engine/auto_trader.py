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
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
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
        """Execute conservative strategy - REAL Alpaca stock order (3% risk)."""
        risk_budget = balance * (self.conservative_risk_pct / 100)
        
        # Calculate shares to buy with 3% of account
        shares = int(risk_budget / signal['price'])
        shares = max(1, shares)  # At least 1 share
        
        # Place REAL market order via Alpaca
        try:
            order_data = MarketOrderRequest(
                symbol=self.symbol,
                qty=shares,
                side=OrderSide.BUY if signal['direction'] == 'LONG' else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.trading_client.submit_order(order_data)
            
            position = {
                'strategy': 'conservative',
                'entry_time': datetime.now(),
                'entry_price': signal['price'],
                'direction': signal['direction'],
                'target_price': signal['target'],
                'shares': shares,
                'cost': shares * signal['price'],
                'atr': signal['atr'],
                'status': 'open',
                'order_id': str(order.id),
                'alpaca_order': order
            }
            
            self.positions['conservative'].append(position)
            
            # Notification
            notifier.send_notification(
                f"💼 CONSERVATIVE Entry (REAL ORDER)\n"
                f"{signal['direction']} {shares} shares QQQ\n"
                f"Entry: ${signal['price']:.2f}\n"
                f"Target: ${signal['target']:.2f}\n"
                f"Risk: ${shares * signal['price']:.2f}\n"
                f"Order ID: {order.id}",
                title="Conservative Entry",
                priority=0
            )
            
            print(f"✅ Conservative {signal['direction']}: {shares} shares @ ${signal['price']:.2f} [Order {order.id}]")
            
        except Exception as e:
            print(f"❌ Conservative order failed: {e}")
            notifier.send_notification(
                f"Failed to place conservative order:\n{str(e)[:200]}",
                title="⚠️ Order Error",
                priority=2
            )
    
    def execute_aggressive(self, signal: Dict, balance: float):
        """Execute aggressive strategy - REAL Alpaca stock order (4% risk)."""
        risk_budget = balance * (self.aggressive_risk_pct / 100)
        
        # Use 4% of account for larger position
        shares = int(risk_budget / signal['price'])
        shares = max(1, shares)
        
        # Place REAL market order via Alpaca
        try:
            order_data = MarketOrderRequest(
                symbol=self.symbol,
                qty=shares,
                side=OrderSide.BUY if signal['direction'] == 'LONG' else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            
            order = self.trading_client.submit_order(order_data)
            
            position = {
                'strategy': 'aggressive',
                'entry_time': datetime.now(),
                'entry_price': signal['price'],
                'direction': signal['direction'],
                'target_price': signal['target'],
                'shares': shares,
                'cost': shares * signal['price'],
                'atr': signal['atr'],
                'status': 'open',
                'order_id': str(order.id),
                'alpaca_order': order
            }
            
            self.positions['aggressive'].append(position)
            
            # Notification
            notifier.send_notification(
                f"🚀 AGGRESSIVE Entry (REAL ORDER)\n"
                f"{signal['direction']} {shares} shares QQQ\n"
                f"Entry: ${signal['price']:.2f}\n"
                f"Target: ${signal['target']:.2f}\n"
                f"Risk: ${shares * signal['price']:.2f}\n"
                f"Order ID: {order.id}",
                title="Aggressive Entry",
                priority=0
            )
            
            print(f"✅ Aggressive {signal['direction']}: {shares} shares @ ${signal['price']:.2f} [Order {order.id}]")
            
        except Exception as e:
            print(f"❌ Aggressive order failed: {e}")
            notifier.send_notification(
                f"Failed to place aggressive order:\n{str(e)[:200]}",
                title="⚠️ Order Error",
                priority=2
            )
    
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
        """Close a position - REAL Alpaca close order."""
        strategy = position['strategy']
        
        # Place REAL close order via Alpaca
        try:
            # Reverse the original order direction
            close_side = OrderSide.SELL if position['direction'] == 'LONG' else OrderSide.BUY
            
            order_data = MarketOrderRequest(
                symbol=self.symbol,
                qty=position['shares'],
                side=close_side,
                time_in_force=TimeInForce.DAY
            )
            
            close_order = self.trading_client.submit_order(order_data)
            
            # Calculate actual P&L from stock position
            if position['direction'] == 'LONG':
                pnl = (exit_price - position['entry_price']) * position['shares']
            else:  # SHORT
                pnl = (position['entry_price'] - exit_price) * position['shares']
            
            # Update position
            position['status'] = 'closed'
            position['exit_time'] = datetime.now()
            position['exit_price'] = exit_price
            position['pnl'] = pnl
            position['hit_target'] = hit_target
            position['close_order_id'] = str(close_order.id)
            
            # Update stats
            self.stats[strategy]['trades'] += 1
            self.stats[strategy]['total_pnl'] += pnl
            if pnl > 0:
                self.stats[strategy]['wins'] += 1
            
            # Notification
            emoji = "🎯" if hit_target else "⏱️"
            color = "🟢" if pnl > 0 else "🔴"
            
            notifier.send_notification(
                f"{emoji} {strategy.upper()} Exit {color} (REAL CLOSE)\n"
                f"P&L: ${pnl:+.2f}\n"
                f"Entry: ${position['entry_price']:.2f} → Exit: ${exit_price:.2f}\n"
                f"Shares: {position['shares']}\n"
                f"{'Target HIT' if hit_target else 'Time limit'}\n"
                f"Close Order: {close_order.id}",
                title=f"{strategy.title()} Exit",
                priority=0
            )
            
            print(f"{color} {strategy.upper()} closed: ${pnl:+.2f} ({position['shares']} shares, {'target' if hit_target else 'time'}) [Close Order {close_order.id}]")
            
            self.save_state()
            
        except Exception as e:
            print(f"❌ Failed to close {strategy} position: {e}")
            notifier.send_notification(
                f"Failed to close {strategy} position:\n{str(e)[:200]}",
                title="⚠️ Close Error",
                priority=2
            )
    
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
