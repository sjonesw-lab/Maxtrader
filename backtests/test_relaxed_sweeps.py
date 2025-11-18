#!/usr/bin/env python3
"""
Backtest relaxed sweep detection vs strict mode.
Last 3 months (Aug, Sep, Oct 2025) with 75/25 allocation rule.
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_displacement, detect_mss


def calculate_atr(df, period=14):
    """Calculate ATR."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def detect_sweeps_strict(df):
    """STRICT: Exact sweep of session levels."""
    df = df.copy()
    df['sweep_bullish'] = False
    df['sweep_bearish'] = False
    
    for idx in df.index:
        row = df.loc[idx]
        
        if pd.notna(row['asia_low']) and row['low'] < row['asia_low'] and row['close'] > row['asia_low']:
            df.at[idx, 'sweep_bullish'] = True
        elif pd.notna(row['london_low']) and row['low'] < row['london_low'] and row['close'] > row['london_low']:
            df.at[idx, 'sweep_bullish'] = True
        
        if pd.notna(row['asia_high']) and row['high'] > row['asia_high'] and row['close'] < row['asia_high']:
            df.at[idx, 'sweep_bearish'] = True
        elif pd.notna(row['london_high']) and row['high'] > row['london_high'] and row['close'] < row['london_high']:
            df.at[idx, 'sweep_bearish'] = True
    
    return df


def detect_sweeps_relaxed(df, tolerance_pct=0.3):
    """RELAXED: Accept near-sweeps within tolerance."""
    df = df.copy()
    df['sweep_bullish'] = False
    df['sweep_bearish'] = False
    
    for idx in df.index:
        row = df.loc[idx]
        
        # Bullish: near or below Asia/London low
        if pd.notna(row['asia_low']):
            distance_pct = abs(row['low'] - row['asia_low']) / row['asia_low'] * 100
            if distance_pct <= tolerance_pct or row['low'] < row['asia_low']:
                if row['close'] > row['asia_low'] * (1 - tolerance_pct/100):
                    df.at[idx, 'sweep_bullish'] = True
        
        if pd.notna(row['london_low']):
            distance_pct = abs(row['low'] - row['london_low']) / row['london_low'] * 100
            if distance_pct <= tolerance_pct or row['low'] < row['london_low']:
                if row['close'] > row['london_low'] * (1 - tolerance_pct/100):
                    df.at[idx, 'sweep_bullish'] = True
        
        # Bearish: near or above Asia/London high
        if pd.notna(row['asia_high']):
            distance_pct = abs(row['high'] - row['asia_high']) / row['asia_high'] * 100
            if distance_pct <= tolerance_pct or row['high'] > row['asia_high']:
                if row['close'] < row['asia_high'] * (1 + tolerance_pct/100):
                    df.at[idx, 'sweep_bearish'] = True
        
        if pd.notna(row['london_high']):
            distance_pct = abs(row['high'] - row['london_high']) / row['london_high'] * 100
            if distance_pct <= tolerance_pct or row['high'] > row['london_high']:
                if row['close'] < row['london_high'] * (1 + tolerance_pct/100):
                    df.at[idx, 'sweep_bearish'] = True
    
    return df


def find_signals(df):
    """Find ICT confluence signals (sweep + displacement + MSS within 5 bars)."""
    signals = []
    
    for i in range(len(df) - 5):
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
        
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
    
    return signals


