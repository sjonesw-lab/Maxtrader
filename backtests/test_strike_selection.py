#!/usr/bin/env python3
"""
Strike Selection Backtest: ATM vs ITM vs OTM
Compares long option performance at different strike prices
Same ICT signals, same exit logic, only strike varies
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
    """Calculate ATR."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def detect_sweeps_strict(df):
    """STRICT: Exact sweep of session levels."""
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
    """Find ICT confluence signals."""
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
    """0DTE premium estimation."""
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
    """
    Backtest long options with specific strike offset.
    
    Args:
        strike_offset: 0 for ATM, -5 for ITM, +5 for OTM (for calls)
    """
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
        
        # Calculate strike based on offset
        atm_strike = round(entry_price / 5) * 5
        
        if signal['direction'] == 'long':
            # For calls: ITM = lower strike, OTM = higher strike
            strike = atm_strike + strike_offset
            target_price = entry_price + target_distance
        else:
            # For puts: ITM = higher strike, OTM = lower strike
            strike = atm_strike - strike_offset
            target_price = entry_price - target_distance
        
        premium_per_contract = estimate_option_premium(entry_price, strike, time_from_open)
        
        risk_dollars = account_balance * (risk_pct / 100)
        num_contracts = int(risk_dollars / (premium_per_contract * 100))
        num_contracts = max(1, min(num_contracts, 10))
        
        total_premium_paid = num_contracts * premium_per_contract * 100
        
        # 60-bar hold
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
            # Calculate intrinsic value
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
            'direction': signal['direction'],
            'hit_target': hit_target,
            'pnl': position_pnl,
            'balance': account_balance,
            'entry_premium': premium_per_contract,
            'strike': strike,
            'entry_price': entry_price
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades), account_balance


