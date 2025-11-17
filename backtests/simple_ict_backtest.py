#!/usr/bin/env python3
"""
Simple ICT confluence backtest - test if institutional signals are profitable.

Entry: Bullish sweep + displacement + MSS within 5 bars = GO LONG
Target: 0.5% gain
Stop: 0.25% loss (2:1 RR)
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

def find_confluence_signals(df):
    """Find bars where we have sweep + displacement + MSS confluence."""
    signals = []
    
    for i in range(len(df) - 5):
        # Check if this bar has a sweep
        if df.iloc[i]['sweep_bullish']:
            # Check next 5 bars for displacement AND MSS
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long'
                })
        
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short'
                })
    
    return pd.DataFrame(signals)


def backtest_ict_signals(df, signals, target_pct=0.5, stop_pct=None, max_hold_bars=60):
    """Backtest the ICT confluence signals."""
    trades = []
    last_exit_time = None
    
    for _, signal in signals.iterrows():
        # No overlapping trades
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Find next bar for entry
        entry_mask = df['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df[entry_mask].index[0]
        entry_bar = df.loc[entry_idx]
        entry_price = entry_bar['open']
        
        # Calculate targets
        if signal['direction'] == 'long':
            target_price = entry_price * (1 + target_pct/100)
            stop_price = entry_price * (1 - stop_pct/100) if stop_pct else None
        else:
            target_price = entry_price * (1 - target_pct/100)
            stop_price = entry_price * (1 + stop_pct/100) if stop_pct else None
        
        # Check exit window
        exit_window = df.loc[entry_idx:entry_idx + max_hold_bars]
        if len(exit_window) == 0:
            continue
        
        # Track trade
        trade = {
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'direction': signal['direction'],
            'target': target_price,
            'stop': stop_price
        }
        
        # Find exit
        hit_target = False
        hit_stop = False
        exit_price = None
        exit_time = None
        bars_held = 0
        
        for idx, bar in exit_window.iterrows():
            bars_held += 1
            
            if signal['direction'] == 'long':
                if bar['high'] >= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    break
                if stop_price and bar['low'] <= stop_price:
                    hit_stop = True
                    exit_price = stop_price
                    exit_time = bar['timestamp']
                    break
            else:
                if bar['low'] <= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    break
                if stop_price and bar['high'] >= stop_price:
                    hit_stop = True
                    exit_price = stop_price
                    exit_time = bar['timestamp']
                    break
        
        # Time-based exit
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        # Calculate P&L
        if signal['direction'] == 'long':
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
        
        pnl_pct = (pnl / entry_price) * 100
        
        trade.update({
            'exit_time': exit_time,
            'exit_price': exit_price,
            'bars_held': bars_held,
            'hit_target': hit_target,
            'hit_stop': hit_stop,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })
        
        trades.append(trade)
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_metrics(trades_df):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return None
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] < 0]
    
    total_wins = winners['pnl'].sum() if len(winners) > 0 else 0
    total_losses = abs(losers['pnl'].sum()) if len(losers) > 0 else 0
    
    return {
        'total_trades': len(trades_df),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'profit_factor': total_wins / total_losses if total_losses > 0 else 0,
        'total_pnl': trades_df['pnl'].sum(),
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'stop_hit_rate': (trades_df['hit_stop'].sum() / len(trades_df)) * 100
    }


# Run backtest
print("\n" + "="*70)
print("ICT CONFLUENCE STRATEGY BACKTEST")
print("="*70)

# Test different targets WITHOUT STOP LOSS
test_configs = [
    {'target': 0.3, 'stop': None, 'name': 'NO STOP - 0.3% target'},
    {'target': 0.5, 'stop': None, 'name': 'NO STOP - 0.5% target'},
    {'target': 1.0, 'stop': None, 'name': 'NO STOP - 1.0% target'},
]

# Test on multiple months
months = [
    'QQQ_2021_05_1min.csv',
    'QQQ_2022_04_1min.csv',
    'QQQ_2023_06_1min.csv',
    'QQQ_2024_06_1min.csv'
]

for config in test_configs:
    print(f"\n{'='*70}")
    print(f"Testing: {config['name']}")
    print(f"{'='*70}\n")
    
    all_trades = []
    
    for month_file in months:
        data_path = Path(f'data/polygon_downloads/{month_file}')
        if not data_path.exists():
            continue
            
        provider = CSVDataProvider(str(data_path))
        df = provider.load_bars()
        
        # Detect structures
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_all_structures(df, displacement_threshold=1.0)
        
        # Find confluence signals
        signals = find_confluence_signals(df)
        
        # Backtest
        trades = backtest_ict_signals(df, signals, target_pct=config['target'], stop_pct=config['stop'])
        
        if len(trades) > 0:
            metrics = calculate_metrics(trades)
            month_name = month_file.replace('QQQ_', '').replace('_1min.csv', '')
            print(f"{month_name}: {metrics['total_trades']} trades, {metrics['win_rate']:.1f}% WR, ${metrics['total_pnl']:,.2f} P&L")
            all_trades.append(trades)
    
    # Combined results
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        metrics = calculate_metrics(combined)
        
        print(f"\n📊 COMBINED RESULTS:")
        print(f"   Total Trades: {metrics['total_trades']}")
        print(f"   Win Rate: {metrics['win_rate']:.1f}%")
        print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"   Total P&L: ${metrics['total_pnl']:,.2f}")
        print(f"   Avg Win: ${metrics['avg_win']:.2f}")
        print(f"   Avg Loss: ${metrics['avg_loss']:.2f}")

print(f"\n{'='*70}\n")
