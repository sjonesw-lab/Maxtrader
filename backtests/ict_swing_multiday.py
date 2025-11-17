#!/usr/bin/env python3
"""
ICT Swing Trading Strategy - Multi-Day Holds

Question: 1H swings ($8.69 avg) only hit 35.9% in 60 minutes.
But what if we hold for 2, 3, or 5 DAYS?

Setup:
- 1-Hour swings for targets
- ICT confluence on 1-minute for entry
- NO STOP LOSS
- Variable hold periods: 1 day, 2 days, 3 days, 5 days
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
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
    
    swing_high = recent['high'].max()
    swing_low = recent['low'].min()
    swing_range = swing_high - swing_low
    
    return {
        'swing_high': swing_high,
        'swing_low': swing_low,
        'swing_range': swing_range
    }


def find_ict_confluence_signals(df):
    """Find ICT confluence: Sweep + Displacement + MSS."""
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


def backtest_multiday_holds(df_1min, df_1h, signals, target_pct=1.0, max_hold_days=5):
    """
    Backtest with multi-day hold periods.
    
    Args:
        max_hold_days: Maximum days to hold (converted to minutes: 1 day = 390 trading mins)
    """
    trades = []
    last_exit_time = None
    
    # Trading minutes per day (9:30am - 4:00pm ET = 390 minutes)
    minutes_per_day = 390
    max_hold_bars = max_hold_days * minutes_per_day
    
    for _, signal in signals.iterrows():
        # No overlapping positions
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Get 1H swing structure
        swing_data = find_swing_targets(df_1h, signal['timestamp'], lookback_bars=20)
        if not swing_data or swing_data['swing_range'] < 0.50:
            continue
        
        # Entry: Next bar at open
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        
        # Calculate target from 1H swing
        if signal['direction'] == 'long':
            target_price = swing_data['swing_low'] + (target_pct * swing_data['swing_range'])
        else:
            target_price = swing_data['swing_high'] - (target_pct * swing_data['swing_range'])
        
        # Skip if target too close
        target_distance = abs(target_price - entry_price)
        if target_distance < 0.30:
            continue
        
        # Exit window (multiple days)
        exit_window = df_1min.loc[entry_idx:entry_idx + max_hold_bars]
        if len(exit_window) == 0:
            continue
        
        # Find exit (NO STOP LOSS)
        hit_target = False
        exit_price = None
        exit_time = None
        bars_held = 0
        days_held = 0
        
        for idx, bar in exit_window.iterrows():
            bars_held += 1
            days_held = bars_held / minutes_per_day
            
            # Check target hit
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
        
        trades.append({
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'target': target_price,
            'swing_range': swing_data['swing_range'],
            'bars_held': bars_held,
            'days_held': days_held,
            'hit_target': hit_target,
            'pnl': pnl,
            'pnl_pct': (pnl / entry_price) * 100
        })
        
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
        'profit_factor': total_wins / total_losses if total_losses > 0 else float('inf'),
        'total_pnl': trades_df['pnl'].sum(),
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'avg_days_held': trades_df['days_held'].mean(),
        'avg_swing_range': trades_df['swing_range'].mean()
    }


# Main backtest
print("\n" + "="*70)
print("ICT SWING TRADING STRATEGY - MULTI-DAY HOLDS")
print("="*70)
print("\nQuestion: 1H swings only hit 35.9% in 60 minutes.")
print("Answer: Let's test holding for 1, 2, 3, and 5 DAYS\n")
print("Strategy:")
print("  ✓ 1-Hour swings for targets (avg $8.69)")
print("  ✓ ICT confluence for entry (Sweep + Displacement + MSS)")
print("  ✓ NO STOP LOSS (defined risk via options)")
print("  ✓ 100% of 1H swing as target")
print("="*70)

# Test files
months = [
    ('QQQ_2021_05_1min.csv', '2021_05'),
    ('QQQ_2022_04_1min.csv', '2022_04'),
    ('QQQ_2023_06_1min.csv', '2023_06'),
    ('QQQ_2024_06_1min.csv', '2024_06 [OUT-OF-SAMPLE]'),
]

# Test different hold periods
hold_periods = [
    (1, "1 Day"),
    (2, "2 Days"),
    (3, "3 Days"),
    (5, "5 Days"),
]

for max_days, display_name in hold_periods:
    print(f"\n{'='*70}")
    print(f"HOLD PERIOD: {display_name} (Max {max_days * 390} minutes)")
    print(f"{'='*70}\n")
    
    all_trades = []
    
    for filename, month_name in months:
        data_path = Path(f'data/polygon_downloads/{filename}')
        if not data_path.exists():
            continue
        
        # Load and prepare data
        provider = CSVDataProvider(str(data_path))
        df_1min = provider.load_bars()
        df_1h = resample_to_timeframe(df_1min, '1h')
        
        # Detect ICT structures
        df_1min = label_sessions(df_1min)
        df_1min = add_session_highs_lows(df_1min)
        df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
        
        # Find signals
        signals = find_ict_confluence_signals(df_1min)
        
        # Backtest with multi-day holds
        trades = backtest_multiday_holds(df_1min, df_1h, signals, 
                                        target_pct=1.0, 
                                        max_hold_days=max_days)
        
        if len(trades) > 0:
            metrics = calculate_metrics(trades)
            print(f"{month_name:30s} {metrics['total_trades']:3d} trades, "
                  f"{metrics['target_hit_rate']:5.1f}% hit target, "
                  f"avg {metrics['avg_days_held']:.1f} days held, "
                  f"${metrics['total_pnl']:7.2f} P&L")
            all_trades.append(trades)
    
    # Combined results
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        metrics = calculate_metrics(combined)
        
        print(f"\n📊 COMBINED RESULTS:")
        print(f"   Total Trades: {metrics['total_trades']}")
        print(f"   TARGET HIT RATE: {metrics['target_hit_rate']:.1f}%")
        print(f"   Win Rate: {metrics['win_rate']:.1f}%")
        print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"   Total P&L: ${metrics['total_pnl']:.2f}")
        print(f"   Avg Days Held: {metrics['avg_days_held']:.1f}")
        print(f"   Avg 1H Swing: ${metrics['avg_swing_range']:.2f}")

print(f"\n{'='*70}\n")
