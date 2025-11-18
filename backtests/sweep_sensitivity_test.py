#!/usr/bin/env python3
"""
Test how relaxing sweep detection affects profitability and drawdown.
Compare: Strict (exact sweep) vs Relaxed (near-sweep) vs Very Relaxed (proximity-based)
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


def detect_relaxed_sweeps(df, tolerance_pct=0.5):
    """
    Relaxed sweep detection: Accept "near sweeps" within tolerance.
    
    Args:
        df: DataFrame with session highs/lows
        tolerance_pct: % tolerance (0.5 = 0.5% from level)
    """
    df = df.copy()
    df['sweep_bullish_relaxed'] = False
    df['sweep_bearish_relaxed'] = False
    
    for idx in df.index:
        row = df.loc[idx]
        
        # Bullish: near or below Asia/London low
        if pd.notna(row['asia_low']):
            distance_pct = abs(row['low'] - row['asia_low']) / row['asia_low'] * 100
            if distance_pct <= tolerance_pct or row['low'] < row['asia_low']:
                if row['close'] > row['asia_low'] * (1 - tolerance_pct/100):
                    df.at[idx, 'sweep_bullish_relaxed'] = True
        
        if pd.notna(row['london_low']):
            distance_pct = abs(row['low'] - row['london_low']) / row['london_low'] * 100
            if distance_pct <= tolerance_pct or row['low'] < row['london_low']:
                if row['close'] > row['london_low'] * (1 - tolerance_pct/100):
                    df.at[idx, 'sweep_bullish_relaxed'] = True
        
        # Bearish: near or above Asia/London high
        if pd.notna(row['asia_high']):
            distance_pct = abs(row['high'] - row['asia_high']) / row['asia_high'] * 100
            if distance_pct <= tolerance_pct or row['high'] > row['asia_high']:
                if row['close'] < row['asia_high'] * (1 + tolerance_pct/100):
                    df.at[idx, 'sweep_bearish_relaxed'] = True
        
        if pd.notna(row['london_high']):
            distance_pct = abs(row['high'] - row['london_high']) / row['london_high'] * 100
            if distance_pct <= tolerance_pct or row['high'] > row['london_high']:
                if row['close'] < row['london_high'] * (1 + tolerance_pct/100):
                    df.at[idx, 'sweep_bearish_relaxed'] = True
    
    return df


def find_signals(df, sweep_mode='strict'):
    """Find ICT confluence with different sweep modes."""
    signals = []
    
    sweep_bull_col = 'sweep_bullish' if sweep_mode == 'strict' else 'sweep_bullish_relaxed'
    sweep_bear_col = 'sweep_bearish' if sweep_mode == 'strict' else 'sweep_bearish_relaxed'
    
    for i in range(len(df) - 5):
        if df.iloc[i][sweep_bull_col]:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
        
        if df.iloc[i][sweep_bear_col]:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
    
    return pd.DataFrame(signals)


def backtest_signals(df, signals, starting_capital=25000, risk_pct=5.0):
    """Simple backtest with 5x ATR targets."""
    if len(signals) == 0:
        return pd.DataFrame()
    
    trades = []
    account_balance = starting_capital
    
    for _, signal in signals.iterrows():
        entry_mask = df['timestamp'] > signal['timestamp']
        if not entry_mask.any():
            continue
        
        entry_idx = df[entry_mask].index[0]
        entry_price = df.loc[entry_idx, 'open']
        
        atr_value = signal.get('atr', 0.5)
        target_distance = 5.0 * atr_value
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
        else:
            target_price = entry_price - target_distance
        
        # 60-bar hold window
        exit_window = df.loc[entry_idx:entry_idx + 60]
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        for idx, bar in exit_window.iterrows():
            if signal['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                break
            elif signal['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                break
        
        # Simplified P&L (premium paid vs intrinsic value at target)
        premium_paid = 200  # Rough ATM 0DTE estimate
        pnl = (target_distance * 100 - premium_paid) if hit_target else -premium_paid
        
        account_balance += pnl
        trades.append({
            'hit_target': hit_target,
            'pnl': pnl,
            'balance': account_balance
        })
    
    return pd.DataFrame(trades)


def analyze_performance(trades_df, label, starting_capital=25000):
    """Calculate key metrics."""
    if len(trades_df) == 0:
        return {
            'label': label,
            'total_trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'return_pct': 0,
            'max_drawdown_pct': 0,
            'avg_win': 0,
            'avg_loss': 0
        }
    
    equity_curve = trades_df['balance'].values
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_dd = drawdown.min()
    max_dd_pct = (max_dd / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    
    total_pnl = equity_curve[-1] - starting_capital
    return_pct = (total_pnl / starting_capital) * 100
    
    return {
        'label': label,
        'total_trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df) * 100) if len(trades_df) > 0 else 0,
        'total_pnl': total_pnl,
        'return_pct': return_pct,
        'max_drawdown_pct': max_dd_pct,
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("SWEEP SENSITIVITY ANALYSIS")
print("="*80)
print("Testing: How does relaxing sweep detection affect results?")
print("="*80)

# Load recent data (Oct 2025)
data_path = Path('data/polygon_downloads/QQQ_2025_10_1min.csv')

if not data_path.exists():
    print(f"\n❌ Data file not found: {data_path}")
    print("   Need recent data to test sweep sensitivity")
    sys.exit(1)

provider = CSVDataProvider(str(data_path))
df = provider.load_bars()

print(f"\n✅ Loaded {len(df)} bars from October 2025")

# Prepare data
df = calculate_atr(df, period=14)
df = label_sessions(df)
df = add_session_highs_lows(df)
df = detect_all_structures(df, displacement_threshold=1.0)

# Test different sweep modes
print("\n" + "="*80)
print("MODE 1: STRICT (Current System)")
print("="*80)
print("Requires: Exact sweep of Asia/London high/low")

signals_strict = find_signals(df, sweep_mode='strict')
trades_strict = backtest_signals(df, signals_strict)
metrics_strict = analyze_performance(trades_strict, "STRICT")

print(f"Signals Found: {len(signals_strict)}")
print(f"Trades:        {metrics_strict['total_trades']}")
print(f"Win Rate:      {metrics_strict['win_rate']:.1f}%")
print(f"Total P&L:     ${metrics_strict['total_pnl']:,.2f}")
print(f"Return:        {metrics_strict['return_pct']:.2f}%")
print(f"Max Drawdown:  {metrics_strict['max_drawdown_pct']:.2f}%")

# Test relaxed mode
print("\n" + "="*80)
print("MODE 2: RELAXED")
print("="*80)
print("Requires: Within 0.5% of session high/low")

df = detect_relaxed_sweeps(df, tolerance_pct=0.5)
signals_relaxed = find_signals(df, sweep_mode='relaxed')
trades_relaxed = backtest_signals(df, signals_relaxed)
metrics_relaxed = analyze_performance(trades_relaxed, "RELAXED")

print(f"Signals Found: {len(signals_relaxed)}")
print(f"Trades:        {metrics_relaxed['total_trades']}")
print(f"Win Rate:      {metrics_relaxed['win_rate']:.1f}%")
print(f"Total P&L:     ${metrics_relaxed['total_pnl']:,.2f}")
print(f"Return:        {metrics_relaxed['return_pct']:.2f}%")
print(f"Max Drawdown:  {metrics_relaxed['max_drawdown_pct']:.2f}%")

# Comparison
print("\n" + "="*80)
print("COMPARISON & RECOMMENDATION")
print("="*80)

if metrics_strict['total_trades'] == 0 and metrics_relaxed['total_trades'] == 0:
    print("❌ Both modes produced ZERO trades")
    print("   → Session highs/lows not being set properly")
    print("   → Check session labeling logic")
elif metrics_strict['total_trades'] == 0:
    print(f"✅ Relaxed mode found {metrics_relaxed['total_trades']} trades")
    print(f"   Win Rate: {metrics_relaxed['win_rate']:.1f}%")
    print(f"   Drawdown: {metrics_relaxed['max_drawdown_pct']:.2f}%")
    print("\n💡 RECOMMENDATION:")
    if metrics_relaxed['win_rate'] >= 50 and abs(metrics_relaxed['max_drawdown_pct']) < 10:
        print("   → SWITCH to relaxed mode")
        print("   → Maintains quality while increasing trade frequency")
    else:
        print("   → KEEP strict mode")
        print("   → Relaxed trades show poor quality metrics")
else:
    delta_trades = metrics_relaxed['total_trades'] - metrics_strict['total_trades']
    delta_winrate = metrics_relaxed['win_rate'] - metrics_strict['win_rate']
    delta_dd = metrics_relaxed['max_drawdown_pct'] - metrics_strict['max_drawdown_pct']
    
    print(f"Trade Increase:  +{delta_trades} ({delta_trades/max(1, metrics_strict['total_trades'])*100:.0f}%)")
    print(f"Win Rate Change: {delta_winrate:+.1f}%")
    print(f"Drawdown Change: {delta_dd:+.1f}%")
    
    print("\n💡 RECOMMENDATION:")
    if delta_winrate < -5 or delta_dd < -3:
        print("   → KEEP strict mode")
        print("   → Relaxing reduces win rate or increases drawdown")
    elif delta_trades > 3 and delta_winrate > -3:
        print("   → CONSIDER relaxed mode")
        print("   → More trades with acceptable quality degradation")
    else:
        print("   → KEEP strict mode")
        print("   → Minimal benefit from relaxing")

print("\n" + "="*80 + "\n")
