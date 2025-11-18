#!/usr/bin/env python3
"""
Comprehensive Option Structure Backtest
Tests: Long Options, Debit Spreads, Balanced Flies (1:-2:+1), Unbalanced Flies (1:-3:+2)
Variants: ATM vs One Strike Away
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


# ============================================================================
# STRUCTURE CONSTRUCTORS
# ============================================================================

def construct_debit_spread(underlying_price, direction, atm_offset=0):
    """
    Debit Spread: Buy ATM (or ATM+offset), Sell ATM+$5 away
    
    Returns: (net_debit, max_profit, strikes)
    """
    atm_strike = round(underlying_price / 5) * 5
    
    if direction == 'long':
        long_strike = atm_strike + atm_offset
        short_strike = long_strike + 5
        
        long_prem = 2.5 if atm_offset == 0 else 2.0
        short_prem = 1.0 if atm_offset == 0 else 0.8
        
        net_debit = long_prem - short_prem
        max_profit = 5.0 - net_debit
        
        return {
            'net_debit': net_debit,
            'max_profit': max_profit,
            'long_strike': long_strike,
            'short_strike': short_strike,
            'direction': 'call'
        }
    else:
        long_strike = atm_strike - atm_offset
        short_strike = long_strike - 5
        
        long_prem = 2.5 if atm_offset == 0 else 2.0
        short_prem = 1.0 if atm_offset == 0 else 0.8
        
        net_debit = long_prem - short_prem
        max_profit = 5.0 - net_debit
        
        return {
            'net_debit': net_debit,
            'max_profit': max_profit,
            'long_strike': long_strike,
            'short_strike': short_strike,
            'direction': 'put'
        }


def construct_balanced_butterfly(underlying_price, direction, atm_offset=0, wing_width=5.0):
    """
    Balanced Butterfly 1:-2:+1
    
    For calls (bullish):
    - Buy 1x lower strike
    - Sell 2x middle strike
    - Buy 1x upper strike
    
    Returns: (net_debit, max_profit, strikes)
    """
    atm_strike = round(underlying_price / 5) * 5
    
    if direction == 'long':
        K_low = atm_strike + atm_offset
        K_mid = K_low + wing_width
        K_high = K_mid + wing_width
        
        prem_low = 2.5 if atm_offset == 0 else 2.0
        prem_mid = 1.0 if atm_offset == 0 else 0.8
        prem_high = 0.3 if atm_offset == 0 else 0.2
        
        net_debit = prem_low - (2 * prem_mid) + prem_high
        max_profit = wing_width - net_debit
        
        return {
            'net_debit': net_debit,
            'max_profit': max_profit,
            'K_low': K_low,
            'K_mid': K_mid,
            'K_high': K_high,
            'wing_width': wing_width,
            'direction': 'call'
        }
    else:
        K_high = atm_strike - atm_offset
        K_mid = K_high - wing_width
        K_low = K_mid - wing_width
        
        prem_high = 2.5 if atm_offset == 0 else 2.0
        prem_mid = 1.0 if atm_offset == 0 else 0.8
        prem_low = 0.3 if atm_offset == 0 else 0.2
        
        net_debit = prem_high - (2 * prem_mid) + prem_low
        max_profit = wing_width - net_debit
        
        return {
            'net_debit': net_debit,
            'max_profit': max_profit,
            'K_low': K_low,
            'K_mid': K_mid,
            'K_high': K_high,
            'wing_width': wing_width,
            'direction': 'put'
        }


# ============================================================================
# BACKTEST ENGINES
# ============================================================================

def backtest_long_options(df, signals, starting_capital=25000, risk_pct=5.0):
    """Long Options (baseline)."""
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
        
        target_price = entry_price + target_distance if signal['direction'] == 'long' else entry_price - target_distance
        strike = round(entry_price / 5) * 5
        
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
            intrinsic_value = target_distance * 100
            option_value_at_exit = intrinsic_value * num_contracts
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


def backtest_debit_spread(df, signals, atm_offset=0, starting_capital=25000, risk_pct=5.0):
    """Debit Spread backtest."""
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    for signal in signals:
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_idx = signal['index'] + 1
        if entry_idx >= len(df):
            continue
        
        entry_price = df.iloc[entry_idx]['open']
        atr_value = signal['atr']
        target_distance = 5.0 * atr_value
        
        if target_distance < 0.15:
            continue
        
        target_price = entry_price + target_distance if signal['direction'] == 'long' else entry_price - target_distance
        
        spread = construct_debit_spread(entry_price, signal['direction'], atm_offset)
        
        risk_dollars = account_balance * (risk_pct / 100)
        num_spreads = max(1, int(risk_dollars / (spread['net_debit'] * 100)))
        num_spreads = min(num_spreads, 10)
        total_debit = num_spreads * spread['net_debit'] * 100
        
        exit_window_end = min(entry_idx + 60, len(df) - 1)
        exit_window = df.iloc[entry_idx:exit_window_end+1]
        
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        for idx in range(len(exit_window)):
            bar = exit_window.iloc[idx]
            if signal['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                break
            elif signal['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                break
        
        # Simplified P&L: Max profit if target hit, else lose debit
        if hit_target:
            position_pnl = spread['max_profit'] * 100 * num_spreads
        else:
            position_pnl = -total_debit * 0.7  # Partial recovery
        
        account_balance += position_pnl
        
        trades.append({
            'timestamp': signal['timestamp'],
            'pnl': position_pnl,
            'balance': account_balance,
            'hit_target': hit_target
        })
        
        last_exit_time = exit_window.iloc[-1]['timestamp']
    
    return pd.DataFrame(trades), account_balance


def backtest_balanced_fly(df, signals, atm_offset=0, starting_capital=25000, risk_pct=5.0):
    """Balanced Butterfly 1:-2:+1 backtest."""
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    for signal in signals:
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_idx = signal['index'] + 1
        if entry_idx >= len(df):
            continue
        
        entry_price = df.iloc[entry_idx]['open']
        atr_value = signal['atr']
        target_distance = 5.0 * atr_value
        
        if target_distance < 0.15:
            continue
        
        target_price = entry_price + target_distance if signal['direction'] == 'long' else entry_price - target_distance
        
        fly = construct_balanced_butterfly(entry_price, signal['direction'], atm_offset, wing_width=5.0)
        
        risk_dollars = account_balance * (risk_pct / 100)
        num_flies = max(1, int(risk_dollars / (abs(fly['net_debit']) * 100)))
        num_flies = min(num_flies, 5)
        total_debit = num_flies * abs(fly['net_debit']) * 100
        
        exit_window_end = min(entry_idx + 60, len(df) - 1)
        exit_window = df.iloc[entry_idx:exit_window_end+1]
        
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        final_price = exit_window.iloc[-1]['close']
        
        for idx in range(len(exit_window)):
            bar = exit_window.iloc[idx]
            if signal['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                final_price = bar['close']
                break
            elif signal['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                final_price = bar['close']
                break
        
        # Simplified P&L: Near body = max profit, wings = loss
        K_mid = fly['K_mid']
        distance_to_mid = abs(final_price - K_mid)
        
        if distance_to_mid < 2.0:  # Near body
            position_pnl = fly['max_profit'] * 100 * num_flies * 0.7
        elif distance_to_mid < 5.0:  # Wing zone
            position_pnl = -total_debit * 0.3
        else:  # Far from body
            position_pnl = -total_debit
        
        account_balance += position_pnl
        
        trades.append({
            'timestamp': signal['timestamp'],
            'pnl': position_pnl,
            'balance': account_balance,
            'hit_target': hit_target
        })
        
        last_exit_time = exit_window.iloc[-1]['timestamp']
    
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
            'profit_factor': 0
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
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("COMPREHENSIVE OPTION STRUCTURE BACKTEST - 3 MONTHS")
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

df_all = pd.concat(all_data, ignore_index=True)
df_all = calculate_atr(df_all, period=14)
df_all = label_sessions(df_all)
df_all = add_session_highs_lows(df_all)
df_all = detect_sweeps_strict(df_all)
df_all = detect_displacement(df_all, threshold=1.0)
df_all = detect_mss(df_all)

signals = find_signals(df_all)
print(f"🎯 ICT Confluence Signals: {len(signals)}\n")

# Run all strategies
strategies = []

print("Testing Long Options...")
t, b = backtest_long_options(df_all, signals)
strategies.append(analyze_performance(t, "Long Options (Baseline)"))

print("Testing Debit Spreads ATM...")
t, b = backtest_debit_spread(df_all, signals, atm_offset=0)
strategies.append(analyze_performance(t, "Debit Spread ATM"))

print("Testing Debit Spreads OTM +$5...")
t, b = backtest_debit_spread(df_all, signals, atm_offset=5)
strategies.append(analyze_performance(t, "Debit Spread OTM"))

print("Testing Balanced Fly ATM...")
t, b = backtest_balanced_fly(df_all, signals, atm_offset=0)
strategies.append(analyze_performance(t, "Balanced Fly ATM"))

print("Testing Balanced Fly OTM +$5...")
t, b = backtest_balanced_fly(df_all, signals, atm_offset=5)
strategies.append(analyze_performance(t, "Balanced Fly OTM"))

# Display results
print("\n" + "="*80)
print("RESULTS SUMMARY")
print("="*80)
print(f"{'Strategy':<30} {'Trades':<8} {'Win%':<8} {'Return%':<12} {'MaxDD%':<10} {'PF':<8}")
print("-"*80)

for s in strategies:
    print(f"{s['label']:<30} {s['trades']:<8} {s['win_rate']:<8.1f} {s['return_pct']:<12.2f} {s['max_dd_pct']:<10.2f} {s['profit_factor']:<8.2f}")

print("="*80)
print("\n💡 INTERPRETATION:")
print("- Long Options: Unlimited upside, higher risk")
print("- Debit Spreads: Capped profit, defined risk, cheaper")
print("- Balanced Flies: Max profit at body, tight P&L range")
print("="*80 + "\n")
