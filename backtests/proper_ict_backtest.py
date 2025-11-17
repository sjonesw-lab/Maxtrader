#!/usr/bin/env python3
"""
Proper ICT strategy with multi-timeframe structure:
- 4H timeframe: Find swing highs/lows for TARGETS
- 1-minute timeframe: ICT confluence for ENTRY TRIGGER
- NO STOP LOSS (let defined risk options handle it)
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


def find_swing_targets_4h(df_4h, signal_time, lookback_bars=20):
    """
    Find swing high/low on 4H chart for target calculation.
    
    Args:
        df_4h: 4-hour timeframe data
        signal_time: Entry signal timestamp
        lookback_bars: How many 4H bars to look back
    
    Returns:
        dict with swing_high, swing_low, swing_range
    """
    # Find the 4H bar containing the signal
    mask = df_4h['timestamp'] <= signal_time
    if not mask.any():
        return None
    
    current_idx = mask.sum() - 1
    start_idx = max(0, current_idx - lookback_bars)
    
    # Get recent 4H data
    recent = df_4h.iloc[start_idx:current_idx + 1]
    
    if len(recent) == 0:
        return None
    
    swing_high = recent['high'].max()
    swing_low = recent['low'].min()
    swing_range = swing_high - swing_low
    
    return {
        'swing_high': swing_high,
        'swing_low': swing_low,
        'swing_range': swing_range
    }


def find_confluence_signals(df):
    """Find ICT confluence on 1-minute data."""
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


def backtest_with_htf_targets(df_1min, df_htf, signals, target_pct=0.75, max_hold_bars=60, tf_name='4H'):
    """
    Backtest with 4H swing targets.
    
    Args:
        target_pct: What % of 4H swing range to use (0.5 = 50%, 0.75 = 75%)
    """
    trades = []
    last_exit_time = None
    
    for _, signal in signals.iterrows():
        # No overlapping trades
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Get HTF swing structure for targets
        swing_data = find_swing_targets_4h(df_htf, signal['timestamp'], lookback_bars=20)
        if not swing_data or swing_data['swing_range'] < 0.50:  # Min $0.50 range
            continue
        
        # Find next bar for entry
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        
        # Calculate target from 4H swing structure
        if signal['direction'] == 'long':
            # Target: swing_low + (target_pct * swing_range)
            target_price = swing_data['swing_low'] + (target_pct * swing_data['swing_range'])
        else:
            # Target: swing_high - (target_pct * swing_range)
            target_price = swing_data['swing_high'] - (target_pct * swing_data['swing_range'])
        
        # Check if target is reasonable from entry
        target_distance = abs(target_price - entry_price)
        if target_distance < 0.30:  # Min $0.30 target distance
            continue
        
        # Exit window
        exit_window = df_1min.loc[entry_idx:entry_idx + max_hold_bars]
        if len(exit_window) == 0:
            continue
        
        # Track trade
        trade = {
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'direction': signal['direction'],
            'target': target_price,
            'swing_high': swing_data['swing_high'],
            'swing_low': swing_data['swing_low'],
            'swing_range': swing_data['swing_range'],
            'target_pct': target_pct
        }
        
        # Find exit (NO STOP, only target or time)
        hit_target = False
        exit_price = None
        exit_time = None
        bars_held = 0
        
        for idx, bar in exit_window.iterrows():
            bars_held += 1
            
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
        
        # Time-based exit if target not hit
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        # Calculate P&L
        if signal['direction'] == 'long':
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
        
        trade.update({
            'exit_time': exit_time,
            'exit_price': exit_price,
            'bars_held': bars_held,
            'hit_target': hit_target,
            'pnl': pnl,
            'pnl_pct': (pnl / entry_price) * 100
        })
        
        trades.append(trade)
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_metrics(trades_df):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return None
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] < 0]
    
    total_wins = winners['pnl'].sum() if len(winners) > 0 else 0
    total_losses = abs(losers['pnl'].sum()) if len(losers) > 0 else 0
    
    return {
        'total_trades': len(trades_df),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'profit_factor': total_wins / total_losses if total_losses > 0 else 0,
        'total_pnl': trades_df['pnl'].sum(),
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'avg_swing_range': trades_df['swing_range'].mean()
    }


# Run backtest
print("\n" + "="*70)
print("PROPER MULTI-TIMEFRAME ICT STRATEGY")
print("="*70)
print("\nSetup:")
print("  - 4H chart: Identify swing highs/lows for TARGETS")
print("  - 1-min chart: ICT confluence (Sweep+Displacement+MSS) for ENTRY")
print("  - NO STOP LOSS (defined risk via options)")
print("  - Max hold: 60 minutes\n")

months = [
    'QQQ_2021_05_1min.csv',
    'QQQ_2022_04_1min.csv',
    'QQQ_2023_06_1min.csv',
    'QQQ_2024_06_1min.csv'
]

# Test different swing target percentages
target_configs = [
    0.50,  # 50% of 4H swing
    0.75,  # 75% of 4H swing
    1.00,  # 100% of 4H swing (full swing)
]

# Test different timeframes for swing structure
for tf_key, tf_display in [('15min', '15-Min'), ('1h', '1-Hour'), ('4h', '4-Hour')]:
    for target_pct in [0.75, 1.0]:  # Test 75% and 100% of swing
        print(f"\n{'='*70}")
        print(f"Testing: {tf_display} Swings, {int(target_pct*100)}% Target")
        print(f"{'='*70}\n")
        
        all_trades = []
        
        for month_file in months:
            data_path = Path(f'data/polygon_downloads/{month_file}')
            if not data_path.exists():
                continue
            
            # Load 1-minute data
            provider = CSVDataProvider(str(data_path))
            df_1min = provider.load_bars()
            
            # Resample to target timeframe
            df_htf = resample_to_timeframe(df_1min, tf_key)
            
            # Detect ICT structures on 1-min
            df_1min = label_sessions(df_1min)
            df_1min = add_session_highs_lows(df_1min)
            df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
            
            # Find confluence signals
            signals = find_confluence_signals(df_1min)
            
            # Backtest with HTF swing targets
            trades = backtest_with_htf_targets(df_1min, df_htf, signals, target_pct=target_pct, tf_name=tf_display)
            
            if len(trades) > 0:
                metrics = calculate_metrics(trades)
                month_name = month_file.replace('QQQ_', '').replace('_1min.csv', '')
                print(f"{month_name}: {metrics['total_trades']} trades, "
                      f"{metrics['target_hit_rate']:.1f}% hit target, "
                      f"${metrics['total_pnl']:,.2f} P&L")
                all_trades.append(trades)
        
        # Combined results
        if all_trades:
            combined = pd.concat(all_trades, ignore_index=True)
            metrics = calculate_metrics(combined)
            
            print(f"\n📊 COMBINED:")
            print(f"   Trades: {metrics['total_trades']}, "
                  f"Target Hit: {metrics['target_hit_rate']:.1f}%, "
                  f"PF: {metrics['profit_factor']:.2f}, "
                  f"P&L: ${metrics['total_pnl']:,.2f}")

print(f"\n{'='*70}\n")
