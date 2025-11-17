#!/usr/bin/env python3
"""
ATR Strategy with Options-Based Position Sizing and Compounding
2024 & 2025 Full Dataset
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


def estimate_option_premium(entry_price, target_distance, direction):
    """
    Realistic option premium estimation for 0DTE options.
    
    For QQQ 0DTE options with 60-min hold:
    - Base premium: $100 (minimum for 0DTE near-money options)
    - Plus: proportional to target distance
    - Typical range: $100-200 per contract
    """
    # Base premium + premium based on target distance
    base_premium = 100
    distance_premium = target_distance * 100 * 0.25
    
    premium_per_contract = base_premium + distance_premium
    
    # Cap at $300 per contract (very ITM options)
    premium_per_contract = min(premium_per_contract, 300)
    
    return premium_per_contract


def backtest_atr_options(df_1min, signals, atr_multiple=2.5, starting_capital=25000, risk_pct=5.0):
    """
    Backtest with ATR targets and options-based position sizing.
    
    Position sizing:
    - Risk = X% of current account balance
    - Contracts = risk_dollars / premium_per_contract
    - Max loss = total premium paid
    """
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
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
        
        # Estimate option premium
        premium_per_contract = estimate_option_premium(entry_price, target_distance, signal['direction'])
        
        # Calculate number of contracts based on current balance
        risk_dollars = account_balance * (risk_pct / 100)
        num_contracts = int(risk_dollars / premium_per_contract)
        
        # Minimum 1 contract, max 20 contracts (realistic position limit)
        num_contracts = max(1, min(num_contracts, 20))
        
        total_premium_paid = num_contracts * premium_per_contract
        
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
        
        # Calculate option P&L
        if signal['direction'] == 'long':
            intrinsic_value_per_contract = max(0, (exit_price - entry_price) * 100)
        else:
            intrinsic_value_per_contract = max(0, (entry_price - exit_price) * 100)
        
        # Total option value at exit
        total_option_value = intrinsic_value_per_contract * num_contracts
        
        # P&L = exit value - premium paid
        position_pnl = total_option_value - total_premium_paid
        
        # Update account
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'target_distance': target_distance,
            'premium_per_contract': premium_per_contract,
            'num_contracts': num_contracts,
            'total_premium': total_premium_paid,
            'option_value_at_exit': total_option_value,
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
        'avg_premium': trades_df['total_premium'].mean(),
    }


# ============================================================================
# RUN 2024 & 2025 WITH OPTIONS COMPOUNDING
# ============================================================================

print("\n" + "="*80)
print("2.5x ATR STRATEGY - OPTIONS WITH COMPOUNDING")
print("="*80)
print("Starting Capital: $25,000")
print("Risk Per Trade: 5% (compounding)")
print("Target: 2.5x ATR")
print("Max Hold: 60 minutes")
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
            
            # Calculate ATR
            df_1min = calculate_atr(df_1min, period=14)
            
            df_1min = label_sessions(df_1min)
            df_1min = add_session_highs_lows(df_1min)
            df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
            
            signals = find_ict_confluence_signals(df_1min)
            
            if len(signals) == 0:
                continue
            
            trades = backtest_atr_options(df_1min, signals, atr_multiple=2.5, 
                                         starting_capital=25000, risk_pct=5.0)
            
            if len(trades) > 0:
                all_trades.append(trades)
                print(f"  {year_label}-{month:02d}: {len(trades):3d} trades")
                
        except Exception as e:
            print(f"  {year_label}-{month:02d}: Error - {str(e)[:50]}")
            continue
    
    if all_trades:
        combined_trades = pd.concat(all_trades, ignore_index=True)
        perf = calculate_performance(combined_trades, starting_capital=25000)
        
        print(f"\n  📊 {year_label} PERFORMANCE:")
        print(f"     Starting Capital: ${perf['final_balance'] if len(all_trades) == 1 else 25000:,.2f}")
        print(f"     Final Balance: ${perf['final_balance']:,.2f}")
        print(f"     Total Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
        print(f"     Max Drawdown: ${perf['max_drawdown']:,.2f} ({perf['max_drawdown_pct']:.2f}%)")
        print(f"     Total Trades: {perf['total_trades']}")
        print(f"     Win Rate: {perf['win_rate']:.1f}%")
        print(f"     Target Hit Rate: {perf['target_hit_rate']:.1f}%")
        print(f"     Avg Contracts: {perf['avg_contracts']:.1f}")
        print(f"     Avg Premium: ${perf['avg_premium']:.2f}")
    else:
        print(f"\n  ⚠ No data available for {year_label}")

print(f"\n{'='*80}\n")
