#!/usr/bin/env python3
"""
Comprehensive Backtest: All of 2024 + 2025 YTD
Tests ITM vs ATM with separate and compounded results
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
            'timestamp': signal['timestamp'],
            'pnl': position_pnl,
            'balance': account_balance,
            'hit_target': hit_target
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades), account_balance


def analyze_performance(trades_df, starting_capital=25000):
    if len(trades_df) == 0:
        return {'trades': 0, 'win_rate': 0, 'return_pct': 0, 'max_dd_pct': 0, 'final_balance': starting_capital}
    
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
        'max_dd_pct': max_dd_pct,
        'final_balance': equity[-1]
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("COMPREHENSIVE BACKTEST: 2024 + 2025 YTD")
print("="*80)
print("ITM vs ATM Long Options (1 strike ITM vs At-The-Money)")
print("="*80)

# Define all available months
all_months = []
data_dir = Path('data/polygon_downloads')

if data_dir.exists():
    for file in sorted(data_dir.glob('QQQ_*_*_1min.csv')):
        parts = file.stem.split('_')
        if len(parts) >= 3:
            year = parts[1]
            month = parts[2]
            all_months.append((year, month, file))

print(f"\n📁 Found {len(all_months)} months of data")

# Separate 2024 and 2025
months_2024 = [(y, m, f) for y, m, f in all_months if y == '2024']
months_2025 = [(y, m, f) for y, m, f in all_months if y == '2025']

print(f"   2024: {len(months_2024)} months")
print(f"   2025: {len(months_2025)} months")

# ============================================================================
# TEST 2024 SEPARATELY
# ============================================================================

if months_2024:
    print("\n" + "="*80)
    print("2024 BACKTEST")
    print("="*80)
    
    data_2024 = []
    for year, month, file in months_2024:
        provider = CSVDataProvider(str(file))
        df = provider.load_bars()
        data_2024.append(df)
        print(f"✓ Loaded {year}-{month}: {len(df)} bars")
    
    df_2024 = pd.concat(data_2024, ignore_index=True)
    df_2024 = calculate_atr(df_2024, period=14)
    df_2024 = label_sessions(df_2024)
    df_2024 = add_session_highs_lows(df_2024)
    df_2024 = detect_sweeps_strict(df_2024)
    df_2024 = detect_displacement(df_2024, threshold=1.0)
    df_2024 = detect_mss(df_2024)
    
    signals_2024 = find_signals(df_2024)
    print(f"\n🎯 Total Signals: {len(signals_2024)}")
    
    # ATM
    trades_atm_2024, final_atm_2024 = backtest_with_strike_offset(df_2024, signals_2024, strike_offset=0)
    metrics_atm_2024 = analyze_performance(trades_atm_2024)
    
    # ITM
    trades_itm_2024, final_itm_2024 = backtest_with_strike_offset(df_2024, signals_2024, strike_offset=-5)
    metrics_itm_2024 = analyze_performance(trades_itm_2024)
    
    print(f"\n📊 ATM Results:")
    print(f"   Trades: {metrics_atm_2024['trades']}, Win Rate: {metrics_atm_2024['win_rate']:.1f}%")
    print(f"   Return: {metrics_atm_2024['return_pct']:.2f}%, Max DD: {metrics_atm_2024['max_dd_pct']:.2f}%")
    print(f"   Final Balance: ${metrics_atm_2024['final_balance']:,.2f}")
    
    print(f"\n📊 ITM Results:")
    print(f"   Trades: {metrics_itm_2024['trades']}, Win Rate: {metrics_itm_2024['win_rate']:.1f}%")
    print(f"   Return: {metrics_itm_2024['return_pct']:.2f}%, Max DD: {metrics_itm_2024['max_dd_pct']:.2f}%")
    print(f"   Final Balance: ${metrics_itm_2024['final_balance']:,.2f}")

# ============================================================================
# TEST 2025 SEPARATELY
# ============================================================================

if months_2025:
    print("\n" + "="*80)
    print("2025 YTD BACKTEST")
    print("="*80)
    
    data_2025 = []
    for year, month, file in months_2025:
        provider = CSVDataProvider(str(file))
        df = provider.load_bars()
        data_2025.append(df)
        print(f"✓ Loaded {year}-{month}: {len(df)} bars")
    
    df_2025 = pd.concat(data_2025, ignore_index=True)
    df_2025 = calculate_atr(df_2025, period=14)
    df_2025 = label_sessions(df_2025)
    df_2025 = add_session_highs_lows(df_2025)
    df_2025 = detect_sweeps_strict(df_2025)
    df_2025 = detect_displacement(df_2025, threshold=1.0)
    df_2025 = detect_mss(df_2025)
    
    signals_2025 = find_signals(df_2025)
    print(f"\n🎯 Total Signals: {len(signals_2025)}")
    
    # ATM
    trades_atm_2025, final_atm_2025 = backtest_with_strike_offset(df_2025, signals_2025, strike_offset=0)
    metrics_atm_2025 = analyze_performance(trades_atm_2025)
    
    # ITM
    trades_itm_2025, final_itm_2025 = backtest_with_strike_offset(df_2025, signals_2025, strike_offset=-5)
    metrics_itm_2025 = analyze_performance(trades_itm_2025)
    
    print(f"\n📊 ATM Results:")
    print(f"   Trades: {metrics_atm_2025['trades']}, Win Rate: {metrics_atm_2025['win_rate']:.1f}%")
    print(f"   Return: {metrics_atm_2025['return_pct']:.2f}%, Max DD: {metrics_atm_2025['max_dd_pct']:.2f}%")
    print(f"   Final Balance: ${metrics_atm_2025['final_balance']:,.2f}")
    
    print(f"\n📊 ITM Results:")
    print(f"   Trades: {metrics_itm_2025['trades']}, Win Rate: {metrics_itm_2025['win_rate']:.1f}%")
    print(f"   Return: {metrics_itm_2025['return_pct']:.2f}%, Max DD: {metrics_itm_2025['max_dd_pct']:.2f}%")
    print(f"   Final Balance: ${metrics_itm_2025['final_balance']:,.2f}")

# ============================================================================
# COMPOUNDED RESULTS
# ============================================================================

print("\n" + "="*80)
print("COMPOUNDED RESULTS (2024 → 2025)")
print("="*80)

if months_2024 and months_2025:
    # ATM Compounded
    atm_2024_ending = metrics_atm_2024['final_balance']
    trades_atm_2025_comp, final_atm_comp = backtest_with_strike_offset(
        df_2025, signals_2025, strike_offset=0, starting_capital=atm_2024_ending
    )
    total_atm_return = ((final_atm_comp - 25000) / 25000) * 100
    
    # ITM Compounded
    itm_2024_ending = metrics_itm_2024['final_balance']
    trades_itm_2025_comp, final_itm_comp = backtest_with_strike_offset(
        df_2025, signals_2025, strike_offset=-5, starting_capital=itm_2024_ending
    )
    total_itm_return = ((final_itm_comp - 25000) / 25000) * 100
    
    print(f"\n💰 ATM Compounded:")
    print(f"   Start (Jan 2024): $25,000")
    print(f"   End 2024: ${atm_2024_ending:,.2f}")
    print(f"   End 2025 YTD: ${final_atm_comp:,.2f}")
    print(f"   Total Return: {total_atm_return:.2f}%")
    
    print(f"\n💰 ITM Compounded:")
    print(f"   Start (Jan 2024): $25,000")
    print(f"   End 2024: ${itm_2024_ending:,.2f}")
    print(f"   End 2025 YTD: ${final_itm_comp:,.2f}")
    print(f"   Total Return: {total_itm_return:.2f}%")
    
    print(f"\n🏆 ITM Advantage: {total_itm_return - total_atm_return:+.2f}% better")

print("\n" + "="*80)
print("SUMMARY TABLE")
print("="*80)
print(f"{'Period':<15} {'Strategy':<10} {'Return %':<12} {'Win Rate %':<12} {'Max DD %':<10}")
print("-"*80)

if months_2024:
    print(f"{'2024':<15} {'ATM':<10} {metrics_atm_2024['return_pct']:<12.2f} {metrics_atm_2024['win_rate']:<12.1f} {metrics_atm_2024['max_dd_pct']:<10.2f}")
    print(f"{'2024':<15} {'ITM':<10} {metrics_itm_2024['return_pct']:<12.2f} {metrics_itm_2024['win_rate']:<12.1f} {metrics_itm_2024['max_dd_pct']:<10.2f}")

if months_2025:
    print(f"{'2025 YTD':<15} {'ATM':<10} {metrics_atm_2025['return_pct']:<12.2f} {metrics_atm_2025['win_rate']:<12.1f} {metrics_atm_2025['max_dd_pct']:<10.2f}")
    print(f"{'2025 YTD':<15} {'ITM':<10} {metrics_itm_2025['return_pct']:<12.2f} {metrics_itm_2025['win_rate']:<12.1f} {metrics_itm_2025['max_dd_pct']:<10.2f}")

if months_2024 and months_2025:
    print(f"{'COMPOUNDED':<15} {'ATM':<10} {total_atm_return:<12.2f} {'-':<12} {'-':<10}")
    print(f"{'COMPOUNDED':<15} {'ITM':<10} {total_itm_return:<12.2f} {'-':<12} {'-':<10}")

print("="*80 + "\n")
