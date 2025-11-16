"""
Test crash-trend concept: Trade WITH the crash, not against it.

Concept:
- High Vol (VIX >30) = Directional crash environment
- Strategy: Short failed bounces, ride the crash down
- Entry: Price bounces to resistance → fails → short the rejection
- Stop: Above rejection high
- Target: Recent swing low or -1% move
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
import numpy as np

# Load March 2020 data (peak crash)
provider = CSVDataProvider('data/QQQ_1m_covid_2020.csv')
df_full = provider.load_bars()
df = df_full[
    (df_full['timestamp'] >= '2020-03-01') &
    (df_full['timestamp'] < '2020-04-01')  # Just March (worst crash)
].copy().reset_index(drop=True)

print("CRASH-TREND CONCEPT TEST")
print("=" * 80)
print(f"Data: March 2020, {len(df)} bars")
print()

# Simple trend-following logic
wins = 0
losses = 0
total_r = 0
signals = []

for i in range(100, len(df) - 120, 5):  # Sample every 5th bar
    # Calculate recent trend
    lookback = df.iloc[i-50:i]
    price_change = (df.iloc[i]['close'] - lookback['close'].iloc[0]) / lookback['close'].iloc[0]
    
    # Only trade in downtrend
    if price_change > -0.02:  # Not trending down enough
        continue
    
    # Look for failed bounce
    bar = df.iloc[i]
    prev_bars = df.iloc[i-10:i]
    
    # Recent high = resistance
    recent_high = prev_bars['high'].max()
    
    # Entry: Price approaches recent high but rejects (fails to break)
    if bar['high'] >= recent_high * 0.998 and bar['close'] < recent_high * 0.995:
        # Failed bounce at resistance
        entry = bar['close']
        stop = recent_high * 1.003  # Just above resistance
        target = entry * 0.990  # 1% down (conservative)
        
        risk = stop - entry
        reward = entry - target
        rr = reward / risk if risk > 0 else 0
        
        if rr < 1.5:
            continue
        
        # Check outcome
        future = df.iloc[i:i+120]
        
        tp_hit = (future['low'] <= target).any()
        sl_hit = (future['high'] >= stop).any()
        
        if tp_hit and not sl_hit:
            wins += 1
            total_r += rr
        elif sl_hit:
            losses += 1
            total_r -= 1.0
        
        signals.append({
            'timestamp': bar['timestamp'],
            'entry': entry,
            'target': target,
            'stop': stop,
            'rr': rr,
            'win': tp_hit and not sl_hit
        })

total_trades = wins + losses
if total_trades > 0:
    wr = wins / total_trades
    avg_r = total_r / total_trades
    pf = (wins * 2.0) / losses if losses > 0 else 999  # Assume avg 2R wins
    
    print("CRASH-TREND RESULTS:")
    print("-" * 80)
    print(f"Total Signals: {len(signals)}")
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate: {wr*100:.1f}%")
    print(f"Avg R: {avg_r:.2f}R")
    print(f"Profit Factor: {pf:.2f}")
    print()
    
    if wr >= 0.60 and avg_r >= 1.5 and pf >= 1.5:
        print("✅ SUCCESS! Crash-trend meets all targets!")
        print()
        print("STRATEGY LOGIC:")
        print("  1. Confirm downtrend (price down >2% from 50 bars ago)")
        print("  2. Identify resistance (recent 10-bar high)")
        print("  3. Wait for failed bounce (price touches resistance, rejects)")
        print("  4. SHORT on rejection close")
        print("  5. Stop: Just above resistance")
        print("  6. Target: 1% down")
        print()
        print("This trades WITH the crash, not against it!")
    elif wr >= 0.50 and avg_r >= 1.0:
        print("✓ PROMISING - Needs tuning but better than sweep-reclaim")
        print()
        print(f"vs Sweep-Reclaim: {wr*100:.1f}% WR vs 14.7% WR")
        print(f"vs Sweep-Reclaim: {avg_r:.2f}R vs -0.41R")
        print()
        print("RECOMMENDATION: Pursue crash-trend redesign")
    else:
        print("⚠️  Not significantly better than sweep-reclaim")
else:
    print("No trades generated")
    
print()
print("SAMPLE SIGNALS (first 5):")
print("-" * 80)
for i, sig in enumerate(signals[:5], 1):
    outcome = "WIN" if sig['win'] else "LOSS"
    print(f"{i}. {sig['timestamp']} | {outcome}")
    print(f"   Entry: ${sig['entry']:.2f}, Target: ${sig['target']:.2f}, Stop: ${sig['stop']:.2f}, R:R: {sig['rr']:.2f}:1")
