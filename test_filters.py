"""Test each filter individually to find optimal combination."""

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

print("\n" + "="*70)
print("FILTER EFFECTIVENESS TESTING")
print("="*70)

# Baseline
baseline = generate_wave_signals(
    df_1min, df_4h, df_daily, renko_df, df_1min['regime'], brick_size,
    min_bricks=3, max_entry_distance=1.5, min_confidence=0.40,
    use_ict_boost=False, target_mode='fixed_pct'
)

print(f"\nBaseline (no extra filters): {len(baseline)} signals")

# Test 1: Sweep filter only
try:
    sweep_only = generate_wave_signals(
        df_1min, df_4h, df_daily, renko_df, df_1min['regime'], brick_size,
        min_bricks=3, max_entry_distance=1.5, min_confidence=0.40,
        use_ict_boost=False, target_mode='fixed_pct',
        require_sweep=True
    )
    print(f"+ Sweep filter only: {len(sweep_only)} signals ({len(sweep_only)/len(baseline)*100:.1f}% of baseline)")
except Exception as e:
    print(f"+ Sweep filter only: ERROR - {e}")

# Test 2: Volume filter only
volume_only = generate_wave_signals(
    df_1min, df_4h, df_daily, renko_df, df_1min['regime'], brick_size,
    min_bricks=3, max_entry_distance=1.5, min_confidence=0.40,
    use_ict_boost=False, target_mode='fixed_pct',
    use_volume_filter=True
)
print(f"+ Volume filter only: {len(volume_only)} signals ({len(volume_only)/len(baseline)*100:.1f}% of baseline)")

# Test 3: Time-of-day filter only
time_only = generate_wave_signals(
    df_1min, df_4h, df_daily, renko_df, df_1min['regime'], brick_size,
    min_bricks=3, max_entry_distance=1.5, min_confidence=0.40,
    use_ict_boost=False, target_mode='fixed_pct',
    avoid_lunch_chop=True
)
print(f"+ Time-of-day filter only: {len(time_only)} signals ({len(time_only)/len(baseline)*100:.1f}% of baseline)")

# Test 4: Dynamic targets only
dynamic_only = generate_wave_signals(
    df_1min, df_4h, df_daily, renko_df, df_1min['regime'], brick_size,
    min_bricks=3, max_entry_distance=1.5, min_confidence=0.40,
    use_ict_boost=False, target_mode='fixed_pct',
    use_dynamic_targets=True
)
print(f"+ Dynamic targets only: {len(dynamic_only)} signals (same as baseline - targets don't filter)")

print("\n" + "="*70)