def backtest_75_25_strategy(df, signals, starting_capital=25000, conservative_risk=3.0, aggressive_risk=4.0):
    """
    Backtest with 75/25 allocation rule:
    - Conservative: 100% longs (3% risk)
    - Aggressive: 75% longs + 25% spreads (4% risk)
    """
    trades = []
    balance = starting_capital
    
    for signal in signals:
        entry_idx = signal['index'] + 1  # Next bar
        if entry_idx >= len(df):
            continue
        
        entry_price = df.iloc[entry_idx]['open']
        atr = signal['atr']
        target_distance = 5.0 * atr
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
        else:
            target_price = entry_price - target_distance
        
        # 60-bar hold window
        exit_window_end = min(entry_idx + 60, len(df) - 1)
        exit_window = df.iloc[entry_idx:exit_window_end+1]
        
        if len(exit_window) == 0:
            continue
        
        # Check if target hit
        hit_target = False
        for idx in range(len(exit_window)):
            bar = exit_window.iloc[idx]
            if signal['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                break
            elif signal['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                break
        
        # Conservative (100% longs, 3% risk)
        conservative_risk_dollars = balance * (conservative_risk / 100)
        conservative_premium = 200  # Simplified ATM 0DTE
        conservative_contracts = max(1, int(conservative_risk_dollars / conservative_premium))
        conservative_cost = conservative_contracts * conservative_premium
        
        if hit_target:
            conservative_pnl = (target_distance * 100 * conservative_contracts) - conservative_cost
        else:
            conservative_pnl = -conservative_cost
        
        # Aggressive (75% longs, 25% spreads, 4% risk)
        aggressive_risk_dollars = balance * (aggressive_risk / 100)
        
        # 75% to longs
        long_allocation = aggressive_risk_dollars * 0.75
        long_contracts = max(1, int(long_allocation / conservative_premium))
        long_cost = long_contracts * conservative_premium
        
        # 25% to spreads (half the cost, lower payout)
        spread_allocation = aggressive_risk_dollars * 0.25
        spread_cost_per = conservative_premium * 0.5  # Spread costs less
        spread_contracts = max(1, int(spread_allocation / spread_cost_per))
        spread_cost = spread_contracts * spread_cost_per
        
        total_aggressive_cost = long_cost + spread_cost
        
        if hit_target:
            # Longs pay full distance
            long_payout = target_distance * 100 * long_contracts
            # Spreads capped at $2 width (typical)
            spread_payout = min(target_distance, 2.0) * 100 * spread_contracts
            aggressive_pnl = (long_payout + spread_payout) - total_aggressive_cost
        else:
            aggressive_pnl = -total_aggressive_cost
        
        # Average the two strategies
        combined_pnl = (conservative_pnl + aggressive_pnl) / 2
        balance += combined_pnl
        
        trades.append({
            'timestamp': signal['timestamp'],
            'direction': signal['direction'],
            'hit_target': hit_target,
            'conservative_pnl': conservative_pnl,
            'aggressive_pnl': aggressive_pnl,
            'combined_pnl': combined_pnl,
            'balance': balance
        })
    
    return pd.DataFrame(trades), balance


def analyze_results(trades_df, label, starting_capital=25000):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return {
            'mode': label,
            'trades': 0,
            'win_rate': 0,
            'total_return': 0,
            'return_pct': 0,
            'max_dd_pct': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'profit_factor': 0
        }
    
    equity = trades_df['balance'].values
    running_max = np.maximum.accumulate(equity)
    drawdown = equity - running_max
    max_dd = drawdown.min()
    max_dd_pct = (max_dd / starting_capital) * 100
    
    winners = trades_df[trades_df['combined_pnl'] > 0]
    losers = trades_df[trades_df['combined_pnl'] <= 0]
    
    total_return = equity[-1] - starting_capital
    return_pct = (total_return / starting_capital) * 100
    
    profit_factor = 0
    if len(losers) > 0 and losers['combined_pnl'].sum() != 0:
        profit_factor = abs(winners['combined_pnl'].sum() / losers['combined_pnl'].sum())
    
    return {
        'mode': label,
        'trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df) * 100) if len(trades_df) > 0 else 0,
        'total_return': total_return,
        'return_pct': return_pct,
        'max_dd_pct': max_dd_pct,
        'avg_win': winners['combined_pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['combined_pnl'].mean() if len(losers) > 0 else 0,
        'profit_factor': profit_factor,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df) * 100) if len(trades_df) > 0 else 0
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("RELAXED SWEEP BACKTEST - LAST 3 MONTHS")
print("="*80)
print("Testing: 0.3% tolerance vs Strict mode")
print("Strategy: 75% Longs + 25% Spreads (Aggressive) + 100% Longs (Conservative)")
print("="*80)

# Load last 3 months
months = [
    ('2025', '08', 'August'),
    ('2025', '09', 'September'),
    ('2025', '10', 'October')
]

all_data = []
for year, month, name in months:
    path = Path(f'data/polygon_downloads/QQQ_{year}_{month}_1min.csv')
    if path.exists():
        provider = CSVDataProvider(str(path))
        df = provider.load_bars()
        all_data.append(df)
        print(f"✓ Loaded {name} 2025: {len(df)} bars")

if not all_data:
    print("\n❌ No data found!")
    sys.exit(1)

df_all = pd.concat(all_data, ignore_index=True)
print(f"\n✅ Total: {len(df_all)} bars across 3 months")

# Prepare base data
df_all = calculate_atr(df_all, period=14)
df_all = label_sessions(df_all)
df_all = add_session_highs_lows(df_all)

# Test STRICT mode
print("\n" + "="*80)
print("MODE 1: STRICT (Current System)")
print("="*80)

df_strict = detect_sweeps_strict(df_all)
df_strict = detect_displacement(df_strict, threshold=1.0)
df_strict = detect_mss(df_strict)

signals_strict = find_signals(df_strict)
print(f"Signals found: {len(signals_strict)}")

trades_strict, final_strict = backtest_75_25_strategy(df_strict, signals_strict)
metrics_strict = analyze_results(trades_strict, "STRICT")

print(f"Total Trades:    {metrics_strict['trades']}")
print(f"Win Rate:        {metrics_strict['win_rate']:.1f}%")
print(f"Target Hit Rate: {metrics_strict['target_hit_rate']:.1f}%")
print(f"Total Return:    ${metrics_strict['total_return']:,.2f} ({metrics_strict['return_pct']:.2f}%)")
print(f"Max Drawdown:    {metrics_strict['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_strict['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_strict['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_strict['avg_loss']:.2f}")

# Test RELAXED mode
print("\n" + "="*80)
print("MODE 2: RELAXED (0.3% Tolerance)")
print("="*80)

df_relaxed = detect_sweeps_relaxed(df_all, tolerance_pct=0.3)
df_relaxed = detect_displacement(df_relaxed, threshold=1.0)
df_relaxed = detect_mss(df_relaxed)

signals_relaxed = find_signals(df_relaxed)
print(f"Signals found: {len(signals_relaxed)}")

trades_relaxed, final_relaxed = backtest_75_25_strategy(df_relaxed, signals_relaxed)
metrics_relaxed = analyze_results(trades_relaxed, "RELAXED")

print(f"Total Trades:    {metrics_relaxed['trades']}")
print(f"Win Rate:        {metrics_relaxed['win_rate']:.1f}%")
print(f"Target Hit Rate: {metrics_relaxed['target_hit_rate']:.1f}%")
print(f"Total Return:    ${metrics_relaxed['total_return']:,.2f} ({metrics_relaxed['return_pct']:.2f}%)")
print(f"Max Drawdown:    {metrics_relaxed['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_relaxed['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_relaxed['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_relaxed['avg_loss']:.2f}")

# COMPARISON
print("\n" + "="*80)
print("COMPARISON & VERDICT")
print("="*80)

delta_trades = metrics_relaxed['trades'] - metrics_strict['trades']
delta_wr = metrics_relaxed['win_rate'] - metrics_strict['win_rate']
delta_return = metrics_relaxed['return_pct'] - metrics_strict['return_pct']
delta_dd = metrics_relaxed['max_dd_pct'] - metrics_strict['max_dd_pct']

print(f"Trade Count:     {metrics_strict['trades']} → {metrics_relaxed['trades']} ({delta_trades:+d})")
print(f"Win Rate:        {metrics_strict['win_rate']:.1f}% → {metrics_relaxed['win_rate']:.1f}% ({delta_wr:+.1f}%)")
print(f"3-Month Return:  {metrics_strict['return_pct']:.2f}% → {metrics_relaxed['return_pct']:.2f}% ({delta_return:+.2f}%)")
print(f"Max Drawdown:    {metrics_strict['max_dd_pct']:.2f}% → {metrics_relaxed['max_dd_pct']:.2f}% ({delta_dd:+.2f}%)")

print("\n" + "="*80)
print("VERDICT")
print("="*80)

if metrics_strict['trades'] == 0:
    print("❌ STRICT MODE: ZERO TRADES (0% return guaranteed)")
    print("✅ RELAXED MODE: Switch immediately")
elif metrics_relaxed['return_pct'] > metrics_strict['return_pct'] * 1.5:
    print("✅ RELAXED MODE WINS")
    print(f"   → {delta_return:+.1f}% better returns")
    print(f"   → Worth the {abs(delta_dd):.1f}% drawdown increase")
elif delta_return > 0 and delta_dd < 5:
    print("✅ RELAXED MODE RECOMMENDED")
    print(f"   → More profits with acceptable risk")
else:
    print("⚠️  KEEP STRICT MODE")
    print(f"   → Quality over quantity pays off")

print("="*80 + "\n")
