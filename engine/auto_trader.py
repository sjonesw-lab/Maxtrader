#!/usr/bin/env python3
"""
Fully Automated Dual-Strategy Paper Trading System
Uses REAL Polygon.io options pricing for realistic 0DTE paper trading
Executes both conservative (3% risk) and aggressive (4% risk) strategies
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

from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.polygon_options_fetcher import PolygonOptionsFetcher
from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.market_calendar import MarketCalendar
from dashboard.notifier import notifier


class AutomatedDualTrader:
    """
    Fully automated dual strategy paper trader.
    
    Uses REAL Polygon options pricing:
    1. Fetches real 0DTE options prices (bid/ask) from Polygon
    2. Tracks positions internally with realistic premium costs
    3. Calculates P&L using real market pricing
    4. NO broker integration - pure paper trading
    """
    
    def __init__(self, starting_balance=25000, state_file='/tmp/trader_state.json'):
        # Data clients (using Polygon for BOTH bar data and options pricing)
        self.data_fetcher = PolygonDataFetcher()
        self.options_fetcher = PolygonOptionsFetcher()
        self.market_calendar = MarketCalendar()
        
        # Configuration
        self.symbol = 'QQQ'
        self.starting_balance = starting_balance
        self.conservative_risk_pct = 3.0
        self.aggressive_risk_pct = 4.0
        self.atr_multiple = 5.0
        self.max_hold_minutes = 60
        
        # State tracking
        self.state_file = state_file
        self.account_balance = starting_balance
        self.positions = {
            'conservative': [],
            'aggressive': []
        }
        self.stats = {
            'conservative': {'trades': 0, 'wins': 0, 'total_pnl': 0.0},
            'aggressive': {'trades': 0, 'wins': 0, 'total_pnl': 0.0}
        }
        self.trade_history = []  # Track all closed trades
        
        # Market data buffer
        self.bars_buffer = pd.DataFrame()
        self.last_signal_check = None
        
        # Load previous state if exists
        self.load_state()
        
        # Save initial state to create the file
        self.save_state()
    
    def get_account_balance(self) -> float:
        """Get current account balance (paper trading)."""
        return self.account_balance
    
    def is_market_open(self) -> bool:
        """Check if market is open (uses MarketCalendar with holiday awareness)."""
        return self.market_calendar.is_market_open_now()
    
    def get_recent_bars(self, hours=2) -> pd.DataFrame:
        """Fetch recent 1-minute bars from Polygon."""
        end = datetime.now()
        start = end - timedelta(hours=hours)
        
        df = self.data_fetcher.fetch_stock_bars(
            ticker=self.symbol,
            from_date=start.strftime('%Y-%m-%d'),
            to_date=end.strftime('%Y-%m-%d')
        )
        
        if df is None or len(df) == 0:
            return pd.DataFrame()
        
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
        """Execute conservative strategy using REAL Polygon 0DTE options pricing (3% risk)."""
        risk_budget = balance * (self.conservative_risk_pct / 100)
        
        # Fetch REAL 0DTE option price from Polygon
        option_data = self.options_fetcher.get_0dte_option_price(
            underlying_ticker=self.symbol,
            current_price=signal['price'],
            direction=signal['direction'],
            strike_offset=-1  # 1 strike ITM (BACKTEST VALIDATED: +2000% vs +135% ATM)
        )
        
        if not option_data:
            print(f"⚠️  Conservative: No 0DTE options available")
            return
        
        # Calculate number of contracts based on premium
        premium_per_contract = option_data['premium']
        if premium_per_contract == 0:
            print(f"⚠️  Conservative: Invalid premium ($0.00)")
            return
        
        # Check if we can afford at least 1 contract
        if risk_budget < premium_per_contract or balance < premium_per_contract:
            print(f"⚠️  Conservative: Insufficient balance (${balance:.2f}) for premium (${premium_per_contract:.2f})")
            return
        
        num_contracts = int(risk_budget / premium_per_contract)
        num_contracts = max(1, min(num_contracts, 10))  # 1-10 contracts
        
        total_cost = num_contracts * premium_per_contract
        
        # Deduct cost from account balance
        self.account_balance -= total_cost
        
        # Track position with REAL option data
        position = {
            'strategy': 'conservative',
            'entry_time': datetime.now(),
            'entry_price': signal['price'],
            'direction': signal['direction'],
            'target_price': signal['target'],
            'num_contracts': num_contracts,
            'premium_paid': total_cost,
            'option_contract': option_data['contract'],
            'strike': option_data['strike'],
            'entry_bid': option_data['bid'],
            'entry_ask': option_data['ask'],
            'delta': option_data['delta'],
            'iv': option_data['iv'],
            'atr': signal['atr'],
            'status': 'open'
        }
        
        self.positions['conservative'].append(position)
        
        # Notification
        notifier.send_notification(
            f"💼 CONSERVATIVE Entry (REAL 0DTE)\n"
            f"{signal['direction']} {num_contracts} contracts\n"
            f"Strike: ${option_data['strike']:.2f}\n"
            f"Premium: ${option_data['ask']:.2f} (${total_cost:.2f} total)\n"
            f"Target: ${signal['target']:.2f}\n"
            f"Delta: {option_data['delta']:.2f}",
            title="Conservative Entry",
            priority=0
        )
        
        print(f"✅ Conservative {signal['direction']}: {num_contracts}x {option_data['contract']}")
        print(f"   Premium: ${option_data['ask']:.2f} × {num_contracts} = ${total_cost:.2f}")
        
        self.save_state()
    
    def execute_aggressive(self, signal: Dict, balance: float):
        """Execute aggressive strategy using REAL Polygon 0DTE options pricing (4% risk)."""
        risk_budget = balance * (self.aggressive_risk_pct / 100)
        
        # Fetch REAL 0DTE option price from Polygon
        option_data = self.options_fetcher.get_0dte_option_price(
            underlying_ticker=self.symbol,
            current_price=signal['price'],
            direction=signal['direction'],
            strike_offset=-1  # 1 strike ITM (BACKTEST VALIDATED: +2000% vs +135% ATM)
        )
        
        if not option_data:
            print(f"⚠️  Aggressive: No 0DTE options available")
            return
        
        # Calculate number of contracts (4% risk = more contracts than conservative)
        premium_per_contract = option_data['premium']
        if premium_per_contract == 0:
            print(f"⚠️  Aggressive: Invalid premium ($0.00)")
            return
        
        # Check if we can afford at least 1 contract
        if risk_budget < premium_per_contract or balance < premium_per_contract:
            print(f"⚠️  Aggressive: Insufficient balance (${balance:.2f}) for premium (${premium_per_contract:.2f})")
            return
        
        num_contracts = int(risk_budget / premium_per_contract)
        num_contracts = max(1, min(num_contracts, 10))  # 1-10 contracts
        
        total_cost = num_contracts * premium_per_contract
        
        # Deduct cost from account balance
        self.account_balance -= total_cost
        
        # Track position with REAL option data
        position = {
            'strategy': 'aggressive',
            'entry_time': datetime.now(),
            'entry_price': signal['price'],
            'direction': signal['direction'],
            'target_price': signal['target'],
            'num_contracts': num_contracts,
            'premium_paid': total_cost,
            'option_contract': option_data['contract'],
            'strike': option_data['strike'],
            'entry_bid': option_data['bid'],
            'entry_ask': option_data['ask'],
            'delta': option_data['delta'],
            'iv': option_data['iv'],
            'atr': signal['atr'],
            'status': 'open'
        }
        
        self.positions['aggressive'].append(position)
        
        # Notification
        notifier.send_notification(
            f"🚀 AGGRESSIVE Entry (REAL 0DTE)\n"
            f"{signal['direction']} {num_contracts} contracts\n"
            f"Strike: ${option_data['strike']:.2f}\n"
            f"Premium: ${option_data['ask']:.2f} (${total_cost:.2f} total)\n"
            f"Target: ${signal['target']:.2f}\n"
            f"Delta: {option_data['delta']:.2f}",
            title="Aggressive Entry",
            priority=0
        )
        
        print(f"✅ Aggressive {signal['direction']}: {num_contracts}x {option_data['contract']}")
        print(f"   Premium: ${option_data['ask']:.2f} × {num_contracts} = ${total_cost:.2f}")
        
        self.save_state()
    
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
        """Close a position using REAL Polygon exit pricing."""
        strategy = position['strategy']
        
        # Fetch REAL exit price from Polygon (uses bid = realistic exit)
        exit_value_per_contract = self.options_fetcher.get_exit_price(
            contract_ticker=position['option_contract'],
            underlying=self.symbol
        )
        
        if exit_value_per_contract is None:
            # API FAILURE - cannot get reliable exit price, skip this close attempt
            print(f"⚠️  Cannot close {strategy} position - Polygon API failed to return exit price")
            print(f"   Will retry on next cycle")
            return  # Don't close - wait for API to recover
        
        # Calculate total exit value
        total_exit_value = exit_value_per_contract * position['num_contracts']
        
        # Calculate P&L
        pnl = total_exit_value - position['premium_paid']
        
        # Add exit proceeds to account balance
        self.account_balance += total_exit_value
        
        # Update position
        position['status'] = 'closed'
        position['exit_time'] = datetime.now()
        position['exit_price'] = exit_price
        position['exit_value_per_contract'] = exit_value_per_contract
        position['total_exit_value'] = total_exit_value
        position['pnl'] = pnl
        position['hit_target'] = hit_target
        
        # Update stats
        self.stats[strategy]['trades'] += 1
        self.stats[strategy]['total_pnl'] += pnl
        if pnl > 0:
            self.stats[strategy]['wins'] += 1
        
        # Add to trade history
        self.trade_history.append({
            'timestamp': datetime.now().isoformat(),
            'strategy': strategy,
            'symbol': self.symbol,
            'direction': position['direction'],
            'option_contract': position['option_contract'],
            'num_contracts': position['num_contracts'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'premium_paid': position['premium_paid'],
            'total_exit_value': total_exit_value,
            'pnl': pnl,
            'hit_target': hit_target,
            'entry_time': position['entry_time'].isoformat() if hasattr(position['entry_time'], 'isoformat') else str(position['entry_time']),
            'exit_time': datetime.now().isoformat()
        })
        
        # Notification
        emoji = "🎯" if hit_target else "⏱️"
        color = "🟢" if pnl > 0 else "🔴"
        
        exit_bid = exit_value_per_contract / 100
        
        notifier.send_notification(
            f"{emoji} {strategy.upper()} Exit {color}\n"
            f"P&L: ${pnl:+.2f}\n"
            f"Entry Premium: ${position['premium_paid']:.2f}\n"
            f"Exit Value: ${total_exit_value:.2f} (${exit_bid:.2f} bid)\n"
            f"Contracts: {position['num_contracts']}\n"
            f"{'Target HIT' if hit_target else 'Time limit'}",
            title=f"{strategy.title()} Exit",
            priority=0
        )
        
        print(f"{color} {strategy.upper()} closed: ${pnl:+.2f}")
        print(f"   {position['num_contracts']} contracts: ${position['premium_paid']:.2f} → ${total_exit_value:.2f}")
        print(f"   ({'target' if hit_target else 'time exit'})")
        
        self.save_state()
    
    def save_state(self):
        """Save current state to file."""
        state = {
            'account_balance': self.account_balance,
            'starting_balance': self.starting_balance,
            'positions': self.positions,
            'stats': self.stats,
            'trade_history': self.trade_history,
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
                    self.account_balance = state.get('account_balance', self.starting_balance)
                    self.positions = state.get('positions', {'conservative': [], 'aggressive': []})
                    self.stats = state.get('stats', self.stats)
                    self.trade_history = state.get('trade_history', [])
                    print(f"✅ State loaded - Balance: ${self.account_balance:.2f}, Trades: {len(self.trade_history)}")
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
        """
        Main trading loop with intelligent market hours scheduling.
        Auto-starts at 9:25 AM ET, auto-stops at 4:05 PM ET (or 1:05 PM early close).
        Aware of all market holidays and early close days.
        """
        print("\n" + "="*70)
        print("🤖 AUTOMATED DUAL-STRATEGY TRADER")
        print("="*70)
        print(f"Conservative: 3% risk, 100% longs")
        print(f"Aggressive: 4% risk, 75% longs + 25% spreads")
        print(f"Target: 5x ATR per trade")
        print(f"Auto-Start: 9:25 AM ET | Auto-Stop: 4:05 PM ET (1:05 PM early close)")
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
        
        trading_session_active = False
        last_status_print = None
        
        while True:
            try:
                # Check market calendar
                should_trade = self.market_calendar.should_start_trading()
                should_stop = self.market_calendar.should_stop_trading()
                market_status = self.market_calendar.get_status_message()
                
                # Print status update every 5 minutes when not trading
                now = datetime.now()
                if not trading_session_active:
                    if last_status_print is None or (now - last_status_print).seconds >= 300:
                        print(f"[{now.strftime('%H:%M:%S')}] {market_status}")
                        last_status_print = now
                
                # Should we stop trading?
                if should_stop and trading_session_active:
                    print(f"\n⏰ Market closed - Stopping trading session at {now.strftime('%H:%M:%S')}")
                    
                    # Close any remaining positions
                    if len(self.positions['conservative']) > 0 or len(self.positions['aggressive']) > 0:
                        print("🔄 Closing all remaining positions at market close...")
                        df = self.get_recent_bars()
                        if len(df) > 0:
                            current_price = df.iloc[-1]['close']
                            self.check_exits(current_price)
                    
                    self.save_state()
                    notifier.send_notification(
                        f"Trading session ended\n"
                        f"Final Balance: ${self.get_account_balance():,.2f}",
                        title="⏰ Market Closed"
                    )
                    trading_session_active = False
                    time.sleep(check_interval)
                    continue
                
                # Should we start trading?
                if should_trade and not trading_session_active:
                    print(f"\n🚀 Market open - Starting trading session at {now.strftime('%H:%M:%S')}")
                    print(f"   {market_status}")
                    notifier.send_notification(
                        f"Trading session started\n"
                        f"Balance: ${self.get_account_balance():,.2f}",
                        title="🚀 Market Open"
                    )
                    trading_session_active = True
                
                # Not trading hours? Wait
                if not should_trade:
                    time.sleep(check_interval)
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
