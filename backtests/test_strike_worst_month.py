#!/usr/bin/env python3
"""
Strike Selection Stress Test: Find worst month and validate ITM advantage
Tests ATM vs ITM on individual months to find weaknesses
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_displacement, detect_mss


def calculate_atr(df, period=14):
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def detect_sweeps_strict(df):
    df = df.copy()
    df['sweep_bullish'] = False
    df['sweep_bearish'] = False
    
    for idx in df.index:
        row = df.loc[idx]
        if pd.notna(row['asia_low']) and row['low'] < row['asia_low'] and row['close'] > row['asia_low']:
            df.at[idx, 'sweep_bullish'] = True
        elif pd.notna(row['london_low']) and row['low'] < row['london_low'] and row['close'] > row['london_low']:
            df.at[idx, 'sweep_bullish'] = True
        if pd.notna(row['asia_high']) and row['high'] > row['asia_high'] and row['close'] < row['asia_high']:
            df.at[idx, 'sweep_bearish'] = True
        elif pd.notna(row['london_high']) and row['high'] > row['london_high'] and row['close'] < row['london_high']:
            df.at[idx, 'sweep_bearish'] = True
    
    return df


def find_signals(df):
    signals = []
    for i in range(len(df) - 5):
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
    return signals


def estimate_option_premium(underlying_price, strike, time_minutes_from_open=0):
    moneyness = (underlying_price - strike) / underlying_price
    
    if moneyness >= 0.01:
        base_premium = 3.0 + (moneyness * 100)
    elif moneyness >= 0.005:
        base_premium = 2.5
    elif moneyness >= -0.005:
        base_premium = 2.0
    elif moneyness >= -0.01:
        base_premium = 1.2
    elif moneyness >= -0.02:
        base_premium = 0.6
    else:
        base_premium = 0.2
    
    time_remaining_pct = max(0, (390 - time_minutes_from_open) / 390)
    time_decay = 0.3 + (0.7 * time_remaining_pct)
    vol_factor = underlying_price / 500
    premium = base_premium * time_decay * vol_factor
    
    return max(premium, 0.05)


def backtest_with_strike_offset(df, signals, strike_offset=0, starting_capital=25000, risk_pct=5.0):
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    market_open = df.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    
    for signal in signals:
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_idx = signal['index'] + 1
        if entry_idx >= len(df):
            continue
        
        entry_price = df.iloc[entry_idx]['open']
        entry_time = df.iloc[entry_idx]['timestamp']
        time_from_open = (entry_time - market_open).total_seconds() / 60
        
        atr_value = signal['atr']
        target_distance = 5.0 * atr_value
        
        if target_distance < 0.15:
            continue
        
        atm_strike = round(entry_price / 5) * 5
        
        if signal['direction'] == 'long':
            strike = atm_strike + strike_offset
            target_price = entry_price + target_distance
        else:
            strike = atm_strike - strike_offset
            target_price = entry_price - target_distance
        
        premium_per_contract = estimate_option_premium(entry_price, strike, time_from_open)
        risk_dollars = account_balance * (risk_pct / 100)
        num_contracts = max(1, min(int(risk_dollars / (premium_per_contract * 100)), 10))
        total_premium_paid = num_contracts * premium_per_contract * 100
        
        exit_window_end = min(entry_idx + 60, len(df) - 1)
        exit_window = df.iloc[entry_idx:exit_window_end+1]
        
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        exit_price = None
        exit_time = None
        
        for idx in range(len(exit_window)):
            bar = exit_window.iloc[idx]
            if signal['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                exit_price = target_price
                exit_time = bar['timestamp']
                break
            elif signal['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                exit_price = target_price
                exit_time = bar['timestamp']
                break
        
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        time_at_exit = (exit_time - market_open).total_seconds() / 60
        
        if hit_target:
            if signal['direction'] == 'long':
                intrinsic = max(0, exit_price - strike) * 100
            else:
                intrinsic = max(0, strike - exit_price) * 100
            option_value_at_exit = intrinsic * num_contracts
        else:
            exit_premium = estimate_option_premium(exit_price, strike, time_at_exit)
            option_value_at_exit = exit_premium * 100 * num_contracts
        
        position_pnl = option_value_at_exit - total_premium_paid
        account_balance += position_pnl
        
        trades.append({
            'pnl': position_pnl,
            'balance': account_balance,
            'hit_target': hit_target
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades), account_balance


def analyze_performance(trades_df, starting_capital=25000):
    if len(trades_df) == 0:
        return {'trades': 0, 'win_rate': 0, 'return_pct': 0, 'max_dd_pct': 0}
    
    equity = trades_df['balance'].values
    running_max = np.maximum.accumulate(equity)
    drawdown = equity - running_max
    max_dd_pct = (drawdown.min() / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl'] > 0]
    total_return = equity[-1] - starting_capital
    return_pct = (total_return / starting_capital) * 100
    
    return {
        'trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df) * 100) if len(trades_df) > 0 else 0,
        'return_pct': return_pct,
        'max_dd_pct': max_dd_pct
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("STRIKE STRESS TEST - INDIVIDUAL MONTHS")
print("="*80)

months = [
    ('2025', '08', 'August'),
    ('2025', '09', 'September'),
    ('2025', '10', 'October')
]

results = []

for year, month, name in months:
    path = Path(f'data/polygon_downloads/QQQ_{year}_{month}_1min.csv')
    if not path.exists():
        continue
    
    provider = CSVDataProvider(str(path))
    df = provider.load_bars()
    
    df = calculate_atr(df, period=14)
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_sweeps_strict(df)
    df = detect_displacement(df, threshold=1.0)
    df = detect_mss(df)
    
    signals = find_signals(df)
    
    print(f"\n{'='*80}")
    print(f"{name} 2025 - {len(signals)} signals")
    print(f"{'='*80}")
    
    # Test ATM
    trades_atm, final_atm = backtest_with_strike_offset(df, signals, strike_offset=0)
    metrics_atm = analyze_performance(trades_atm)
    
    # Test ITM
    trades_itm, final_itm = backtest_with_strike_offset(df, signals, strike_offset=-5)
    metrics_itm = analyze_performance(trades_itm)
    
    print(f"\nATM:")
    print(f"  Trades: {metrics_atm['trades']}, Win Rate: {metrics_atm['win_rate']:.1f}%")
    print(f"  Return: {metrics_atm['return_pct']:.2f}%, Max DD: {metrics_atm['max_dd_pct']:.2f}%")
    
    print(f"\nITM -$5:")
    print(f"  Trades: {metrics_itm['trades']}, Win Rate: {metrics_itm['win_rate']:.1f}%")
    print(f"  Return: {metrics_itm['return_pct']:.2f}%, Max DD: {metrics_itm['max_dd_pct']:.2f}%")
    
    delta_return = metrics_itm['return_pct'] - metrics_atm['return_pct']
    print(f"\nΔ Return: {delta_return:+.2f}% (ITM vs ATM)")
    
    results.append({
        'month': name,
        'atm_return': metrics_atm['return_pct'],
        'itm_return': metrics_itm['return_pct'],
        'delta': delta_return,
        'atm_trades': metrics_atm['trades'],
        'itm_trades': metrics_itm['trades']
    })

# Find worst performing month
print("\n" + "="*80)
print("SUMMARY: WORST MONTH ANALYSIS")
print("="*80)

worst_atm = min(results, key=lambda x: x['atm_return'])
worst_itm = min(results, key=lambda x: x['itm_return'])

print(f"\nWorst ATM Month: {worst_atm['month']}")
print(f"  ATM Return: {worst_atm['atm_return']:.2f}%")
print(f"  ITM Return: {worst_atm['itm_return']:.2f}%")
print(f"  ITM Advantage: {worst_atm['delta']:+.2f}%")

print(f"\nWorst ITM Month: {worst_itm['month']}")
print(f"  ATM Return: {worst_itm['atm_return']:.2f}%")
print(f"  ITM Return: {worst_itm['itm_return']:.2f}%")
print(f"  ITM Advantage: {worst_itm['delta']:+.2f}%")

print("\n" + "="*80)
print("VERDICT")
print("="*80)

all_itm_better = all(r['delta'] > 0 for r in results)

if all_itm_better:
    print("✅ ITM DOMINATES IN ALL MONTHS")
    print("   → Even in worst conditions, ITM outperforms ATM")
    print("   → Pattern is consistent and reliable")
else:
    losing_months = [r['month'] for r in results if r['delta'] < 0]
    print(f"⚠️  ITM LOST IN: {', '.join(losing_months)}")
    print("   → Results may be period-dependent")
    print("   → More testing needed")

print("="*80 + "\n")
