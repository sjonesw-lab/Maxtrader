#!/usr/bin/env python3
"""
Multi-Timeframe ICT Strategy - Final Version

Setup:
- 1-Hour timeframe: Swing highs/lows for TARGET calculation
- 1-Minute timeframe: ICT confluence (Sweep + Displacement + MSS) for ENTRY
- NO STOP LOSS (defined risk via options structures)
- Max hold: 60 minutes
- Entry: Next bar at open price after signal
- Exit: Target hit or 60-minute time exit
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
    """Find swing high/low on higher timeframe chart for target calculation."""
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
    """Find ICT confluence: Sweep + Displacement + MSS within 5 bars."""
    signals = []
    
    for i in range(len(df) - 5):
        # Bullish confluence
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long'
                })
        
        # Bearish confluence
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short'
                })
    
    return pd.DataFrame(signals)


def backtest_ict_mtf(df_1min, df_htf, signals, target_pct=0.75, max_hold_bars=60):
    """
    Backtest ICT strategy with higher timeframe swing targets.
    
    Args:
        df_1min: 1-minute bars for entry/exit
        df_htf: Higher timeframe bars for swing structure
        signals: ICT confluence signals
        target_pct: Percentage of swing to use as target (0.75 = 75%)
        max_hold_bars: Max hold time in minutes
    """
    trades = []
    last_exit_time = None
    
    for _, signal in signals.iterrows():
        # No overlapping positions
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Get HTF swing structure
        swing_data = find_swing_targets(df_htf, signal['timestamp'], lookback_bars=20)
        if not swing_data or swing_data['swing_range'] < 0.30:  # Min $0.30 swing
            continue
        
        # Entry: Next bar at open
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        entry_price = entry_bar['open']
        
        # Calculate target from HTF swing
        if signal['direction'] == 'long':
            target_price = swing_data['swing_low'] + (target_pct * swing_data['swing_range'])
        else:
            target_price = swing_data['swing_high'] - (target_pct * swing_data['swing_range'])
        
        # Skip if target too close
        target_distance = abs(target_price - entry_price)
        if target_distance < 0.15:  # Min $0.15 move
            continue
        
        # Exit window (60 bars = 60 minutes)
        exit_window = df_1min.loc[entry_idx:entry_idx + max_hold_bars]
        if len(exit_window) == 0:
            continue
        
        # Find exit (NO STOP LOSS)
        hit_target = False
        exit_price = None
        exit_time = None
        bars_held = 0
        
        for idx, bar in exit_window.iterrows():
            bars_held += 1
            
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
        'avg_swing_range': trades_df['swing_range'].mean()
    }


# Main backtest
print("\n" + "="*70)
print("MULTI-TIMEFRAME ICT STRATEGY BACKTEST")
print("="*70)
# Test files
months = [
    ('QQQ_2021_05_1min.csv', '2021_05'),
    ('QQQ_2022_04_1min.csv', '2022_04'),
    ('QQQ_2023_06_1min.csv', '2023_06'),
    ('QQQ_2024_06_1min.csv', '2024_06 [OUT-OF-SAMPLE]'),
]

# Test different timeframes for swing structure
timeframe_tests = [
    ('15min', '15-Minute'),
    ('1h', '1-Hour'),
]

for tf_key, tf_name in timeframe_tests:
    print(f"\n{'='*70}")
    print(f"SWING TIMEFRAME: {tf_name}")
    print(f"{'='*70}")
    print(f"  ✓ {tf_name} Swings: Swing highs/lows for TARGETS")
    print(f"  ✓ 1-Minute ICT: Sweep + Displacement + MSS for ENTRY")
    print(f"  ✓ NO STOP LOSS (defined risk via options)")
    print(f"  ✓ Entry: Next bar at open, Exit: Target or 60-min")
    
    # Test 75% and 100% targets
    for target_pct in [0.75, 1.00]:
        print(f"\n  Target: {int(target_pct*100)}% of {tf_name} Swing")
        print(f"  {'-'*66}")
        
        all_trades = []
        
        for filename, display_name in months:
            data_path = Path(f'data/polygon_downloads/{filename}')
            if not data_path.exists():
                continue
            
            # Load and prepare data
            provider = CSVDataProvider(str(data_path))
            df_1min = provider.load_bars()
            df_htf = resample_to_timeframe(df_1min, tf_key)
        
            # Detect ICT structures
            df_1min = label_sessions(df_1min)
            df_1min = add_session_highs_lows(df_1min)
            df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
            
            # Find signals
            signals = find_ict_confluence_signals(df_1min)
            
            # Backtest
            trades = backtest_ict_mtf(df_1min, df_htf, signals, target_pct=target_pct)
            
            if len(trades) > 0:
                metrics = calculate_metrics(trades)
                print(f"  {display_name:30s} {metrics['total_trades']:3d} trades, "
                      f"{metrics['target_hit_rate']:5.1f}% hit, "
                      f"${metrics['total_pnl']:7.2f}")
                all_trades.append(trades)
        
        # Combined results
        if all_trades:
            combined = pd.concat(all_trades, ignore_index=True)
            metrics = calculate_metrics(combined)
            
            print(f"\n  📊 COMBINED: {metrics['total_trades']} trades, "
                  f"{metrics['target_hit_rate']:.1f}% hit target, "
                  f"PF {metrics['profit_factor']:.2f}, "
                  f"P&L ${metrics['total_pnl']:.2f}")

print(f"\n{'='*70}\n")
