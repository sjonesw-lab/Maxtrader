#!/usr/bin/env python3
"""
Live Trading Engine with Dual Strategy Support
- Conservative: 3% risk, 100% longs
- Aggressive: 4% risk, 75% longs + 25% spreads
"""

import os
from datetime import datetime, time
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.live import StockDataStream
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import asyncio


class DualStrategyTrader:
    """
    Manages two concurrent strategies:
    - Conservative: 100% longs, 3% risk
    - Aggressive: 75% longs + 25% spreads, 4% risk
    """
    
    def __init__(self):
        # Alpaca clients
        self.api_key = os.environ.get('ALPACA_API_KEY')
        self.api_secret = os.environ.get('ALPACA_API_SECRET')
        
        self.trading_client = TradingClient(
            self.api_key, 
            self.api_secret, 
            paper=True  # Paper trading
        )
        
        self.data_client = StockHistoricalDataClient(
            self.api_key,
            self.api_secret
        )
        
        # Strategy configuration
        self.conservative_risk_pct = 3.0  # 3% per trade
        self.aggressive_risk_pct = 4.0    # 4% per trade
        
        # Position tracking
        self.conservative_positions = []
        self.aggressive_positions = []
        
        # Performance tracking
        self.stats = {
            'conservative': {
                'trades': 0,
                'wins': 0,
                'total_pnl': 0,
                'active_positions': 0
            },
            'aggressive': {
                'trades': 0,
                'wins': 0,
                'total_pnl': 0,
                'active_positions': 0
            }
        }
        
        # Market data buffer
        self.bars_1min = pd.DataFrame()
        
    def get_account_balance(self) -> float:
        """Get current account equity."""
        account = self.trading_client.get_account()
        return float(account.equity)
    
    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        clock = self.trading_client.get_clock()
        return clock.is_open
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate current ATR."""
        if len(df) < period + 1:
            return 0.5  # Default
        
        df = df.copy()
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        atr = df['tr'].rolling(window=period).mean().iloc[-1]
        return atr if not pd.isna(atr) else 0.5
    
    def check_ict_confluence(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Check for ICT confluence signal.
        Returns signal dict or None.
        """
        # This is a placeholder - you'd implement your full ICT detection here
        # For now, return None (no signals during initial testing)
        return None
    
    def execute_conservative_trade(self, signal: Dict, balance: float, current_price: float):
        """
        Execute conservative strategy (100% longs).
        3% risk budget.
        """
        risk_budget = balance * (self.conservative_risk_pct / 100)
        
        # Calculate position (using ATM options premium estimate)
        premium_per_contract = 2.0  # Simplified estimate
        num_contracts = int(risk_budget / (premium_per_contract * 100))
        num_contracts = max(1, min(num_contracts, 10))
        
        # In paper trading, we'll track this as a simulated options position
        position = {
            'strategy': 'conservative',
            'entry_time': datetime.now(),
            'entry_price': current_price,
            'direction': signal['direction'],
            'target_price': signal['target_price'],
            'num_contracts': num_contracts,
            'premium_paid': num_contracts * premium_per_contract * 100,
            'status': 'open'
        }
        
        self.conservative_positions.append(position)
        self.stats['conservative']['active_positions'] += 1
        
        return position
    
    def execute_aggressive_trade(self, signal: Dict, balance: float, current_price: float):
        """
        Execute aggressive strategy (75% longs + 25% spreads).
        4% risk budget.
        """
        risk_budget = balance * (self.aggressive_risk_pct / 100)
        
        # 75% to longs, 25% to spreads
        long_budget = risk_budget * 0.75
        spread_budget = risk_budget * 0.25
        
        long_premium = 2.0
        spread_cost = 0.8
        
        num_longs = int(long_budget / (long_premium * 100))
        num_spreads = int(spread_budget / (spread_cost * 100))
        
        num_longs = max(1, min(num_longs, 10))
        num_spreads = max(1, min(num_spreads, 10))
        
        position = {
            'strategy': 'aggressive',
            'entry_time': datetime.now(),
            'entry_price': current_price,
            'direction': signal['direction'],
            'target_price': signal['target_price'],
            'num_longs': num_longs,
            'num_spreads': num_spreads,
            'total_cost': (num_longs * long_premium * 100) + (num_spreads * spread_cost * 100),
            'status': 'open'
        }
        
        self.aggressive_positions.append(position)
        self.stats['aggressive']['active_positions'] += 1
        
        return position
    
    def check_exits(self, current_price: float):
        """Check if any positions should be closed."""
        now = datetime.now()
        
        # Check conservative positions
        for pos in self.conservative_positions:
            if pos['status'] != 'open':
                continue
            
            # Time-based exit (60 minutes)
            time_elapsed = (now - pos['entry_time']).total_seconds() / 60
            
            # Target hit check
            hit_target = False
            if pos['direction'] == 'long' and current_price >= pos['target_price']:
                hit_target = True
            elif pos['direction'] == 'short' and current_price <= pos['target_price']:
                hit_target = True
            
            if hit_target or time_elapsed >= 60:
                self.close_position(pos, current_price, hit_target)
        
        # Check aggressive positions
        for pos in self.aggressive_positions:
            if pos['status'] != 'open':
                continue
            
            time_elapsed = (now - pos['entry_time']).total_seconds() / 60
            
            hit_target = False
            if pos['direction'] == 'long' and current_price >= pos['target_price']:
                hit_target = True
            elif pos['direction'] == 'short' and current_price <= pos['target_price']:
                hit_target = True
            
            if hit_target or time_elapsed >= 60:
                self.close_position(pos, current_price, hit_target)
    
    def close_position(self, position: Dict, exit_price: float, hit_target: bool):
        """Close a position and calculate P&L."""
        strategy = position['strategy']
        
        # Simplified P&L calculation
        if hit_target:
            target_distance = abs(exit_price - position['entry_price'])
            
            if strategy == 'conservative':
                exit_value = target_distance * 100 * position['num_contracts']
                pnl = exit_value - position['premium_paid']
            else:
                # Aggressive includes spreads
                long_value = target_distance * 100 * position['num_longs']
                spread_value = 5 * 100 * position['num_spreads']  # Max profit
                exit_value = long_value + spread_value
                pnl = exit_value - position['total_cost']
        else:
            # Expired worthless or small gain
            pnl = -position.get('premium_paid', position.get('total_cost', 0)) * 0.5
        
        # Update position
        position['status'] = 'closed'
        position['exit_price'] = exit_price
        position['exit_time'] = datetime.now()
        position['pnl'] = pnl
        position['hit_target'] = hit_target
        
        # Update stats
        self.stats[strategy]['trades'] += 1
        self.stats[strategy]['total_pnl'] += pnl
        self.stats[strategy]['active_positions'] -= 1
        
        if pnl > 0:
            self.stats[strategy]['wins'] += 1
    
    def get_status(self) -> Dict:
        """Get current trading status."""
        balance = self.get_account_balance()
        
        return {
            'account_balance': balance,
            'market_open': self.is_market_open(),
            'conservative': {
                **self.stats['conservative'],
                'win_rate': (self.stats['conservative']['wins'] / max(1, self.stats['conservative']['trades'])) * 100,
                'positions': [p for p in self.conservative_positions if p['status'] == 'open']
            },
            'aggressive': {
                **self.stats['aggressive'],
                'win_rate': (self.stats['aggressive']['wins'] / max(1, self.stats['aggressive']['trades'])) * 100,
                'positions': [p for p in self.aggressive_positions if p['status'] == 'open']
            }
        }


if __name__ == '__main__':
    # Test connection
    trader = DualStrategyTrader()
    print("Alpaca Connection Test:")
    print(f"Account Balance: ${trader.get_account_balance():,.2f}")
    print(f"Market Open: {trader.is_market_open()}")
