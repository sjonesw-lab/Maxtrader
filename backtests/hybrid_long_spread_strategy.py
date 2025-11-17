#!/usr/bin/env python3
"""
Hybrid Strategy: 1 Long Call/Put + 1 Debit Spread
- Long option = runner (unlimited upside)
- Spread = defined risk, lower cost
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


def estimate_option_premium(underlying_price, strike, time_minutes_from_open=0):
    """Estimate single option premium."""
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
    
    return max(base_premium * time_decay * vol_factor, 0.05)


def calculate_spread_cost(underlying_price, long_strike, short_strike, time_minutes_from_open=0):
    """Calculate debit spread cost (long - short)."""
    long_premium = estimate_option_premium(underlying_price, long_strike, time_minutes_from_open)
    short_premium = estimate_option_premium(underlying_price, short_strike, time_minutes_from_open)
    return long_premium - short_premium


def calculate_spread_value_at_exit(exit_price, long_strike, short_strike, direction, time_at_exit=0):
    """Calculate spread value at exit."""
    if direction == 'long':
        # Call spread
        if exit_price >= short_strike:
            # Max profit: spread width
            return short_strike - long_strike
        elif exit_price >= long_strike:
            # Partial profit: ITM amount
            return exit_price - long_strike
        else:
            # Worthless
            return 0
    else:
        # Put spread
        if exit_price <= short_strike:
            # Max profit
            return long_strike - short_strike
        elif exit_price <= long_strike:
            # Partial profit
            return long_strike - exit_price
        else:
            # Worthless
            return 0


def find_ict_signals(df):
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


def backtest_hybrid(df_1min, signals, atr_multiple=5.0, starting_capital=25000, risk_pct=5.0):
    """
    Hybrid strategy:
    - 1 ATM long call/put (runner)
    - 1 debit spread (ATM / 1 OTM) for defined risk
    """
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    market_open = df_1min.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    
    for _, signal in signals.iterrows():
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        entry_time = entry_bar['timestamp']
        
        time_from_open = (entry_time - market_open).total_seconds() / 60
        
        # Target
        atr_value = signal.get('atr', 0.5)
        target_distance = atr_multiple * atr_value
        
        if target_distance < 0.15:
            continue
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
            atm_strike = round(entry_price / 5) * 5
            otm_strike = atm_strike + 5  # 1 strike OTM
        else:
            target_price = entry_price - target_distance
            atm_strike = round(entry_price / 5) * 5
            otm_strike = atm_strike - 5  # 1 strike OTM
        
        # Calculate costs
        # 1. Long ATM option (runner)
        long_premium = estimate_option_premium(entry_price, atm_strike, time_from_open)
        
        # 2. Debit spread (ATM / OTM)
        spread_cost = calculate_spread_cost(entry_price, atm_strike, otm_strike, time_from_open)
        
        # Total cost per unit
        total_cost_per_unit = long_premium + spread_cost
        
        # Position sizing: risk 5% of balance
        risk_dollars = account_balance * (risk_pct / 100)
        num_units = int(risk_dollars / (total_cost_per_unit * 100))
        num_units = max(1, min(num_units, 10))
        
        total_premium_paid = num_units * total_cost_per_unit * 100
        
        # Exit logic
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
        
        time_at_exit = (exit_time - market_open).total_seconds() / 60
        
        # Calculate value at exit
        # 1. Long runner value
        if hit_target:
            long_value = target_distance * 100  # Intrinsic value
        else:
            long_exit_premium = estimate_option_premium(exit_price, atm_strike, time_at_exit)
            long_value = long_exit_premium * 100
        
        # 2. Spread value
        spread_value_per_unit = calculate_spread_value_at_exit(
            exit_price, atm_strike, otm_strike, signal['direction'], time_at_exit
        )
        spread_value = spread_value_per_unit * 100
        
        # Total value
        total_exit_value = (long_value + spread_value) * num_units
        
        # P&L
        position_pnl = total_exit_value - total_premium_paid
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'target_distance': target_distance,
            'long_premium': long_premium * num_units * 100,
            'spread_cost': spread_cost * num_units * 100,
            'total_cost': total_premium_paid,
            'exit_value': total_exit_value,
            'pnl': position_pnl,
            'balance': account_balance,
            'num_units': num_units,
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def analyze_performance(trades_df, label, starting_capital=25000):
    if len(trades_df) == 0:
        return
    
    final_balance = trades_df.iloc[-1]['balance']
    equity_curve = trades_df['balance'].values
    
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_drawdown = drawdown.min()
    max_dd_pct = (max_drawdown / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    
    total_return = final_balance - starting_capital
    return_pct = (total_return / starting_capital) * 100
    
    print(f"\n{'='*80}")
    print(f"{label} PERFORMANCE - HYBRID STRATEGY")
    print(f"{'='*80}")
    print(f"Starting Capital:    ${starting_capital:,.2f}")
    print(f"Final Balance:       ${final_balance:,.2f}")
    print(f"Total Return:        ${total_return:,.2f} ({return_pct:.2f}%)")
    print(f"Max Drawdown:        ${max_drawdown:,.2f} ({max_dd_pct:.2f}%)")
    print(f"\nTrade Statistics:")
    print(f"  Total Trades:      {len(trades_df)}")
    print(f"  Winners:           {len(winners)} ({len(winners)/len(trades_df)*100:.1f}%)")
    print(f"  Losers:            {len(losers)} ({len(losers)/len(trades_df)*100:.1f}%)")
    print(f"  Target Hit Rate:   {trades_df['hit_target'].sum()} ({trades_df['hit_target'].sum()/len(trades_df)*100:.1f}%)")
    print(f"\nP&L Analysis:")
    print(f"  Avg Win:           ${winners['pnl'].mean():.2f}" if len(winners) > 0 else "  Avg Win:           N/A")
    print(f"  Avg Loss:          ${losers['pnl'].mean():.2f}" if len(losers) > 0 else "  Avg Loss:          N/A")
    print(f"  Avg Total Cost:    ${trades_df['total_cost'].mean():.2f}")
    print(f"  Avg Long Premium:  ${trades_df['long_premium'].mean():.2f}")
    print(f"  Avg Spread Cost:   ${trades_df['spread_cost'].mean():.2f}")
    
    if len(winners) > 0 and len(losers) > 0:
        profit_factor = abs(winners['pnl'].sum() / losers['pnl'].sum())
        print(f"  Profit Factor:     {profit_factor:.2f}")
    
    print(f"{'='*80}\n")


# ============================================================================
# RUN HYBRID STRATEGY
# ============================================================================

print("\n" + "="*80)
print("HYBRID STRATEGY: 1 LONG RUNNER + 1 DEBIT SPREAD")
print("="*80)
print("Position: 1 ATM call/put + 1 debit spread (ATM/1OTM)")
print("Long = runner (unlimited upside)")
print("Spread = defined risk (capped at spread width)")
print("="*80)

for year in ['2024', '2025']:
    all_data = []
    months = range(1, 13) if year == '2024' else range(1, 12)
    
    for month in months:
        filename = f'QQQ_{year}_{month:02d}_1min.csv'
        data_path = Path(f'data/polygon_downloads/{filename}')
        
        if data_path.exists():
            try:
                provider = CSVDataProvider(str(data_path))
                df = provider.load_bars()
                if len(df) > 0:
                    all_data.append(df)
            except:
                continue
    
    if all_data:
        df_year = pd.concat(all_data, ignore_index=True)
        df_year = calculate_atr(df_year, period=14)
        df_year = label_sessions(df_year)
        df_year = add_session_highs_lows(df_year)
        df_year = detect_all_structures(df_year, displacement_threshold=1.0)
        
        signals = find_ict_signals(df_year)
        trades = backtest_hybrid(df_year, signals, atr_multiple=5.0)
        
        analyze_performance(trades, year)

print("="*80)
print("COMPARISON TO PURE LONG")
print("="*80)
print("Hybrid = 1 long + 1 spread (lower cost, runner potential)")
print("Pure Long = just ATM options (higher cost, unlimited upside)")
print("="*80 + "\n")
