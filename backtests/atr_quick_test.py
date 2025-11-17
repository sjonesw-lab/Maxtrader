#!/usr/bin/env python3
"""
Quick ATR Target Analysis: Test on Representative Months
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures


def calculate_atr(df, period=14):
    """Calculate ATR for each bar."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def find_ict_confluence_signals(df):
    """Find ICT confluence signals."""
    signals = []
    
    for i in range(len(df) - 5):
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
        
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
    
    return pd.DataFrame(signals)


def backtest_atr_strategy(df_1min, signals, atr_multiple=1.5):
    """Backtest with ATR-based targets."""
    trades = []
    last_exit_time = None
    account_balance = 25000
    
    for _, signal in signals.iterrows():
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        
        atr_value = signal.get('atr', 0.5)
        target_distance = atr_multiple * atr_value
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
        else:
            target_price = entry_price - target_distance
        
        if target_distance < 0.15:
            continue
        
        exit_window = df_1min.loc[entry_idx:entry_idx + 60]
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        exit_price = None
        exit_time = None
        
        for idx, bar in exit_window.iterrows():
            if signal['direction'] == 'long':
                if bar['high'] >= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    break
            else:
                if bar['low'] <= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    break
        
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        shares = 100
        
        if signal['direction'] == 'long':
            pnl_per_share = exit_price - entry_price
        else:
            pnl_per_share = entry_price - exit_price
        
        position_pnl = pnl_per_share * shares
        account_balance += position_pnl
        
        trades.append({
            'hit_target': hit_target,
            'pnl_per_share': pnl_per_share,
            'target_distance': target_distance,
            'balance': account_balance
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_performance(trades_df):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return None
    
    final_balance = trades_df.iloc[-1]['balance']
    equity_curve = trades_df['balance'].values
    
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_drawdown = drawdown.min()
    
    winners = trades_df[trades_df['pnl_per_share'] > 0]
    
    return {
        'final_balance': final_balance,
        'return_pct': ((final_balance - 25000) / 25000) * 100,
        'max_drawdown_pct': (max_drawdown / 25000) * 100,
        'total_trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'avg_target': trades_df['target_distance'].mean(),
    }


# Test on 6 representative months (3 from each year)
test_months = [
    (2024, 3), (2024, 7), (2024, 10),
    (2025, 2), (2025, 5), (2025, 9)
]

atr_multiples = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

print("\n" + "="*80)
print("QUICK ATR ANALYSIS: 6 Representative Months")
print("="*80)
print("Months: Mar/Jul/Oct 2024, Feb/May/Sep 2025")
print("="*80)

results = []

for atr_mult in atr_multiples:
    all_trades = []
    
    for year, month in test_months:
        filename = f'QQQ_{year}_{month:02d}_1min.csv'
        data_path = Path(f'data/polygon_downloads/{filename}')
        
        if not data_path.exists():
            continue
        
        try:
            provider = CSVDataProvider(str(data_path))
            df_1min = provider.load_bars()
            
            if len(df_1min) == 0:
                continue
            
            df_1min = calculate_atr(df_1min, period=14)
            df_1min = label_sessions(df_1min)
            df_1min = add_session_highs_lows(df_1min)
            df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
            
            signals = find_ict_confluence_signals(df_1min)
            
            if len(signals) == 0:
                continue
            
            trades = backtest_atr_strategy(df_1min, signals, atr_multiple=atr_mult)
            
            if len(trades) > 0:
                all_trades.append(trades)
                
        except Exception as e:
            continue
    
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        perf = calculate_performance(combined)
        
        results.append({
            'atr_mult': atr_mult,
            'return_pct': perf['return_pct'],
            'win_rate': perf['win_rate'],
            'hit_rate': perf['hit_rate'],
            'trades': perf['total_trades'],
            'max_dd_pct': perf['max_drawdown_pct'],
            'avg_target': perf['avg_target']
        })

# Display results
print(f"\n{'ATR Mult':<10} {'Return':<12} {'Win Rate':<12} {'Hit Rate':<12} {'Trades':<10} {'Avg Target':<12}")
print("="*80)

for r in results:
    print(f"{r['atr_mult']:.1f}x      {r['return_pct']:>6.2f}%      {r['win_rate']:>6.1f}%      {r['hit_rate']:>6.1f}%      {r['trades']:<10}  ${r['avg_target']:>6.2f}")

# Find sweet spot
results_df = pd.DataFrame(results)
best_return_idx = results_df['return_pct'].idxmax()
best = results_df.loc[best_return_idx]

print("\n" + "="*80)
print("BEST PERFORMER")
print("="*80)
print(f"ATR Multiple: {best['atr_mult']:.1f}x")
print(f"Return: {best['return_pct']:.2f}%")
print(f"Win Rate: {best['win_rate']:.1f}%")
print(f"Hit Rate: {best['hit_rate']:.1f}%")
print(f"Trades: {best['trades']}")
print(f"Avg Target: ${best['avg_target']:.2f}")

print("\n" + "="*80 + "\n")
