#!/usr/bin/env python3
"""
Flexible Allocation: Mix longs + spreads within 5% risk budget
System decides optimal ratio based on cost efficiency
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
    long_premium = estimate_option_premium(underlying_price, long_strike, time_minutes_from_open)
    short_premium = estimate_option_premium(underlying_price, short_strike, time_minutes_from_open)
    return long_premium - short_premium


def calculate_spread_value_at_exit(exit_price, long_strike, short_strike, direction):
    if direction == 'long':
        if exit_price >= short_strike:
            return short_strike - long_strike
        elif exit_price >= long_strike:
            return exit_price - long_strike
        else:
            return 0
    else:
        if exit_price <= short_strike:
            return long_strike - short_strike
        elif exit_price <= long_strike:
            return long_strike - exit_price
        else:
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


def backtest_flexible_allocation(df_1min, signals, long_ratio=0.5, atr_multiple=5.0, 
                                  starting_capital=25000, risk_pct=5.0):
    """
    Flexible allocation strategy.
    
    Args:
        long_ratio: % of budget allocated to longs (0-1), rest goes to spreads
                   0.5 = 50% longs, 50% spreads
                   1.0 = 100% longs, 0% spreads
                   0.0 = 0% longs, 100% spreads
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
        
        atr_value = signal.get('atr', 0.5)
        target_distance = atr_multiple * atr_value
        
        if target_distance < 0.15:
            continue
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
            atm_strike = round(entry_price / 5) * 5
            otm_strike = atm_strike + 5
        else:
            target_price = entry_price - target_distance
            atm_strike = round(entry_price / 5) * 5
            otm_strike = atm_strike - 5
        
        # Calculate unit costs
        long_premium = estimate_option_premium(entry_price, atm_strike, time_from_open)
        spread_cost = calculate_spread_cost(entry_price, atm_strike, otm_strike, time_from_open)
        
        # Allocate 5% risk budget
        total_budget = account_balance * (risk_pct / 100)
        
        # Split budget by ratio
        long_budget = total_budget * long_ratio
        spread_budget = total_budget * (1 - long_ratio)
        
        # Calculate quantities
        num_longs = int(long_budget / (long_premium * 100)) if long_ratio > 0 and long_premium > 0 else 0
        num_spreads = int(spread_budget / (spread_cost * 100)) if long_ratio < 1 and spread_cost > 0.01 else 0
        
        # Cap at reasonable limits
        num_longs = min(num_longs, 10)
        num_spreads = min(num_spreads, 10)
        
        # Must have at least something
        if num_longs == 0 and num_spreads == 0:
            num_longs = 1  # Minimum position
        
        # Calculate actual cost
        total_cost = (num_longs * long_premium * 100) + (num_spreads * spread_cost * 100)
        
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
        
        # Calculate exit values
        # 1. Longs
        if num_longs > 0:
            if hit_target:
                long_value = target_distance * 100 * num_longs
            else:
                long_exit_premium = estimate_option_premium(exit_price, atm_strike, time_at_exit)
                long_value = long_exit_premium * 100 * num_longs
        else:
            long_value = 0
        
        # 2. Spreads
        if num_spreads > 0:
            spread_value_per_unit = calculate_spread_value_at_exit(
                exit_price, atm_strike, otm_strike, signal['direction']
            )
            spread_value = spread_value_per_unit * 100 * num_spreads
        else:
            spread_value = 0
        
        # Total
        total_exit_value = long_value + spread_value
        position_pnl = total_exit_value - total_cost
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'num_longs': num_longs,
            'num_spreads': num_spreads,
            'total_cost': total_cost,
            'exit_value': total_exit_value,
            'pnl': position_pnl,
            'balance': account_balance,
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def analyze_performance(trades_df, label, starting_capital=25000):
    if len(trades_df) == 0:
        return None
    
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
    
    print(f"\n{label}")
    print(f"  Return: ${total_return:>10,.0f} ({return_pct:>7.1f}%)")
    print(f"  Final:  ${final_balance:>10,.0f}")
    print(f"  Trades: {len(trades_df):>4} | Win Rate: {len(winners)/len(trades_df)*100:>5.1f}%")
    print(f"  Max DD: {max_dd_pct:>6.2f}%")
    print(f"  Avg Longs:   {trades_df['num_longs'].mean():>4.1f} | Avg Spreads: {trades_df['num_spreads'].mean():>4.1f}")
    
    if len(winners) > 0 and len(losers) > 0:
        pf = abs(winners['pnl'].sum() / losers['pnl'].sum())
        print(f"  Profit Factor: {pf:>5.2f}")
    
    return return_pct


# ============================================================================
# TEST DIFFERENT ALLOCATION RATIOS
# ============================================================================

print("\n" + "="*80)
print("FLEXIBLE ALLOCATION TESTING")
print("="*80)
print("Testing different mixes of longs (runners) + spreads (defined risk)")
print("="*80)

# Load 2024 data
all_data = []
for month in range(1, 13):
    path = Path(f'data/polygon_downloads/QQQ_2024_{month:02d}_1min.csv')
    if path.exists():
        try:
            df = CSVDataProvider(str(path)).load_bars()
            if len(df) > 0:
                all_data.append(df)
        except:
            pass

if all_data:
    df_2024 = pd.concat(all_data, ignore_index=True)
    df_2024 = calculate_atr(df_2024, 14)
    df_2024 = label_sessions(df_2024)
    df_2024 = add_session_highs_lows(df_2024)
    df_2024 = detect_all_structures(df_2024, 1.0)
    
    signals = find_ict_signals(df_2024)
    
    print(f"\n2024 Data: {len(df_2024):,} bars, {len(signals)} signals")
    print("="*80)
    
    results = []
    
    # Test different ratios
    ratios = [
        (0.0, "100% Spreads / 0% Longs"),
        (0.25, "75% Spreads / 25% Longs"),
        (0.5, "50% Spreads / 50% Longs"),
        (0.75, "25% Spreads / 75% Longs"),
        (1.0, "0% Spreads / 100% Longs"),
    ]
    
    for ratio, label in ratios:
        trades = backtest_flexible_allocation(df_2024, signals, long_ratio=ratio)
        ret_pct = analyze_performance(trades, label)
        
        if ret_pct:
            results.append({
                'ratio': ratio,
                'label': label,
                'return_pct': ret_pct,
                'final_balance': trades.iloc[-1]['balance']
            })
    
    # Show winner
    results_df = pd.DataFrame(results)
    best = results_df.loc[results_df['return_pct'].idxmax()]
    
    print(f"\n{'='*80}")
    print(f"🏆 BEST ALLOCATION: {best['label']}")
    print(f"   Return: {best['return_pct']:.2f}% | Final: ${best['final_balance']:,.2f}")
    print(f"{'='*80}\n")

else:
    print("Error loading data\n")
