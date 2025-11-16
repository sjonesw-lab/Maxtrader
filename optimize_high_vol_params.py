"""
Grid search to find optimal High Vol parameters.

Target: WR ≥60%, Avg R ≥1.5, PF ≥1.5
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe

# Load data
provider = CSVDataProvider('data/QQQ_1m_covid_2020.csv')
df_full = provider.load_bars()
df = df_full[
    (df_full['timestamp'] >= '2020-03-01') &
    (df_full['timestamp'] < '2020-05-01')
].copy().reset_index(drop=True)

df_daily = resample_to_timeframe(df, '1d')
vix = calculate_vix_proxy(df_daily, lookback=20)

print("GRID SEARCH: High Vol Parameters")
print("=" * 80)
print()

# Test combinations
targets = [0.004, 0.005, 0.006, 0.0075]  # 0.4%, 0.5%, 0.6%, 0.75%
stops = [0.0025, 0.003, 0.0035]  # 0.25%, 0.3%, 0.35%

results = []

for target_pct in targets:
    for stop_pct in stops:
        # Calculate expected R:R
        rr = target_pct / stop_pct
        
        # Quick simulation: check hit rates
        wins = 0
        losses = 0
        total_r = 0
        
        for i in range(0, len(df) - 120, 10):  # Sample every 10th bar
            entry = df.iloc[i]['close']
            target_long = entry * (1 + target_pct)
            stop_long = entry * (1 - stop_pct)
            
            future = df.iloc[i:i+120]
            
            # Check long setup
            tp_hit = (future['high'] >= target_long).any()
            sl_hit = (future['low'] <= stop_long).any()
            
            if tp_hit and not sl_hit:
                wins += 1
                total_r += rr
            elif sl_hit:
                losses += 1
                total_r -= 1.0
        
        total_trades = wins + losses
        if total_trades == 0:
            continue
        
        wr = wins / total_trades
        avg_r = total_r / total_trades
        pf = (wins * rr) / losses if losses > 0 else 999
        
        results.append({
            'target%': target_pct * 100,
            'stop%': stop_pct * 100,
            'R:R': rr,
            'WR': wr,
            'Avg_R': avg_r,
            'PF': pf,
            'trades': total_trades
        })

# Sort by best overall score
df_results = pd.DataFrame(results)
df_results['score'] = df_results['WR'] * df_results['Avg_R'] * (df_results['PF'] / 2)
df_results = df_results.sort_values('score', ascending=False)

print("TOP 5 CONFIGURATIONS:")
print("-" * 80)
print(df_results.head(10).to_string(index=False))
print()

# Find best config meeting targets
best = df_results[
    (df_results['WR'] >= 0.60) &
    (df_results['Avg_R'] >= 1.5) &
    (df_results['PF'] >= 1.5)
].head(1)

if len(best) > 0:
    print("✓ BEST CONFIG MEETING TARGETS:")
    print("-" * 80)
    print(f"  Target: {best.iloc[0]['target%']:.2f}%")
    print(f"  Stop: {best.iloc[0]['stop%']:.2f}%")
    print(f"  R:R: {best.iloc[0]['R:R']:.2f}:1")
    print(f"  Win Rate: {best.iloc[0]['WR']*100:.1f}%")
    print(f"  Avg R: {best.iloc[0]['Avg_R']:.2f}R")
    print(f"  Profit Factor: {best.iloc[0]['PF']:.2f}")
else:
    print("⚠️  No config meets all targets (WR≥60%, R≥1.5, PF≥1.5)")
    print()
    print("CLOSEST CONFIG:")
    print("-" * 80)
    best_attempt = df_results.iloc[0]
    print(f"  Target: {best_attempt['target%']:.2f}%")
    print(f"  Stop: {best_attempt['stop%']:.2f}%")
    print(f"  R:R: {best_attempt['R:R']:.2f}:1")
    print(f"  Win Rate: {best_attempt['WR']*100:.1f}%")
    print(f"  Avg R: {best_attempt['Avg_R']:.2f}R")
    print(f"  Profit Factor: {best_attempt['PF']:.2f}")
