"""Debug why signals aren't converting to trades."""

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

wave_signals = generate_wave_signals(
    df_1min, df_4h, df_daily, renko_df, df_1min['regime'], brick_size,
    min_bricks=3, max_entry_distance=1.5, min_confidence=0.40,
    use_ict_boost=False, target_mode='fixed_pct',
    use_volume_filter=True, avoid_lunch_chop=True,
    use_dynamic_targets=True
)

print(f"Generated {len(wave_signals)} signals")

if len(wave_signals) > 0:
    ws = wave_signals[0]
    print(f"\nFirst signal:")
    print(f"  Direction: {ws.direction}")
    print(f"  Entry: ${ws.spot:.2f}")
    print(f"  TP1: ${ws.tp1:.2f} ({(abs(ws.tp1 - ws.spot) / ws.spot * 100):.2f}%)")
    print(f"  TP2: ${ws.tp2:.2f} ({(abs(ws.tp2 - ws.spot) / ws.spot * 100):.2f}%)")
    print(f"  Stop: ${ws.stop:.2f} ({(abs(ws.stop - ws.spot) / ws.spot * 100):.2f}%)")
    print(f"  Timestamp: {ws.timestamp}")
    
    # Check if signal has all required attributes
    print(f"\n  Has all attributes:")
    print(f"    - tp1: {hasattr(ws, 'tp1')} = {ws.tp1 if hasattr(ws, 'tp1') else 'N/A'}")
    print(f"    - stop: {hasattr(ws, 'stop')} = {ws.stop if hasattr(ws, 'stop') else 'N/A'}")
    print(f"    - spot: {hasattr(ws, 'spot')} = {ws.spot if hasattr(ws, 'spot') else 'N/A'}")

print("\n" + "="*70)
