#!/usr/bin/env python3
"""
Comprehensive Options Testing Matrix:
- Test 0DTE, 1DTE, 2DTE, 3DTE options
- Test 2.5x, 5x, 10x ATR targets
- Find the optimal combination
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


def estimate_option_premium(underlying_price, strike, days_to_expiry=0, time_minutes_from_open=0):
    """
    Realistic option premium model for 0-3 DTE options.
    
    Key insights:
    - 0DTE: Expensive due to gamma risk ($2-3 ATM at open)
    - 1DTE: ~40% cheaper ($1.20-1.80 ATM at open)
    - 2DTE: ~60% cheaper ($0.80-1.20 ATM at open)
    - 3DTE: ~70% cheaper ($0.60-0.90 ATM at open)
    """
    # Calculate moneyness
    moneyness = (underlying_price - strike) / underlying_price
    
    # Base premium for 0DTE ATM option at market open
    if moneyness >= 0.01:  # >1% ITM
        base_0dte = 3.0 + (moneyness * 100)
    elif moneyness >= 0.005:  # 0.5-1% ITM
        base_0dte = 2.5
    elif moneyness >= -0.005:  # ATM
        base_0dte = 2.0
    elif moneyness >= -0.01:  # 0.5-1% OTM
        base_0dte = 1.2
    elif moneyness >= -0.02:  # 1-2% OTM
        base_0dte = 0.6
    else:  # >2% OTM
        base_0dte = 0.2
    
    # DTE discount factor
    dte_factor = {
        0: 1.0,    # 0DTE = full price
        1: 0.6,    # 1DTE = 40% cheaper
        2: 0.4,    # 2DTE = 60% cheaper
        3: 0.3,    # 3DTE = 70% cheaper
    }.get(days_to_expiry, 0.3)
    
    # Intraday time decay (only for 0DTE)
    if days_to_expiry == 0:
        time_remaining_pct = max(0, (390 - time_minutes_from_open) / 390)
        time_decay = 0.3 + (0.7 * time_remaining_pct)
    else:
        time_decay = 1.0  # Multi-day options don't decay intraday as fast
    
    # Volatility factor
    vol_factor = underlying_price / 500
    
    premium = base_0dte * dte_factor * time_decay * vol_factor
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


def backtest_options(df_1min, signals, atr_multiple, days_to_expiry, starting_capital=25000, risk_pct=5.0):
    """Backtest with specific option DTE and ATR target."""
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
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
        
        time_from_open = (entry_time - market_open).total_seconds() / 60
        
        # Calculate target
        atr_value = signal.get('atr', 0.5)
        target_distance = atr_multiple * atr_value
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
            strike = round(entry_price / 5) * 5
        else:
            target_price = entry_price - target_distance
            strike = round(entry_price / 5) * 5
        
        # Minimum target
        if target_distance < 0.15:
            continue
        
        # Estimate premium
        premium_per_contract = estimate_option_premium(
            entry_price, strike, days_to_expiry, time_from_open
        )
        
        # Position sizing
        risk_dollars = account_balance * (risk_pct / 100)
        num_contracts = int(risk_dollars / (premium_per_contract * 100))
        num_contracts = max(1, min(num_contracts, 10))
        
        total_premium_paid = num_contracts * premium_per_contract * 100
        
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
        
        # Calculate option value at exit
        time_at_exit = (exit_time - market_open).total_seconds() / 60
        
        if hit_target:
            # Option is ITM
            intrinsic_value = target_distance * 100
            option_value_at_exit = intrinsic_value * num_contracts
        else:
            # Estimate option value
            exit_premium = estimate_option_premium(exit_price, strike, days_to_expiry, time_at_exit)
            option_value_at_exit = exit_premium * 100 * num_contracts
        
        # P&L
        position_pnl = option_value_at_exit - total_premium_paid
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'hit_target': hit_target,
            'target_distance': target_distance,
            'premium_paid': total_premium_paid,
            'option_value': option_value_at_exit,
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
    
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_drawdown = drawdown.min()
    max_drawdown_pct = (max_drawdown / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl'] > 0]
    
    return {
        'final_balance': final_balance,
        'total_return': final_balance - starting_capital,
        'return_pct': ((final_balance - starting_capital) / starting_capital) * 100,
        'max_drawdown_pct': max_drawdown_pct,
        'total_trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'avg_premium': trades_df['premium_paid'].mean(),
    }


# ============================================================================
# RUN MATRIX TEST
# ============================================================================

print("\n" + "="*80)
print("OPTIONS CONFIGURATION MATRIX TEST")
print("="*80)
print("Starting Capital: $25,000 | Risk: 5% per trade")
print("Testing: 0DTE, 1DTE, 2DTE, 3DTE × 2.5x, 5x, 10x ATR")
print("="*80 + "\n")

# Load all 2024 data
all_data = []
for month in range(1, 13):
    filename = f'QQQ_2024_{month:02d}_1min.csv'
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
    df_2024 = pd.concat(all_data, ignore_index=True)
    df_2024 = calculate_atr(df_2024, period=14)
    df_2024 = label_sessions(df_2024)
    df_2024 = add_session_highs_lows(df_2024)
    df_2024 = detect_all_structures(df_2024, displacement_threshold=1.0)
    
    signals = find_ict_confluence_signals(df_2024)
    
    print(f"✓ Loaded 2024 data: {len(df_2024):,} bars, {len(signals)} ICT signals\n")
    
    # Test matrix
    results = []
    
    for dte in [0, 1, 2, 3]:
        for atr_mult in [2.5, 5.0, 10.0]:
            trades = backtest_options(df_2024, signals, atr_mult, dte)
            
            if len(trades) > 0:
                perf = calculate_performance(trades)
                
                results.append({
                    'DTE': dte,
                    'ATR_Multiple': atr_mult,
                    'Trades': perf['total_trades'],
                    'Win_Rate': perf['win_rate'],
                    'Target_Hit': perf['target_hit_rate'],
                    'Return_Pct': perf['return_pct'],
                    'Max_DD_Pct': perf['max_drawdown_pct'],
                    'Avg_Premium': perf['avg_premium'],
                    'Final_Balance': perf['final_balance'],
                })
    
    # Display results
    results_df = pd.DataFrame(results)
    
    print("="*80)
    print("FULL RESULTS TABLE")
    print("="*80)
    print(results_df.to_string(index=False))
    
    print("\n" + "="*80)
    print("TOP 5 CONFIGURATIONS (by Return %)")
    print("="*80)
    top5 = results_df.nlargest(5, 'Return_Pct')
    for idx, row in top5.iterrows():
        print(f"\n🏆 Rank #{list(top5.index).index(idx) + 1}")
        print(f"   {row['DTE']}DTE × {row['ATR_Multiple']}x ATR")
        print(f"   Return: {row['Return_Pct']:.2f}% | Win Rate: {row['Win_Rate']:.1f}%")
        print(f"   Target Hit: {row['Target_Hit']:.1f}% | Trades: {row['Trades']}")
        print(f"   Final Balance: ${row['Final_Balance']:,.2f}")
        print(f"   Max DD: {row['Max_DD_Pct']:.1f}% | Avg Premium: ${row['Avg_Premium']:.2f}")
    
    print("\n" + "="*80 + "\n")

else:
    print("Error: No 2024 data found\n")
