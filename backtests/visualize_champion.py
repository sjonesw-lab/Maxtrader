#!/usr/bin/env python3
"""
Quick visualization of champion strategy equity curve
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
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def estimate_premium(price, strike, time_mins=0):
    moneyness = (price - strike) / price
    if moneyness >= 0.01:
        base = 3.0 + (moneyness * 100)
    elif moneyness >= 0.005:
        base = 2.5
    elif moneyness >= -0.005:
        base = 2.0
    elif moneyness >= -0.01:
        base = 1.2
    elif moneyness >= -0.02:
        base = 0.6
    else:
        base = 0.2
    
    time_decay = 0.3 + (0.7 * max(0, (390 - time_mins) / 390))
    vol_factor = price / 500
    return max(base * time_decay * vol_factor, 0.05)


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


def backtest(df, signals, capital=25000):
    trades = []
    balance = capital
    market_open = df.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    last_exit = None
    
    for _, sig in signals.iterrows():
        if last_exit and sig['timestamp'] <= last_exit:
            continue
        
        entry_mask = df['timestamp'] > sig['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df[entry_mask].index[0]
        entry_bar = df.loc[entry_idx]
        entry_price = entry_bar['open']
        entry_time = entry_bar['timestamp']
        time_from_open = (entry_time - market_open).total_seconds() / 60
        
        target_dist = 5.0 * sig.get('atr', 0.5)
        if target_dist < 0.15:
            continue
        
        target_price = entry_price + target_dist if sig['direction'] == 'long' else entry_price - target_dist
        strike = round(entry_price / 5) * 5
        
        premium = estimate_premium(entry_price, strike, time_from_open)
        num_contracts = max(1, min(10, int((balance * 0.05) / (premium * 100))))
        total_premium = num_contracts * premium * 100
        
        exit_window = df.loc[entry_idx:entry_idx + 60]
        hit_target = False
        exit_price = None
        exit_time = None
        
        for idx, bar in exit_window.iterrows():
            if sig['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                exit_price = target_price
                exit_time = bar['timestamp']
                break
            elif sig['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                exit_price = target_price
                exit_time = bar['timestamp']
                break
        
        if not exit_price:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        time_at_exit = (exit_time - market_open).total_seconds() / 60
        
        if hit_target:
            option_value = target_dist * 100 * num_contracts
        else:
            exit_prem = estimate_premium(exit_price, strike, time_at_exit)
            option_value = exit_prem * 100 * num_contracts
        
        pnl = option_value - total_premium
        balance += pnl
        
        trades.append({
            'date': entry_time.date(),
            'pnl': pnl,
            'balance': balance,
            'hit_target': hit_target
        })
        
        last_exit = exit_time
    
    return pd.DataFrame(trades)


print("\n" + "="*80)
print("CHAMPION STRATEGY EQUITY CURVE")
print("="*80)

for year in ['2024', '2025']:
    all_data = []
    months = range(1, 13) if year == '2024' else range(1, 12)
    
    for month in months:
        path = Path(f'data/polygon_downloads/QQQ_{year}_{month:02d}_1min.csv')
        if path.exists():
            try:
                df = CSVDataProvider(str(path)).load_bars()
                if len(df) > 0:
                    all_data.append(df)
            except:
                pass
    
    if all_data:
        df = pd.concat(all_data, ignore_index=True)
        df = calculate_atr(df, 14)
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_all_structures(df, 1.0)
        
        signals = find_signals(df)
        trades = backtest(df, signals)
        
        print(f"\n{year} EQUITY CURVE:")
        print(f"  Start: $25,000")
        
        monthly_balances = trades.groupby(trades['date'].apply(lambda x: x.strftime('%Y-%m'))).last()
        
        for month_str, row in monthly_balances.iterrows():
            month_pnl = trades[trades['date'].apply(lambda x: x.strftime('%Y-%m')) == month_str]['pnl'].sum()
            print(f"  {month_str}: ${row['balance']:>10,.2f} ({month_pnl:>+8,.2f})")
        
        final = trades.iloc[-1]['balance']
        total_return = ((final - 25000) / 25000) * 100
        winners = len(trades[trades['pnl'] > 0])
        
        print(f"\n  Final: ${final:,.2f} ({total_return:+.2f}%)")
        print(f"  Trades: {len(trades)} | Win Rate: {winners/len(trades)*100:.1f}%")

print("\n" + "="*80 + "\n")