def analyze_performance(trades_df, label, starting_capital=25000):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return {
            'label': label,
            'trades': 0,
            'win_rate': 0,
            'return_pct': 0,
            'max_dd_pct': 0,
            'profit_factor': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'avg_premium': 0
        }
    
    equity = trades_df['balance'].values
    running_max = np.maximum.accumulate(equity)
    drawdown = equity - running_max
    max_dd = drawdown.min()
    max_dd_pct = (max_dd / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    
    total_return = equity[-1] - starting_capital
    return_pct = (total_return / starting_capital) * 100
    
    profit_factor = 0
    if len(losers) > 0 and losers['pnl'].sum() != 0:
        profit_factor = abs(winners['pnl'].sum() / losers['pnl'].sum())
    
    return {
        'label': label,
        'trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df) * 100) if len(trades_df) > 0 else 0,
        'return_pct': return_pct,
        'max_dd_pct': max_dd_pct,
        'profit_factor': profit_factor,
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
        'avg_premium': trades_df['entry_premium'].mean() if 'entry_premium' in trades_df else 0
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("STRIKE SELECTION BACKTEST - 3 MONTHS")
print("="*80)
print("Comparing: ATM vs 1 Strike ITM vs 1 Strike OTM")
print("Same signals, same logic, only strike price varies")
print("="*80)

months = [
    ('2025', '08', 'August'),
    ('2025', '09', 'September'),
    ('2025', '10', 'October')
]

all_data = []
for year, month, name in months:
    path = Path(f'data/polygon_downloads/QQQ_{year}_{month}_1min.csv')
    if path.exists():
        provider = CSVDataProvider(str(path))
        df = provider.load_bars()
        all_data.append(df)
        print(f"✓ Loaded {name} 2025: {len(df)} bars")

if not all_data:
    print("\n❌ No data found!")
    sys.exit(1)

df_all = pd.concat(all_data, ignore_index=True)
print(f"\n✅ Total: {len(df_all)} bars across 3 months")

# Prepare data
df_all = calculate_atr(df_all, period=14)
df_all = label_sessions(df_all)
df_all = add_session_highs_lows(df_all)
df_all = detect_sweeps_strict(df_all)
df_all = detect_displacement(df_all, threshold=1.0)
df_all = detect_mss(df_all)

signals = find_signals(df_all)
print(f"\n🎯 ICT Confluence Signals: {len(signals)}")

# Test ATM
print("\n" + "="*80)
print("STRIKE 1: ATM (At-The-Money)")
print("="*80)

trades_atm, final_atm = backtest_with_strike_offset(df_all, signals, strike_offset=0)
metrics_atm = analyze_performance(trades_atm, "ATM")

print(f"Total Trades:    {metrics_atm['trades']}")
print(f"Win Rate:        {metrics_atm['win_rate']:.1f}%")
print(f"3-Month Return:  {metrics_atm['return_pct']:.2f}%")
print(f"Max Drawdown:    {metrics_atm['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_atm['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_atm['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_atm['avg_loss']:.2f}")
print(f"Avg Premium:     ${metrics_atm['avg_premium']:.2f}")

# Test ITM (1 strike)
print("\n" + "="*80)
print("STRIKE 2: 1 Strike ITM (In-The-Money)")
print("="*80)

trades_itm, final_itm = backtest_with_strike_offset(df_all, signals, strike_offset=-5)
metrics_itm = analyze_performance(trades_itm, "ITM -$5")

print(f"Total Trades:    {metrics_itm['trades']}")
print(f"Win Rate:        {metrics_itm['win_rate']:.1f}%")
print(f"3-Month Return:  {metrics_itm['return_pct']:.2f}%")
print(f"Max Drawdown:    {metrics_itm['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_itm['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_itm['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_itm['avg_loss']:.2f}")
print(f"Avg Premium:     ${metrics_itm['avg_premium']:.2f}")

# Test OTM (1 strike)
print("\n" + "="*80)
print("STRIKE 3: 1 Strike OTM (Out-The-Money)")
print("="*80)

trades_otm, final_otm = backtest_with_strike_offset(df_all, signals, strike_offset=5)
metrics_otm = analyze_performance(trades_otm, "OTM +$5")

print(f"Total Trades:    {metrics_otm['trades']}")
print(f"Win Rate:        {metrics_otm['win_rate']:.1f}%")
print(f"3-Month Return:  {metrics_otm['return_pct']:.2f}%")
print(f"Max Drawdown:    {metrics_otm['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_otm['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_otm['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_otm['avg_loss']:.2f}")
print(f"Avg Premium:     ${metrics_otm['avg_premium']:.2f}")

# COMPARISON
print("\n" + "="*80)
print("COMPARISON SUMMARY")
print("="*80)
print(f"{'Metric':<20} {'ATM':<15} {'ITM -$5':<15} {'OTM +$5':<15}")
print("-"*80)
print(f"{'Trades':<20} {metrics_atm['trades']:<15} {metrics_itm['trades']:<15} {metrics_otm['trades']:<15}")
print(f"{'Win Rate %':<20} {metrics_atm['win_rate']:<15.1f} {metrics_itm['win_rate']:<15.1f} {metrics_otm['win_rate']:<15.1f}")
print(f"{'Return %':<20} {metrics_atm['return_pct']:<15.2f} {metrics_itm['return_pct']:<15.2f} {metrics_otm['return_pct']:<15.2f}")
print(f"{'Max DD %':<20} {metrics_atm['max_dd_pct']:<15.2f} {metrics_itm['max_dd_pct']:<15.2f} {metrics_otm['max_dd_pct']:<15.2f}")
print(f"{'Profit Factor':<20} {metrics_atm['profit_factor']:<15.2f} {metrics_itm['profit_factor']:<15.2f} {metrics_otm['profit_factor']:<15.2f}")
print(f"{'Avg Premium $':<20} {metrics_atm['avg_premium']:<15.2f} {metrics_itm['avg_premium']:<15.2f} {metrics_otm['avg_premium']:<15.2f}")

print("\n" + "="*80)
print("VERDICT")
print("="*80)

best_return = max(metrics_atm['return_pct'], metrics_itm['return_pct'], metrics_otm['return_pct'])

if metrics_itm['return_pct'] == best_return:
    print("✅ ITM WINS")
    print("   → Higher premium costs more, but intrinsic value provides downside protection")
    print("   → Better recovery on losers, steadier equity curve")
elif metrics_otm['return_pct'] == best_return:
    print("✅ OTM WINS")
    print("   → Cheaper premium = more contracts = bigger leverage")
    print("   → Higher risk/reward, explosive gains on winners")
else:
    print("✅ ATM WINS")
    print("   → Balanced approach: moderate premium, good delta")
    print("   → Best risk-adjusted returns")

print("="*80 + "\n")
