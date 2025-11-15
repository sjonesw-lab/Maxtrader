"""Compare ICT targets vs fixed % targets vs actual price moves."""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy_wave_renko import generate_wave_signals
from engine.timeframes import resample_to_timeframe
from engine.ict_structures import detect_all_structures

# Load data
provider = CSVDataProvider('data/QQQ_1m_real.csv')
df_1min = provider.load_bars()
df_4h = resample_to_timeframe(df_1min, '4h')
df_daily = resample_to_timeframe(df_1min, '1D')
df_1min = label_sessions(df_1min)
df_1min = add_session_highs_lows(df_1min)
df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)

k_value = 4.0
renko_df = build_renko(df_1min, mode="atr", k=k_value, atr_period=14)
brick_size = renko_df['brick_size'].iloc[0]

df_30min = resample_to_timeframe(df_1min, '30min')
renko_30min = build_renko(df_30min, mode="atr", k=1.0)
renko_direction_30min = get_renko_direction_series(df_30min, renko_30min)
regime_30min = detect_regime(df_30min, renko_direction_30min, lookback=20)

df_1min['regime'] = 'sideways'
for idx in range(len(df_1min)):
    ts = df_1min['timestamp'].iloc[idx]
    mask = df_30min['timestamp'] <= ts
    if mask.any():
        regime_idx = mask.sum() - 1
        if regime_idx < len(regime_30min):
            df_1min.loc[df_1min.index[idx], 'regime'] = regime_30min.iloc[regime_idx]

# Generate signals with FIXED % targets
fixed_pct_signals = generate_wave_signals(
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
    target_mode='fixed_pct'
)

# Generate signals with WAVE-BASED targets (includes ICT if enabled)
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
    target_mode='wave'
)

print("\n" + "="*70)
print("ICT TARGETS vs FIXED % TARGETS vs ACTUAL MOVES")
print("="*70)

# Compare first 10 signals
fixed_pct_targets = []
wave_targets = []
actual_highs = []
actual_lows = []

for i in range(min(10, len(fixed_pct_signals))):
    fixed_sig = fixed_pct_signals[i]
    wave_sig = wave_signals[i]
    
    entry_time = fixed_sig.timestamp
    entry_price = fixed_sig.spot
    direction = fixed_sig.direction
    
    # Get actual price movement over 120 minutes
    future_mask = (
        (df_1min['timestamp'] > entry_time) &
        (df_1min['timestamp'] <= entry_time + pd.Timedelta(minutes=120))
    )
    future_data = df_1min.loc[future_mask]
    
    if len(future_data) == 0:
        continue
    
    actual_high = future_data['high'].max()
    actual_low = future_data['low'].min()
    
    # Calculate distances
    fixed_tp1_dist = abs(fixed_sig.tp1 - entry_price)
    wave_tp1_dist = abs(wave_sig.tp1 - entry_price)
    
    if direction == 'long':
        actual_move = actual_high - entry_price
        fixed_hit = actual_high >= fixed_sig.tp1
        wave_hit = actual_high >= wave_sig.tp1
    else:
        actual_move = entry_price - actual_low
        fixed_hit = actual_low <= fixed_sig.tp1
        wave_hit = actual_low <= wave_sig.tp1
    
    fixed_pct = (fixed_tp1_dist / entry_price) * 100
    wave_pct = (wave_tp1_dist / entry_price) * 100
    actual_pct = (actual_move / entry_price) * 100
    
    print(f"\nTrade {i+1} ({direction.upper()}):")
    print(f"  Entry: ${entry_price:.2f}")
    print(f"  Fixed TP1: ${fixed_sig.tp1:.2f} (+{fixed_pct:.2f}%) - {'HIT' if fixed_hit else 'MISS'}")
    print(f"  Wave TP1:  ${wave_sig.tp1:.2f} (+{wave_pct:.2f}%) - {'HIT' if wave_hit else 'MISS'}")
    print(f"  Actual move: ${actual_move:.2f} (+{actual_pct:.2f}%)")
    
    fixed_pct_targets.append(fixed_pct)
    wave_targets.append(wave_pct)
    actual_highs.append(actual_pct)

print("\n" + "="*70)
print("SUMMARY STATISTICS")
print("="*70)

if fixed_pct_targets:
    print(f"\nFixed % Targets:")
    print(f"  Average: {sum(fixed_pct_targets)/len(fixed_pct_targets):.2f}%")
    print(f"  Range: {min(fixed_pct_targets):.2f}% - {max(fixed_pct_targets):.2f}%")
    
    print(f"\nWave-based Targets:")
    print(f"  Average: {sum(wave_targets)/len(wave_targets):.2f}%")
    print(f"  Range: {min(wave_targets):.2f}% - {max(wave_targets):.2f}%")
    
    print(f"\nActual Price Moves (120 min):")
    print(f"  Average: {sum(actual_highs)/len(actual_highs):.2f}%")
    print(f"  Range: {min(actual_highs):.2f}% - {max(actual_highs):.2f}%")
    
    # Count hits
    fixed_hits = sum(1 for i in range(len(fixed_pct_targets)) if actual_highs[i] >= fixed_pct_targets[i])
    wave_hits = sum(1 for i in range(len(wave_targets)) if actual_highs[i] >= wave_targets[i])
    
    print(f"\nTarget Hit Rate (first {len(fixed_pct_targets)} trades):")
    print(f"  Fixed %: {fixed_hits}/{len(fixed_pct_targets)} ({fixed_hits/len(fixed_pct_targets)*100:.1f}%)")
    print(f"  Wave: {wave_hits}/{len(wave_targets)} ({wave_hits/len(wave_targets)*100:.1f}%)")

print("\n" + "="*70)
