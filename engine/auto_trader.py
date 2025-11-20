#!/usr/bin/env python3
"""
Fully Automated QQQ-Only Paper Trading System
Uses REAL Polygon.io options pricing for realistic 0DTE paper trading
Executes both conservative (5% risk) and aggressive (5% risk) strategies
QQQ-ONLY: 80.5% win rate vs 53% dual-symbol (SPY removed for performance)
"""

import os
import sys
sys.path.insert(0, '.')

import time
import json
import hashlib
import threading
import shutil
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
    
    def __init__(self, starting_balance=25000, state_file='trader_state.json'):
        # Data clients (using Polygon for BOTH bar data and options pricing)
        self.data_fetcher = PolygonDataFetcher()
        self.options_fetcher = PolygonOptionsFetcher()
        self.market_calendar = MarketCalendar()
        
        # Configuration
        self.symbols = ['QQQ']  # QQQ-ONLY: 80.5% win rate (SPY removed - diluted edge to 53%)
        self.starting_balance = starting_balance
        # BUG FIX: Match backtest risk percentage (was 3.0/4.0, backtest uses 5.0)
        self.conservative_risk_pct = 5.0  # Match backtest exactly
        self.aggressive_risk_pct = 5.0    # Match backtest exactly (dual strategy = 2 positions)
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
        self.last_startup_notification = None  # Track when we last sent startup notification
        self.last_market_open_notification = None  # Track when we last sent market open notification
        
        # Market data buffer (per symbol)
        self.bars_buffer = {symbol: pd.DataFrame() for symbol in self.symbols}
        self.last_signal_check = {symbol: None for symbol in self.symbols}
        
        # Reliability & monitoring
        self.heartbeat_timestamp = datetime.now()
        self.main_loop_timestamp = datetime.now()
        self.heartbeat_thread = None
        self.watchdog_thread = None
        self.running = False
        
        # Load previous state if exists
        self.load_state()
        
        # Check for position recovery on restart
        self.recover_positions_after_restart()
        
        # Save initial state to create the file
        self.save_state()
    
    def get_account_balance(self) -> float:
        """Get current account balance (paper trading)."""
        return self.account_balance
    
    def is_market_open(self) -> bool:
        """Check if market is open (uses MarketCalendar with holiday awareness)."""
        return self.market_calendar.is_market_open_now()
    
    def get_recent_bars(self, symbol: str, hours=2) -> pd.DataFrame:
        """Fetch recent 1-minute bars from Polygon for a specific symbol."""
        end = datetime.now()
        start = end - timedelta(hours=hours)
        
        df = self.data_fetcher.fetch_stock_bars(
            ticker=symbol,
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
    
    def detect_signals(self, symbol: str, df: pd.DataFrame) -> List[Dict]:
        """Detect ICT confluence signals for a specific symbol."""
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
            
            # Skip if we already checked this period for this symbol
            if self.last_signal_check[symbol] and timestamp <= self.last_signal_check[symbol]:
                continue
            
            # Bullish signal
            if df.iloc[i]['sweep_bullish']:
                window = df.iloc[i:i+6]
                if window['displacement_bullish'].any() and window['mss_bullish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'symbol': symbol,
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
                        'symbol': symbol,
                        'timestamp': timestamp,
                        'direction': 'SHORT',
                        'price': price,
                        'atr': atr,
                        'target': price - (self.atr_multiple * atr)
                    })
        
        if signals:
            self.last_signal_check[symbol] = max(s['timestamp'] for s in signals)
        
        return signals
    
    def execute_conservative(self, signal: Dict, balance: float):
        """Execute conservative strategy using REAL Polygon 0DTE options pricing (5% risk to match backtest)."""
        risk_budget = balance * (self.conservative_risk_pct / 100)
        symbol = signal['symbol']
        
        # Fetch REAL 0DTE option price from Polygon
        option_data = self.options_fetcher.get_0dte_option_price(
            underlying_ticker=symbol,
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
            'symbol': symbol,
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
            f"💼 CONSERVATIVE Entry ({symbol})\n"
            f"{signal['direction']} {num_contracts} contracts\n"
            f"Strike: ${option_data['strike']:.2f}\n"
            f"Premium: ${option_data['ask']:.2f} (${total_cost:.2f} total)\n"
            f"Target: ${signal['target']:.2f}\n"
            f"Delta: {option_data['delta']:.2f}",
            title=f"Conservative {symbol}",
            priority=0
        )
        
        print(f"✅ Conservative {symbol} {signal['direction']}: {num_contracts}x {option_data['contract']}")
        print(f"   Premium: ${option_data['ask']:.2f} × {num_contracts} = ${total_cost:.2f}")
        
        self.save_state()
    
    def execute_aggressive(self, signal: Dict, balance: float):
        """Execute aggressive strategy using REAL Polygon 0DTE options pricing (5% risk to match backtest)."""
        risk_budget = balance * (self.aggressive_risk_pct / 100)
        symbol = signal['symbol']
        
        # Fetch REAL 0DTE option price from Polygon
        option_data = self.options_fetcher.get_0dte_option_price(
            underlying_ticker=symbol,
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
            'symbol': symbol,
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
            f"🚀 AGGRESSIVE Entry ({symbol})\n"
            f"{signal['direction']} {num_contracts} contracts\n"
            f"Strike: ${option_data['strike']:.2f}\n"
            f"Premium: ${option_data['ask']:.2f} (${total_cost:.2f} total)\n"
            f"Target: ${signal['target']:.2f}\n"
            f"Delta: {option_data['delta']:.2f}",
            title=f"Aggressive {symbol}",
            priority=0
        )
        
        print(f"✅ Aggressive {symbol} {signal['direction']}: {num_contracts}x {option_data['contract']}")
        print(f"   Premium: ${option_data['ask']:.2f} × {num_contracts} = ${total_cost:.2f}")
        
        self.save_state()
    
    def check_exits(self, symbol_prices: Dict[str, float]):
        """Check and execute exits for both strategies using symbol-specific prices."""
        now = datetime.now()
        
        # Conservative exits
        for pos in self.positions['conservative']:
            if pos['status'] != 'open':
                continue
            
            # Get current price for this position's symbol
            current_price = symbol_prices.get(pos['symbol'])
            if current_price is None:
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
            
            # Get current price for this position's symbol
            current_price = symbol_prices.get(pos['symbol'])
            if current_price is None:
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
        symbol = position.get('symbol', 'QQQ')  # Get symbol from position
        
        # Fetch REAL exit price from Polygon (uses bid = realistic exit)
        exit_value_per_contract = self.options_fetcher.get_exit_price(
            contract_ticker=position['option_contract'],
            underlying=symbol
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
            'symbol': position.get('symbol', 'UNKNOWN'),
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
        """Save current state to file with atomic writes and checksums."""
        state = {
            'account_balance': self.account_balance,
            'starting_balance': self.starting_balance,
            'positions': self.positions,
            'stats': self.stats,
            'trade_history': self.trade_history,
            'last_startup_notification': self.last_startup_notification,
            'last_market_open_notification': self.last_market_open_notification,
            'last_updated': datetime.now().isoformat(),
            'heartbeat': self.heartbeat_timestamp.isoformat(),
            'main_loop_active': self.main_loop_timestamp.isoformat()
        }
        
        # Atomic write: write to temp file, then rename
        temp_file = f"{self.state_file}.tmp"
        try:
            state_json = json.dumps(state, default=str, indent=2)
            
            # Add checksum
            checksum = hashlib.sha256(state_json.encode()).hexdigest()
            state['checksum'] = checksum
            
            # Write to temp file
            with open(temp_file, 'w') as f:
                json.dump(state, f, default=str, indent=2)
            
            # Atomic rename
            shutil.move(temp_file, self.state_file)
            
            # Keep backup of last 3 states
            backup_file = f"{self.state_file}.backup"
            if os.path.exists(self.state_file):
                shutil.copy2(self.state_file, backup_file)
                
        except Exception as e:
            print(f"⚠️ Error saving state: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    def load_state(self):
        """Load previous state if exists, with validation and backup recovery."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    
                    # Validate checksum if present
                    stored_checksum = state.pop('checksum', None)
                    if stored_checksum:
                        state_json = json.dumps({k: v for k, v in state.items() if k != 'checksum'}, default=str, indent=2)
                        calculated_checksum = hashlib.sha256(state_json.encode()).hexdigest()
                        
                        if stored_checksum != calculated_checksum:
                            print("⚠️ State file corrupted, attempting backup recovery...")
                            backup_file = f"{self.state_file}.backup"
                            if os.path.exists(backup_file):
                                shutil.copy2(backup_file, self.state_file)
                                with open(self.state_file, 'r') as f:
                                    state = json.load(f)
                                    print("✅ Recovered from backup")
                            else:
                                raise Exception("Checksum mismatch and no backup available")
                    
                    self.account_balance = state.get('account_balance', self.starting_balance)
                    self.positions = state.get('positions', {'conservative': [], 'aggressive': []})
                    self.stats = state.get('stats', self.stats)
                    self.trade_history = state.get('trade_history', [])
                    self.last_startup_notification = state.get('last_startup_notification')
                    self.last_market_open_notification = state.get('last_market_open_notification')
                    
                    # Check for open positions
                    open_positions = len([p for p in self.positions['conservative'] if p.get('status') == 'open']) + \
                                   len([p for p in self.positions['aggressive'] if p.get('status') == 'open'])
                    
                    print(f"✅ State loaded - Balance: ${self.account_balance:.2f}, Trades: {len(self.trade_history)}")
                    if open_positions > 0:
                        print(f"⚠️  Found {open_positions} open positions - will check for recovery")
                        
        except Exception as e:
            print(f"⚠️ Could not load state: {e}")
    
    def recover_positions_after_restart(self):
        """
        Smart position recovery after crash/restart.
        Evaluates each open position and decides whether to exit or continue.
        """
        for strategy in ['conservative', 'aggressive']:
            positions_to_recover = [p for p in self.positions[strategy] if p.get('status') == 'open']
            
            if not positions_to_recover:
                continue
            
            print(f"\n{'='*70}")
            print(f"🔄 POSITION RECOVERY: {len(positions_to_recover)} {strategy} positions found")
            print(f"{'='*70}")
            
            for position in positions_to_recover:
                try:
                    symbol = position.get('symbol', 'UNKNOWN')
                    entry_time = datetime.fromisoformat(position['entry_time']) if isinstance(position['entry_time'], str) else position['entry_time']
                    time_held = (datetime.now() - entry_time).seconds / 60
                    
                    print(f"\nEvaluating {symbol} {position['direction']} position:")
                    print(f"  Entry: {entry_time.strftime('%I:%M %p')}")
                    print(f"  Time held: {time_held:.0f} minutes")
                    print(f"  Target: ${position['target_price']:.2f}")
                    
                    # Get current price
                    df = self.get_recent_bars(symbol)
                    if len(df) == 0:
                        print(f"  ⚠️  Cannot fetch current price - will monitor on next loop")
                        continue
                    
                    current_price = df.iloc[-1]['close']
                    print(f"  Current: ${current_price:.2f}")
                    
                    # Check exit conditions
                    should_exit = False
                    exit_reason = ""
                    
                    # 1. Target hit while offline?
                    if position['direction'] == 'LONG' and current_price >= position['target_price']:
                        should_exit = True
                        exit_reason = "Target HIT while offline"
                    elif position['direction'] == 'SHORT' and current_price <= position['target_price']:
                        should_exit = True
                        exit_reason = "Target HIT while offline"
                    
                    # 2. Time limit exceeded?
                    elif time_held >= self.max_hold_minutes * 60:
                        should_exit = True
                        exit_reason = f"Time limit exceeded ({time_held/60:.1f} hours)"
                    
                    # 3. Option likely expired? (4+ hours old on 0DTE)
                    elif time_held >= 240:  # 4 hours
                        should_exit = True
                        exit_reason = "Position too old (likely expired)"
                    
                    if should_exit:
                        print(f"  ✅ EXITING: {exit_reason}")
                        
                        # Fetch current option value
                        option_data = self.options_fetcher.get_0dte_option_price(
                            underlying_ticker=symbol,
                            current_price=current_price,
                            direction=position['direction'],
                            strike_offset=-1
                        )
                        
                        if option_data:
                            exit_value_per_contract = option_data['bid'] * 100
                        else:
                            # Estimate intrinsic value if can't fetch quote
                            strike = float(position['option_contract'].split('-')[-1])
                            if position['direction'] == 'LONG':
                                intrinsic = max(0, current_price - strike)
                            else:
                                intrinsic = max(0, strike - current_price)
                            exit_value_per_contract = intrinsic * 100
                        
                        # Execute exit
                        total_exit_value = exit_value_per_contract * position['num_contracts']
                        pnl = total_exit_value - position['premium_paid']
                        hit_target = 'Target HIT' in exit_reason
                        
                        # Update account
                        self.account_balance += total_exit_value
                        
                        # Update stats
                        self.stats[strategy]['trades'] += 1
                        if pnl > 0:
                            self.stats[strategy]['wins'] += 1
                        self.stats[strategy]['total_pnl'] += pnl
                        
                        # Mark position closed
                        position['status'] = 'closed'
                        position['exit_price'] = current_price
                        position['exit_time'] = datetime.now()
                        position['pnl'] = pnl
                        
                        # Log trade
                        self.trade_history.append({
                            'timestamp': datetime.now().isoformat(),
                            'strategy': strategy,
                            'symbol': symbol,
                            'direction': position['direction'],
                            'option_contract': position['option_contract'],
                            'num_contracts': position['num_contracts'],
                            'entry_price': position['entry_price'],
                            'exit_price': current_price,
                            'premium_paid': position['premium_paid'],
                            'total_exit_value': total_exit_value,
                            'pnl': pnl,
                            'hit_target': hit_target,
                            'entry_time': position['entry_time'],
                            'exit_time': datetime.now().isoformat(),
                            'recovery_exit': True
                        })
                        
                        # Send notification
                        notifier.send_notification(
                            f"🔄 RECOVERY: {strategy.upper()} position exited\n"
                            f"Reason: {exit_reason}\n"
                            f"P&L: ${pnl:+.2f}\n"
                            f"Entry: ${position['entry_price']:.2f}\n"
                            f"Exit: ${current_price:.2f}",
                            title="Position Recovery",
                            priority=1
                        )
                        
                        print(f"  💰 P&L: ${pnl:+.2f}")
                        
                    else:
                        print(f"  ✅ Position still valid - resuming normal monitoring")
                
                except Exception as e:
                    print(f"  ⚠️  Error recovering position: {e}")
                    # Send alert
                    notifier.send_notification(
                        f"⚠️ Position recovery ERROR\n"
                        f"Symbol: {symbol}\n"
                        f"Strategy: {strategy}\n"
                        f"Error: {str(e)}\n"
                        f"Manual review required!",
                        title="Recovery Error",
                        priority=2
                    )
            
            print(f"{'='*70}\n")
        
        # Save state after recovery
        self.save_state()
    
    def start_heartbeat(self):
        """Start heartbeat thread that updates state every 5 seconds."""
        def heartbeat_loop():
            while self.running:
                self.heartbeat_timestamp = datetime.now()
                time.sleep(5)
        
        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        print("✅ Heartbeat monitoring started (5-second intervals)")
    
    def start_watchdog(self):
        """Start watchdog thread that terminates if main loop stalls >30 seconds."""
        def watchdog_loop():
            while self.running:
                time_since_loop = (datetime.now() - self.main_loop_timestamp).seconds
                if time_since_loop > 30:
                    print(f"\n🚨 WATCHDOG: Main loop stalled for {time_since_loop}s - terminating!")
                    notifier.send_notification(
                        f"🚨 WATCHDOG ALERT\n"
                        f"Main loop stalled for {time_since_loop} seconds\n"
                        f"System terminating for restart\n"
                        f"Supervisor should auto-restart",
                        title="Watchdog Triggered",
                        priority=2
                    )
                    os._exit(1)  # Force exit
                time.sleep(10)
        
        self.watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
        self.watchdog_thread.start()
        print("✅ Watchdog started (30-second stall detection)")
    
    def get_status(self) -> Dict:
        """Get current status for dashboard."""
        return {
            'conservative': {
                **self.stats['conservative'],
                'win_rate': (self.stats['conservative']['wins'] / max(1, self.stats['conservative']['trades'])) * 100,
                'active_positions': len([p for p in self.positions['conservative'] if p.get('status') == 'open'])
            },
            'aggressive': {
                **self.stats['aggressive'],
                'win_rate': (self.stats['aggressive']['wins'] / max(1, self.stats['aggressive']['trades'])) * 100,
                'active_positions': len([p for p in self.positions['aggressive'] if p.get('status') == 'open'])
            }
        }
    
    def run(self, check_interval=60):
        """
        Main trading loop with intelligent market hours scheduling.
        Auto-starts at 9:25 AM ET, auto-stops at 4:05 PM ET (or 1:05 PM early close).
        Aware of all market holidays and early close days.
        """
        print("\n" + "="*70)
        print("🤖 AUTOMATED QQQ-ONLY TRADER (80.5% Win Rate)")
        print("="*70)
        print(f"Symbol: {', '.join(self.symbols)}")
        print(f"Conservative: 5% risk, ITM options")
        print(f"Aggressive: 5% risk, ITM options")
        print(f"Target: 5x ATR per trade")
        print(f"Position Limit: 1 at a time (no overlap)")
        print(f"Auto-Start: 9:25 AM ET | Auto-Stop: 4:05 PM ET (1:05 PM early close)")
        print(f"Started: {datetime.now()}")
        print("="*70 + "\n")
        
        # Start reliability monitoring
        self.running = True
        self.start_heartbeat()
        self.start_watchdog()
        
        # Startup notification (only send once per day to avoid spam on restarts)
        today = datetime.now().date().isoformat()
        if self.last_startup_notification != today:
            balance = self.get_account_balance()
            notifier.send_notification(
                f"QQQ-ONLY trader started\n"
                f"Symbol: {', '.join(self.symbols)}\n"
                f"Account: ${balance:,.2f}\n"
                f"Win Rate: 80.5% (backtest)\n"
                f"Both strategies: 5% risk",
                title="🤖 QQQ Trader Started",
                priority=1
            )
            self.last_startup_notification = today
            self.save_state()
        else:
            print(f"⚠️  Startup notification already sent today ({today}), skipping...")
        
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
                        # Get prices for all symbols
                        symbol_prices = {}
                        for symbol in self.symbols:
                            df = self.get_recent_bars(symbol)
                            if len(df) > 0:
                                symbol_prices[symbol] = df.iloc[-1]['close']
                        if symbol_prices:
                            self.check_exits(symbol_prices)
                    
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
                    
                    # Only send notification if we haven't already sent it today
                    today = now.date().isoformat()
                    if self.last_market_open_notification != today:
                        notifier.send_notification(
                            f"Trading session started\n"
                            f"Balance: ${self.get_account_balance():,.2f}",
                            title="🚀 Market Open"
                        )
                        self.last_market_open_notification = today
                        self.save_state()
                    else:
                        print(f"   ⚠️  Market open notification already sent today, skipping...")
                    
                    trading_session_active = True
                
                # Not trading hours? Wait
                if not should_trade:
                    time.sleep(check_interval)
                    continue
                
                # Update main loop timestamp (for watchdog)
                self.main_loop_timestamp = datetime.now()
                
                # Get current data for ALL symbols
                symbol_data = {}
                symbol_prices = {}
                for symbol in self.symbols:
                    print(f"   Fetching {symbol} bars...")
                    df = self.get_recent_bars(symbol)
                    if len(df) > 0:
                        symbol_data[symbol] = df
                        symbol_prices[symbol] = df.iloc[-1]['close']
                        print(f"   ✓ Got {len(df)} bars for {symbol}")
                
                if not symbol_data:
                    print("No data available for any symbol, retrying...")
                    time.sleep(check_interval)
                    continue
                
                balance = self.get_account_balance()
                
                # Check for exits first (using prices from all symbols)
                if symbol_prices:
                    self.check_exits(symbol_prices)
                
                # Check for new signals across ALL symbols
                all_signals = []
                for symbol, df in symbol_data.items():
                    signals = self.detect_signals(symbol, df)
                    all_signals.extend(signals)
                
                # Process signals (take first valid one, respect position limits)
                for signal in all_signals:
                    # BUG FIX: Skip if we already have an open position (match backtest logic)
                    # Only allow 1 position at a time to prevent overlapping trades
                    has_open_conservative = any(p['status'] == 'open' for p in self.positions['conservative'])
                    has_open_aggressive = any(p['status'] == 'open' for p in self.positions['aggressive'])
                    
                    if has_open_conservative or has_open_aggressive:
                        print(f"⏭️  {signal['symbol']} signal skipped - existing position(s) open (conservative: {has_open_conservative}, aggressive: {has_open_aggressive})")
                        continue
                    
                    print(f"\n🎯 SIGNAL ({signal['symbol']}): {signal['direction']} @ ${signal['price']:.2f}, target ${signal['target']:.2f}")
                    
                    # Execute both strategies
                    self.execute_conservative(signal, balance)
                    self.execute_aggressive(signal, balance)
                    
                    self.save_state()
                    break  # Only take first signal (respects position limit)
                
                # Status update with all symbol prices
                status = self.get_status()
                price_str = " | ".join([f"{sym}: ${price:.2f}" for sym, price in symbol_prices.items()])
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"{price_str} | "
                      f"Conservative: {status['conservative']['active_positions']} open | "
                      f"Aggressive: {status['aggressive']['active_positions']} open")
                
                # Save state regularly so dashboard knows we're alive
                self.save_state()
                
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
