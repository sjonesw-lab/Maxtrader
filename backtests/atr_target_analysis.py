#!/usr/bin/env python3
"""
ATR Target Analysis: Test Multiple ATR Multiples
Testing 1.5x, 2.0x, 2.5x, 3.0x ATR targets across 2024 & 2025
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.timeframes import resample_to_timeframe


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
    """
    Backtest with ATR-based targets.
    
    Args:
        df_1min: 1-minute bars
        signals: ICT confluence signals
        atr_multiple: ATR multiplier for targets (1.5 = 1.5x ATR)
    """
    trades = []
    last_exit_time = None
    account_balance = 25000
    
    for _, signal in signals.iterrows():
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Entry
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        
        # Calculate ATR target
        atr_value = signal.get('atr', 0.5)
        target_distance = atr_multiple * atr_value
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
        else:
            target_price = entry_price - target_distance
        
        # Minimum target filter
        if target_distance < 0.15:
            continue
        
        # Exit logic (60-minute hold max)
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
        
        # Fixed position size (100 shares)
        shares = 100
        
        # Calculate P&L
        if signal['direction'] == 'long':
            pnl_per_share = exit_price - entry_price
        else:
            pnl_per_share = entry_price - exit_price
        
        position_pnl = pnl_per_share * shares
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'pnl_per_share': pnl_per_share,
            'target_distance': target_distance,
            'balance': account_balance
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_performance(trades_df, starting_capital=25000):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return None
    
    final_balance = trades_df.iloc[-1]['balance']
    equity_curve = trades_df['balance'].values
    
    # Max drawdown
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_drawdown = drawdown.min()
    max_drawdown_pct = (max_drawdown / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl_per_share'] > 0]
    
    # Average target distance
    avg_target = trades_df['target_distance'].mean()
    
    return {
        'final_balance': final_balance,
        'total_return': final_balance - starting_capital,
        'return_pct': ((final_balance - starting_capital) / starting_capital) * 100,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'total_trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'avg_target_distance': avg_target,
    }


# ============================================================================
# TEST ATR MULTIPLES ON 2024 & 2025
# ============================================================================

print("\n" + "="*80)
print("ATR TARGET ANALYSIS: 2024 & 2025 Full Dataset")
print("="*80)
print("Testing ATR multiples: 1.5x, 2.0x, 2.5x, 3.0x, 3.5x")
print("Fixed position size: 100 shares | Max hold: 60 minutes")
print("="*80)

atr_multiples = [1.5, 2.0, 2.5, 3.0, 3.5]

test_periods = [
    ('2024', list(range(1, 13))),
    ('2025', list(range(1, 12))),
]

results_summary = []

for atr_mult in atr_multiples:
    print(f"\n{'='*80}")
    print(f"TESTING: {atr_mult}x ATR")
    print(f"{'='*80}")
    
    for year_label, months in test_periods:
        all_trades = []
        
        for month in months:
            filename = f'QQQ_{year_label}_{month:02d}_1min.csv'
            data_path = Path(f'data/polygon_downloads/{filename}')
            
            if not data_path.exists():
                continue
            
            try:
                provider = CSVDataProvider(str(data_path))
                df_1min = provider.load_bars()
                
                if len(df_1min) == 0:
                    continue
                
                # Calculate ATR
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
            combined_trades = pd.concat(all_trades, ignore_index=True)
            perf = calculate_performance(combined_trades)
            
            print(f"\n{year_label} Results ({atr_mult}x ATR):")
            print(f"  Final Balance: ${perf['final_balance']:,.2f}")
            print(f"  Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
            print(f"  Max DD: ${perf['max_drawdown']:,.2f} ({perf['max_drawdown_pct']:.2f}%)")
            print(f"  Trades: {perf['total_trades']}")
            print(f"  Win Rate: {perf['win_rate']:.1f}%")
            print(f"  Hit Rate: {perf['target_hit_rate']:.1f}%")
            print(f"  Avg Target: ${perf['avg_target_distance']:.2f}")
            
            results_summary.append({
                'atr_multiple': atr_mult,
                'year': year_label,
                'return_pct': perf['return_pct'],
                'win_rate': perf['win_rate'],
                'hit_rate': perf['target_hit_rate'],
                'trades': perf['total_trades'],
                'max_dd_pct': perf['max_drawdown_pct'],
                'avg_target': perf['avg_target_distance']
            })

# ============================================================================
# SUMMARY TABLE
# ============================================================================

print("\n" + "="*80)
print("SUMMARY: ATR MULTIPLES COMPARISON")
print("="*80)

summary_df = pd.DataFrame(results_summary)

for atr_mult in atr_multiples:
    subset = summary_df[summary_df['atr_multiple'] == atr_mult]
    
    if len(subset) > 0:
        avg_return = subset['return_pct'].mean()
        avg_win_rate = subset['win_rate'].mean()
        avg_hit_rate = subset['hit_rate'].mean()
        total_trades = subset['trades'].sum()
        avg_target = subset['avg_target'].mean()
        
        print(f"\n{atr_mult}x ATR:")
        print(f"  Avg Return: {avg_return:.2f}%")
        print(f"  Avg Win Rate: {avg_win_rate:.1f}%")
        print(f"  Avg Hit Rate: {avg_hit_rate:.1f}%")
        print(f"  Total Trades: {total_trades}")
        print(f"  Avg Target Distance: ${avg_target:.2f}")

print("\n" + "="*80)
print("RECOMMENDATION")
print("="*80)

# Find best performing multiple
best = summary_df.groupby('atr_multiple')['return_pct'].mean().idxmax()
best_return = summary_df.groupby('atr_multiple')['return_pct'].mean().max()
best_hit_rate = summary_df[summary_df['atr_multiple'] == best]['hit_rate'].mean()

print(f"\nBest ATR Multiple: {best}x")
print(f"  Average Return: {best_return:.2f}%")
print(f"  Average Hit Rate: {best_hit_rate:.1f}%")

print("\n" + "="*80 + "\n")
