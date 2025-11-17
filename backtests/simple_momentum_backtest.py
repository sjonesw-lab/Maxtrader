#!/usr/bin/env python3
"""
Simple, transparent momentum strategy backtest.

Strategy:
- 3+ consecutive Renko bricks in same direction = momentum signal
- Enter on NEXT bar at market open (realistic entry execution)
- Target: 2x brick size (2:1 RR)
- Stop: 1x brick size
- Hold max 60 minutes
- ONE POSITION AT A TIME (no overlapping trades)

Execution Assumptions:
- Entry: Next bar's open price after signal
- Exit: Stops/targets checked from entry bar forward
- No overlapping positions (skip signals during active trades)

No complex filters, no overfitting - just clean momentum trades.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_provider import CSVDataProvider
from engine.renko import build_renko


def generate_simple_signals(df: pd.DataFrame, renko_df: pd.DataFrame, brick_size: float):
    """Generate momentum signals from Renko bricks."""
    signals = []
    
    # Track consecutive brick direction
    consecutive_up = 0
    consecutive_down = 0
    
    for i in range(len(renko_df)):
        brick = renko_df.iloc[i]
        
        if brick['direction'] == 1:  # Up brick
            consecutive_up += 1
            consecutive_down = 0
        else:  # Down brick
            consecutive_down += 1
            consecutive_up = 0
        
        # Signal after 3+ consecutive bricks
        if consecutive_up >= 3:
            # Long signal
            timestamp = brick['timestamp']
            entry_price = brick['brick_close']
            
            signals.append({
                'timestamp': timestamp,
                'direction': 'long',
                'entry_price': entry_price,
                'target_price': entry_price + (2 * brick_size),  # 2:1 RR
                'stop_price': entry_price - brick_size,
                'brick_count': consecutive_up
            })
            
        elif consecutive_down >= 3:
            # Short signal
            timestamp = brick['timestamp']
            entry_price = brick['brick_close']
            
            signals.append({
                'timestamp': timestamp,
                'direction': 'short',
                'entry_price': entry_price,
                'target_price': entry_price - (2 * brick_size),  # 2:1 RR
                'stop_price': entry_price + brick_size,
                'brick_count': consecutive_down
            })
    
    return pd.DataFrame(signals)


def backtest_signals(df_1min: pd.DataFrame, signals_df: pd.DataFrame, max_hold_bars: int = 60):
    """Execute trades and track performance."""
    trades = []
    last_exit_time = None
    
    for _, signal in signals_df.iterrows():
        # Skip if signal occurs before previous trade exited (no overlapping trades)
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Find NEXT bar after signal for entry
        entry_mask = df_1min['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
            
        entry_idx = df_1min[entry_mask].index[0]
        entry_bar = df_1min.loc[entry_idx]
        
        # Enter at market (next bar open price)
        actual_entry_price = entry_bar['open']
        
        # Recalculate target and stop from actual entry price
        brick_size = signal['target_price'] - signal['entry_price'] if signal['direction'] == 'long' else signal['entry_price'] - signal['target_price']
        brick_size = brick_size / 2  # Target was 2x brick size
        
        if signal['direction'] == 'long':
            actual_target = actual_entry_price + (2 * brick_size)
            actual_stop = actual_entry_price - brick_size
        else:
            actual_target = actual_entry_price - (2 * brick_size)
            actual_stop = actual_entry_price + brick_size
        
        # Define exit window (start from entry bar itself to check immediate exit)
        exit_window = df_1min.loc[entry_idx:entry_idx + max_hold_bars]
        
        if len(exit_window) == 0:
            continue
        
        # Track trade
        trade = {
            'entry_time': entry_bar['timestamp'],
            'entry_price': actual_entry_price,
            'direction': signal['direction'],
            'target': actual_target,
            'stop': actual_stop,
            'brick_count': signal['brick_count']
        }
        
        # Check each bar for exit
        hit_target = False
        hit_stop = False
        exit_price = None
        exit_time = None
        bars_held = 0
        
        for idx, bar in exit_window.iterrows():
            bars_held += 1
            
            if signal['direction'] == 'long':
                # Check target
                if bar['high'] >= actual_target:
                    hit_target = True
                    exit_price = actual_target
                    exit_time = bar['timestamp']
                    break
                # Check stop
                if bar['low'] <= actual_stop:
                    hit_stop = True
                    exit_price = actual_stop
                    exit_time = bar['timestamp']
                    break
            else:  # short
                # Check target
                if bar['low'] <= actual_target:
                    hit_target = True
                    exit_price = actual_target
                    exit_time = bar['timestamp']
                    break
                # Check stop
                if bar['high'] >= actual_stop:
                    hit_stop = True
                    exit_price = actual_stop
                    exit_time = bar['timestamp']
                    break
        
        # If no exit, close at end of window
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        # Calculate P&L
        if signal['direction'] == 'long':
            pnl = exit_price - actual_entry_price
        else:
            pnl = actual_entry_price - exit_price
        
        trade.update({
            'exit_time': exit_time,
            'exit_price': exit_price,
            'bars_held': bars_held,
            'hit_target': hit_target,
            'hit_stop': hit_stop,
            'pnl': pnl,
            'pnl_pct': (pnl / actual_entry_price) * 100
        })
        
        trades.append(trade)
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_metrics(trades_df: pd.DataFrame):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'total_pnl': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0
        }
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] < 0]
    
    total_wins = winners['pnl'].sum() if len(winners) > 0 else 0
    total_losses = abs(losers['pnl'].sum()) if len(losers) > 0 else 0
    
    metrics = {
        'total_trades': len(trades_df),
        'winners': len(winners),
        'losers': len(losers),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'profit_factor': total_wins / total_losses if total_losses > 0 else 0,
        'total_pnl': trades_df['pnl'].sum(),
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
        'avg_bars_held': trades_df['bars_held'].mean(),
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
        'stop_hit_rate': (trades_df['hit_stop'].sum() / len(trades_df)) * 100
    }
    
    return metrics


def run_backtest(data_file: str):
    """Run simple momentum backtest."""
    print(f"\n{'='*70}")
    print(f"📊 SIMPLE MOMENTUM BACKTEST: {data_file}")
    print(f"{'='*70}")
    
    # Load data
    data_path = Path(f'data/polygon_downloads/{data_file}')
    provider = CSVDataProvider(str(data_path))
    df_1min = provider.load_bars()
    
    print(f"Loaded {len(df_1min):,} bars")
    print(f"Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")
    
    # Build Renko
    k_value = 3.0  # Moderate brick size
    renko_df = build_renko(df_1min, mode="atr", k=k_value, atr_period=14)
    brick_size = renko_df['brick_size'].iloc[0]
    
    print(f"Built {len(renko_df)} Renko bricks (size: ${brick_size:.2f}, k={k_value})")
    
    # Generate signals
    signals_df = generate_simple_signals(df_1min, renko_df, brick_size)
    print(f"Generated {len(signals_df)} momentum signals")
    
    if len(signals_df) == 0:
        print("No signals generated")
        return None
    
    # Backtest
    trades_df = backtest_signals(df_1min, signals_df, max_hold_bars=60)
    print(f"Executed {len(trades_df)} trades")
    
    # Calculate metrics
    metrics = calculate_metrics(trades_df)
    
    # Print results
    print(f"\n📈 RESULTS:")
    print(f"   Total Trades: {metrics['total_trades']}")
    print(f"   Winners: {metrics['winners']}")
    print(f"   Losers: {metrics['losers']}")
    print(f"   Win Rate: {metrics['win_rate']:.1f}%")
    print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"   Total P&L: ${metrics['total_pnl']:,.2f}")
    print(f"   Avg Win: ${metrics['avg_win']:.2f}")
    print(f"   Avg Loss: ${metrics['avg_loss']:.2f}")
    print(f"   Avg Bars Held: {metrics['avg_bars_held']:.1f}")
    print(f"   Target Hit: {metrics['target_hit_rate']:.1f}%")
    print(f"   Stop Hit: {metrics['stop_hit_rate']:.1f}%")
    
    return metrics


if __name__ == '__main__':
    print("\n" + "="*70)
    print("🎯 SIMPLE MOMENTUM STRATEGY - VERIFIED BACKTEST")
    print("="*70)
    print("\nStrategy Rules:")
    print("  - Entry: 3+ consecutive Renko bricks (momentum)")
    print("  - Target: 2x brick size (2:1 RR)")
    print("  - Stop: 1x brick size")
    print("  - Max hold: 60 minutes")
    print("  - No filters, no optimization\n")
    
    # Test on 3 months
    months = [
        'QQQ_2021_05_1min.csv',
        'QQQ_2022_04_1min.csv',
        'QQQ_2023_06_1min.csv'
    ]
    
    all_metrics = []
    
    for month_file in months:
        try:
            metrics = run_backtest(month_file)
            if metrics:
                metrics['month'] = month_file.replace('QQQ_', '').replace('_1min.csv', '')
                all_metrics.append(metrics)
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    if all_metrics:
        print(f"\n{'='*70}")
        print("📊 COMBINED RESULTS (3 MONTHS)")
        print(f"{'='*70}")
        
        df = pd.DataFrame(all_metrics)
        total_trades = df['total_trades'].sum()
        total_winners = df['winners'].sum()
        total_losers = df['losers'].sum()
        total_pnl = df['total_pnl'].sum()
        avg_win_rate = df['win_rate'].mean()
        avg_profit_factor = df['profit_factor'].mean()
        
        print(f"Total Trades: {total_trades}")
        print(f"Total Winners: {total_winners}")
        print(f"Total Losers: {total_losers}")
        print(f"Overall Win Rate: {(total_winners/total_trades)*100:.1f}%")
        print(f"Avg Profit Factor: {avg_profit_factor:.2f}")
        print(f"Total P&L: ${total_pnl:,.2f}")
        
        print(f"\nPer Month:")
        for _, row in df.iterrows():
            print(f"  {row['month']}: {row['total_trades']} trades, "
                  f"{row['win_rate']:.1f}% WR, ${row['total_pnl']:,.2f} P&L")
        
        print(f"\n{'='*70}\n")
