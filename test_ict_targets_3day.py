"""
Test ICT target hit rates within 3 days.

Compare:
- Current strategy: 120-min intraday, drift-based profits
- ICT strategy: 3-day holds, natural structure targets
"""

import pandas as pd
import numpy as np
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy_wave_renko import generate_wave_signals

print("="*70)
print("ICT TARGET TEST: 3-Day Hold Performance")
print("="*70)

# Load data
print("\nStep 1: Loading data...")
provider = CSVDataProvider("data/QQQ_1m_real.csv")
df_1min = provider.load_bars()
print(f"  ✓ Loaded {len(df_1min)} bars")

# Create 4H and daily
df_4h = df_1min.set_index('timestamp').resample('4H', origin='start').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).dropna().reset_index()

df_daily = df_1min.set_index('timestamp').resample('1D', origin='start').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).dropna().reset_index()

# Label sessions
print("\nStep 2: Detecting ICT structures...")
df_1min = label_sessions(df_1min)
df_1min = add_session_highs_lows(df_1min)
df_1min = detect_all_structures(df_1min, displacement_threshold=1.2)

# Build Renko
print("\nStep 3: Building Renko chart...")
brick_size = 0.66
renko_df = build_renko(df_1min, mode='atr', k=4.0, fixed_brick_size=brick_size)

# Skip regime detection - just use simple neutral regime for all signals
print("\nStep 4: Using neutral regime (no regime filtering)...")
df_1min['regime'] = 'sideways'  # Allow all signals

# Generate signals
print("\nStep 5: Generating wave signals...")
wave_signals = generate_wave_signals(
    df_1min=df_1min,
    df_4h=df_4h,
    df_daily=df_daily,
    renko_df=renko_df,
    regime_series=df_1min['regime'],
    brick_size=brick_size,
    min_bricks=3,
    max_entry_distance=1.5,
    min_confidence=0.40,
    use_ict_boost=False,
    target_mode='fixed_pct',
    require_sweep=False,
    use_volume_filter=False,
    avoid_lunch_chop=False,
    use_dynamic_targets=False
)
print(f"  ✓ Generated {len(wave_signals)} signals")

# Test ICT targets within 3 days
print("\nStep 6: Testing ICT target hit rates (3-day window)...")
print("  Looking for:")
print("    - FVG fill zones")
print("    - Recent swing highs/lows")
print("    - Session level revisits")
print("    - Order block touches")

three_day_bars = 3 * 390  # 3 trading days * 6.5 hours * 60 min

results = []

for sig_idx, sig in enumerate(wave_signals):
    timestamp = sig.timestamp
    direction = sig.direction
    entry_price = sig.spot
    
    # Get signal row in df_1min
    signal_mask = df_1min['timestamp'] == timestamp
    if not signal_mask.any():
        continue
    
    sig_row_idx = df_1min[signal_mask].index[0]
    sig_row = df_1min.loc[sig_row_idx]
    
    # Get 3-day future price data
    future_start_idx = sig_row_idx + 1
    future_end_idx = min(sig_row_idx + three_day_bars, len(df_1min))
    future_data = df_1min.iloc[future_start_idx:future_end_idx]
    
    if len(future_data) == 0:
        continue
    
    # Find ICT targets near entry
    ict_targets = []
    
    # 1. FVG targets
    if pd.notna(sig_row.get('fvg_low')) and pd.notna(sig_row.get('fvg_high')):
        fvg_mid = (sig_row['fvg_low'] + sig_row['fvg_high']) / 2
        if direction == 'long':
            ict_targets.append(('FVG_high', sig_row['fvg_high']))
        else:
            ict_targets.append(('FVG_low', sig_row['fvg_low']))
    
    # 2. Session levels (for sweeps)
    if direction == 'long':
        if pd.notna(sig_row.get('asia_high')):
            ict_targets.append(('Asia_high', sig_row['asia_high']))
        if pd.notna(sig_row.get('london_high')):
            ict_targets.append(('London_high', sig_row['london_high']))
    else:
        if pd.notna(sig_row.get('asia_low')):
            ict_targets.append(('Asia_low', sig_row['asia_low']))
        if pd.notna(sig_row.get('london_low')):
            ict_targets.append(('London_low', sig_row['london_low']))
    
    # 3. Recent swing high/low (look back 100 bars)
    lookback_start = max(0, sig_row_idx - 100)
    recent_data = df_1min.iloc[lookback_start:sig_row_idx]
    
    if direction == 'long':
        recent_high = recent_data['high'].max()
        if recent_high > entry_price:
            ict_targets.append(('Recent_swing_high', recent_high))
    else:
        recent_low = recent_data['low'].min()
        if recent_low < entry_price:
            ict_targets.append(('Recent_swing_low', recent_low))
    
    # Check which targets hit within 3 days
    targets_hit = []
    
    for target_name, target_price in ict_targets:
        # Skip targets that are too close (within 0.2%)
        dist_pct = abs(target_price - entry_price) / entry_price
        if dist_pct < 0.002:
            continue
        
        # Check if target hit
        if direction == 'long':
            hit = (future_data['high'] >= target_price).any()
        else:
            hit = (future_data['low'] <= target_price).any()
        
        if hit:
            # Find when it hit
            if direction == 'long':
                hit_mask = future_data['high'] >= target_price
            else:
                hit_mask = future_data['low'] <= target_price
            
            hit_idx = future_data[hit_mask].index[0]
            bars_to_hit = hit_idx - sig_row_idx
            
            # Calculate P&L if we held to target
            pnl_pct = abs(target_price - entry_price) / entry_price * 100
            
            targets_hit.append({
                'target_name': target_name,
                'target_price': target_price,
                'bars_to_hit': bars_to_hit,
                'hours_to_hit': bars_to_hit / 60,
                'pnl_pct': pnl_pct,
                'distance_pct': dist_pct * 100
            })
    
    # Also check max favorable excursion (MFE) in 3 days
    if direction == 'long':
        max_price = future_data['high'].max()
        mfe_pct = (max_price - entry_price) / entry_price * 100
    else:
        min_price = future_data['low'].min()
        mfe_pct = (entry_price - min_price) / entry_price * 100
    
    results.append({
        'signal_idx': sig_idx,
        'timestamp': timestamp,
        'direction': direction,
        'entry_price': entry_price,
        'ict_targets_count': len(ict_targets),
        'targets_hit_count': len(targets_hit),
        'targets_hit': targets_hit,
        'mfe_3day': mfe_pct,
        'bars_available': len(future_data)
    })

