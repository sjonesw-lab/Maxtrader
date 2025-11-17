#!/usr/bin/env python3
"""
ATR Strategy with Realistic 0DTE Options Pricing Model
Based on observed QQQ options patterns from Polygon data
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
    """Calculate ATR."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def estimate_realistic_option_premium(underlying_price, strike, time_minutes_from_open):
    """
    Realistic 0DTE option premium based on observed QQQ patterns.
    
    Based on Polygon data samples:
    - ATM options at open: $2-3
    - ATM options at midday: $1-2
    - ATM options at close: $0.50-1
    - 1% OTM: ~50-70% of ATM premium
    - 2% OTM: ~20-30% of ATM premium
    
    Formula:
    Premium = Base(moneyness) × TimeDecay(minutes) × VolatilityFactor(price)
    """
    # Calculate moneyness
    moneyness = (underlying_price - strike) / underlying_price
    
    # Base premium based on money-ness
    if moneyness >= 0.01:  # >1% ITM
        base_premium = 3.0 + (moneyness * 100)  # Deep ITM
    elif moneyness >= 0.005:  # 0.5-1% ITM
        base_premium = 2.5
    elif moneyness >= -0.005:  # ATM (within 0.5%)
        base_premium = 2.0
    elif moneyness >= -0.01:  # 0.5-1% OTM
        base_premium = 1.2
    elif moneyness >= -0.02:  # 1-2% OTM
        base_premium = 0.6
    else:  # >2% OTM
        base_premium = 0.2
    
    # Time decay factor (390 minutes in trading day)
    time_remaining_pct = max(0, (390 - time_minutes_from_open) / 390)
    time_decay = 0.3 + (0.7 * time_remaining_pct)  # Decays from 1.0 to 0.3
    
    # Volatility factor based on underlying price (higher price = higher premium)
    vol_factor = underlying_price / 500  # Normalize around $500
    
    premium = base_premium * time_decay * vol_factor
    
    # Minimum premium (options rarely under $0.05)
    premium = max(premium, 0.05)
    
    return premium


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


def backtest_atr_options(df_1min, signals, atr_multiple=2.5, starting_capital=25000, risk_pct=5.0):
    """Backtest with realistic options pricing."""
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    # Market open time (9:30 AM ET)
    market_open = df_1min.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    
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
        entry_time = entry_bar['timestamp']
        
        # Calculate time from market open
        time_from_open = (entry_time - market_open).total_seconds() / 60
        
        # Calculate ATR target
        atr_value = signal.get('atr', 0.5)
        target_distance = atr_multiple * atr_value
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
            strike = round(entry_price / 5) * 5  # ATM call
        else:
            target_price = entry_price - target_distance
            strike = round(entry_price / 5) * 5  # ATM put
        
        # Minimum target filter
        if target_distance < 0.15:
            continue
        
        # Estimate option premium at entry
        premium_per_contract = estimate_realistic_option_premium(entry_price, strike, time_from_open)
        
        # Calculate contracts (5% risk)
        risk_dollars = account_balance * (risk_pct / 100)
        num_contracts = int(risk_dollars / (premium_per_contract * 100))
        
        # Realistic limits (1-10 contracts)
        num_contracts = max(1, min(num_contracts, 10))
        
        total_premium_paid = num_contracts * premium_per_contract * 100
        
        # Exit logic (60-minute hold max)
        exit_window = df_1min.loc[entry_idx:entry_idx + 60]
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        exit_price = None
        exit_time = None
        exit_idx = None
        
        for idx, bar in exit_window.iterrows():
            if signal['direction'] == 'long':
                if bar['high'] >= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    exit_idx = idx
                    break
            else:
                if bar['low'] <= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    exit_idx = idx
                    break
        
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
            exit_idx = exit_window.index[-1]
        
        # Calculate option value at exit
        time_at_exit = (exit_time - market_open).total_seconds() / 60
        
        if hit_target:
            # Target hit: option is ITM by target_distance
            intrinsic_value = target_distance * 100
            option_value_at_exit = intrinsic_value * num_contracts
        else:
            # Target not hit: estimate option value at exit
            exit_premium_per_contract = estimate_realistic_option_premium(exit_price, strike, time_at_exit)
            option_value_at_exit = exit_premium_per_contract * 100 * num_contracts
        
        # P&L
        position_pnl = option_value_at_exit - total_premium_paid
        
        # Update account
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'target_distance': target_distance,
            'premium_paid': total_premium_paid,
            'option_value': option_value_at_exit,
            'num_contracts': num_contracts,
            'pnl': position_pnl,
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
    
    winners = trades_df[trades_df['pnl'] > 0]
    
    return {
        'final_balance': final_balance,
        'total_return': final_balance - starting_capital,
        'return_pct': ((final_balance - starting_capital) / starting_capital) * 100,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'total_trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'avg_contracts': trades_df['num_contracts'].mean(),
        'avg_premium': trades_df['premium_paid'].mean(),
    }


# ============================================================================
# RUN 2024 & 2025 WITH REALISTIC OPTIONS
# ============================================================================

print("\n" + "="*80)
print("2.5x ATR STRATEGY - REALISTIC 0DTE OPTIONS")
print("="*80)
print("Starting Capital: $25,000")
print("Risk Per Trade: 5% (compounding)")
print("Target: 2.5x ATR")
print("Options: ATM strikes, realistic premium modeling")
print("="*80)

test_periods = [
    ('2024', list(range(1, 13))),
    ('2025', list(range(1, 12))),
]

for year_label, months in test_periods:
    print(f"\n{'='*80}")
    print(f"{year_label} RESULTS")
    print(f"{'='*80}")
    
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
            
            df_1min = calculate_atr(df_1min, period=14)
            df_1min = label_sessions(df_1min)
            df_1min = add_session_highs_lows(df_1min)
            df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
            
            signals = find_ict_confluence_signals(df_1min)
            
            if len(signals) == 0:
                continue
            
            trades = backtest_atr_options(df_1min, signals, atr_multiple=2.5)
            
            if len(trades) > 0:
                all_trades.append(trades)
                print(f"  {year_label}-{month:02d}: {len(trades):3d} trades")
                
        except Exception as e:
            print(f"  {year_label}-{month:02d}: Error - {str(e)[:50]}")
            continue
    
    if all_trades:
        combined_trades = pd.concat(all_trades, ignore_index=True)
        perf = calculate_performance(combined_trades)
        
        print(f"\n  📊 {year_label} PERFORMANCE:")
        print(f"     Starting Capital: $25,000.00")
        print(f"     Final Balance: ${perf['final_balance']:,.2f}")
        print(f"     Total Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
        print(f"     Max Drawdown: ${perf['max_drawdown']:,.2f} ({perf['max_drawdown_pct']:.2f}%)")
        print(f"     Total Trades: {perf['total_trades']}")
        print(f"     Win Rate: {perf['win_rate']:.1f}%")
        print(f"     Target Hit Rate: {perf['target_hit_rate']:.1f}%")
        print(f"     Avg Contracts: {perf['avg_contracts']:.1f}")
        print(f"     Avg Premium: ${perf['avg_premium']:.2f}")

print(f"\n{'='*80}\n")
