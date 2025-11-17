#!/usr/bin/env python3
"""ATR Analysis on Single Month"""

import sys
sys.path.insert(0, '.')
import pandas as pd
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

def calculate_atr(df, period=14):
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df

def find_signals(df):
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

def backtest_atr(df, signals, atr_mult):
    balance = 25000
    trades = []
    last_exit = None
    
    for _, sig in signals.iterrows():
        if last_exit and sig['timestamp'] <= last_exit:
            continue
        
        entry_mask = df['timestamp'] > sig['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df[entry_mask].index[0]
        entry_price = df.loc[entry_idx, 'open']
        
        target_dist = atr_mult * sig['atr']
        if target_dist < 0.15:
            continue
        
        if sig['direction'] == 'long':
            target_price = entry_price + target_dist
        else:
            target_price = entry_price - target_dist
        
        exit_window = df.loc[entry_idx:entry_idx + 60]
        hit = False
        exit_price = None
        
        for idx, bar in exit_window.iterrows():
            if sig['direction'] == 'long' and bar['high'] >= target_price:
                hit = True
                exit_price = target_price
                break
            elif sig['direction'] == 'short' and bar['low'] <= target_price:
                hit = True
                exit_price = target_price
                break
        
        if not exit_price:
            exit_price = exit_window.iloc[-1]['close']
        
        if sig['direction'] == 'long':
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
            
        balance += pnl * 100
        
        trades.append({'hit': hit, 'pnl': pnl, 'balance': balance})
        last_exit = exit_window.iloc[-1]['timestamp']
    
    if not trades:
        return None
    
    trades_df = pd.DataFrame(trades)
    return_pct = ((balance - 25000) / 25000) * 100
    win_rate = (trades_df[trades_df['pnl'] > 0].shape[0] / len(trades_df)) * 100
    hit_rate = (trades_df['hit'].sum() / len(trades_df)) * 100
    
    return {
        'return': return_pct,
        'win_rate': win_rate,
        'hit_rate': hit_rate,
        'trades': len(trades_df)
    }

# Load Oct 2024
provider = CSVDataProvider('data/polygon_downloads/QQQ_2024_10_1min.csv')
df = provider.load_bars()
df = calculate_atr(df, 14)
df = label_sessions(df)
df = add_session_highs_lows(df)
df = detect_all_structures(df, displacement_threshold=1.0)
signals = find_signals(df)

print("\nATR Target Analysis - October 2024")
print("="*70)
print("ATR Mult | Return   | Win Rate | Hit Rate | Trades")
print("="*70)

for mult in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
    result = backtest_atr(df, signals, mult)
    if result:
        print(f"{mult:.1f}x      | {result['return']:>6.2f}% | {result['win_rate']:>6.1f}%  | {result['hit_rate']:>6.1f}%  | {result['trades']:>6}")

print("="*70 + "\n")