# Analysis
print("\n" + "="*70)
print("ICT TARGET ANALYSIS (3-Day Window)")
print("="*70)

total_signals = len(results)
signals_with_targets = sum(1 for r in results if r['ict_targets_count'] > 0)
signals_hitting_targets = sum(1 for r in results if r['targets_hit_count'] > 0)

print(f"\nSignals analyzed: {total_signals}")
print(f"Signals with ICT targets nearby: {signals_with_targets} ({signals_with_targets/total_signals*100:.1f}%)")
print(f"Signals hitting at least 1 target: {signals_hitting_targets} ({signals_hitting_targets/total_signals*100:.1f}%)")

# Target hit breakdown
all_hits = []
for r in results:
    all_hits.extend(r['targets_hit'])

if len(all_hits) > 0:
    print(f"\nTotal target hits: {len(all_hits)}")
    print(f"Average time to target: {np.mean([h['hours_to_hit'] for h in all_hits]):.1f} hours")
    print(f"Average target distance: {np.mean([h['distance_pct'] for h in all_hits]):.2f}%")
    print(f"Average PnL at target: {np.mean([h['pnl_pct'] for h in all_hits]):.2f}%")
    
    # Target type breakdown
    target_types = {}
    for hit in all_hits:
        ttype = hit['target_name']
        if ttype not in target_types:
            target_types[ttype] = []
        target_types[ttype].append(hit)
    
    print("\nTarget types hit:")
    for ttype, hits in target_types.items():
        avg_time = np.mean([h['hours_to_hit'] for h in hits])
        avg_pnl = np.mean([h['pnl_pct'] for h in hits])
        print(f"  - {ttype}: {len(hits)} hits, avg {avg_time:.1f}h, avg {avg_pnl:.2f}% PnL")

# MFE analysis
mfe_values = [r['mfe_3day'] for r in results if r['bars_available'] >= three_day_bars * 0.8]
if len(mfe_values) > 0:
    print(f"\n3-Day Max Favorable Excursion:")
    print(f"  Average MFE: {np.mean(mfe_values):.2f}%")
    print(f"  Median MFE: {np.median(mfe_values):.2f}%")
    print(f"  Max MFE: {np.max(mfe_values):.2f}%")
    print(f"  % signals with >1% MFE: {sum(1 for m in mfe_values if m > 1.0)/len(mfe_values)*100:.1f}%")
    print(f"  % signals with >2% MFE: {sum(1 for m in mfe_values if m > 2.0)/len(mfe_values)*100:.1f}%")

# Comparison to current system
print("\n" + "="*70)
print("COMPARISON: ICT 3-Day Targets vs Current Intraday Drift")
print("="*70)

print("\nCurrent System (120-min, drift-based):")
print("  - Win Rate: 95.7%")
print("  - Avg PnL: $46.50 (1.07R)")
print("  - Hold time: 2 hours avg")
print("  - Total PnL: $3,208 (69 trades)")

if len(all_hits) > 0:
    hit_rate = signals_hitting_targets / total_signals * 100
    avg_target_pnl = np.mean([h['pnl_pct'] for h in all_hits])
    
    print(f"\nICT 3-Day Target System (theoretical):")
    print(f"  - Target Hit Rate: {hit_rate:.1f}%")
    print(f"  - Avg PnL at target: {avg_target_pnl:.2f}%")
    print(f"  - Hold time: {np.mean([h['hours_to_hit'] for h in all_hits]):.1f} hours avg")
    print(f"  - Would need multi-day options (NOT 0DTE)")
    
    print("\n⚠️  TRADE-OFFS:")
    print("  ✅ Higher % moves (targets)")
    print("  ❌ Lower hit rate vs current 95.7%")
    print("  ❌ Need longer-dated options (higher premium)")
    print("  ❌ More theta decay over 3 days")
    print("  ❌ Overnight risk exposure")

print("\n" + "="*70)
