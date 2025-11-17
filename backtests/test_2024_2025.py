#!/usr/bin/env python3
"""
Test ICT Strategy on 2024 Full Year and 2025 YTD
With 5% risk per trade (aggressive strategy only)
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.timeframes import resample_to_timeframe


def find_swing_targets(df_htf, signal_time, lookback_bars=20):
    """Find swing high/low on higher timeframe."""
    mask = df_htf['timestamp'] <= signal_time
    if not mask.any():
        return None
    
    current_idx = mask.sum() - 1
    start_idx = max(0, current_idx - lookback_bars)
    recent = df_htf.iloc[start_idx:current_idx + 1]
    
    if len(recent) == 0:
        return None
    
    return {
        'swing_high': recent['high'].max(),
        'swing_low': recent['low'].min(),
        'swing_range': recent['high'].max() - recent['low'].min()
    }


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
                    'direction': 'long'
                })
        
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short'
                })
    
    return pd.DataFrame(signals)


def backtest_15min_swings(df_1min, df_15min, signals, target_pct=1.0):
    """Backtest with 15-minute swing targets."""
    trades = []
    last_exit_time = None
    
    for _, signal in signals.iterrows():
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        swing_data = find_swing_targets(df_15min, signal['timestamp'], lookback_bars=20)
        if not swing_data or swing_data['swing_range'] < 0.30:
            continue
        
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        
        if signal['direction'] == 'long':
            target_price = swing_data['swing_low'] + (target_pct * swing_data['swing_range'])
        else:
            target_price = swing_data['swing_high'] - (target_pct * swing_data['swing_range'])
        
        target_distance = abs(target_price - entry_price)
        if target_distance < 0.15:
            continue
        
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
        
        if signal['direction'] == 'long':
            pnl_per_share = exit_price - entry_price
        else:
            pnl_per_share = entry_price - exit_price
        
        trades.append({
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'pnl_per_share': pnl_per_share
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_account_performance(trades_df, starting_capital=25000, risk_per_trade_pct=5.0):
    """Calculate account performance with position sizing."""
    if len(trades_df) == 0:
        return None
    
    account_balance = starting_capital
    risk_dollars = starting_capital * (risk_per_trade_pct / 100)
    
    equity_curve = [starting_capital]
    
    for _, trade in trades_df.iterrows():
        # 100 shares per position (typical for QQQ at ~$400)
        shares = 100
        position_pnl = trade['pnl_per_share'] * shares
        
        account_balance += position_pnl
        equity_curve.append(account_balance)
    
    # Calculate max drawdown
    equity_curve = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_drawdown = drawdown.min()
    max_drawdown_pct = (max_drawdown / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl_per_share'] > 0]
    
    return {
        'starting_capital': starting_capital,
        'final_balance': account_balance,
        'total_return': account_balance - starting_capital,
        'return_pct': ((account_balance - starting_capital) / starting_capital) * 100,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'total_trades': len(trades_df),
        'winners': len(winners),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
    }


# Main analysis
print("\n" + "="*70)
print("ICT AGGRESSIVE STRATEGY: 2024 & 2025 YTD")
print("="*70)
print("\nConfiguration:")
print("  • Strategy: 100% of 15-Minute Swing")
print("  • Risk: 5% per trade")
print("  • Starting Capital: $25,000")
print("="*70)

# Test 2024 and 2025
test_periods = [
    ('2024', list(range(1, 13))),  # All 12 months
    ('2025', list(range(1, 12))),  # Jan-Nov
]

for year_label, months in test_periods:
    print(f"\n{'='*70}")
    print(f"{year_label} RESULTS")
    print(f"{'='*70}")
    
    all_trades = []
    months_processed = 0
    
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
            
            df_15min = resample_to_timeframe(df_1min, '15min')
            
            df_1min = label_sessions(df_1min)
            df_1min = add_session_highs_lows(df_1min)
            df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
            
            signals = find_ict_confluence_signals(df_1min)
            
            if len(signals) == 0:
                continue
            
            trades = backtest_15min_swings(df_1min, df_15min, signals, target_pct=1.0)
            
            if len(trades) > 0:
                all_trades.append(trades)
                months_processed += 1
                print(f"  {year_label}-{month:02d}: {len(trades):3d} trades")
        except Exception as e:
            print(f"  {year_label}-{month:02d}: Error - {str(e)[:50]}")
            continue
    
    if all_trades:
        combined_trades = pd.concat(all_trades, ignore_index=True)
        perf = calculate_account_performance(combined_trades, starting_capital=25000, risk_per_trade_pct=5.0)
        
        print(f"\n  📊 {year_label} PERFORMANCE ({months_processed} months):")
        print(f"     Starting Capital: ${perf['starting_capital']:,.2f}")
        print(f"     Final Balance: ${perf['final_balance']:,.2f}")
        print(f"     Total Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
        print(f"     Max Drawdown: ${perf['max_drawdown']:,.2f} ({perf['max_drawdown_pct']:.2f}%)")
        print(f"     Total Trades: {perf['total_trades']}")
        print(f"     Win Rate: {perf['win_rate']:.1f}%")
        print(f"     Target Hit Rate: {perf['target_hit_rate']:.1f}%")
    else:
        print(f"\n  ⚠ No data available for {year_label}")

print(f"\n{'='*70}\n")
