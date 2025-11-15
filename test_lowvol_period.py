"""
Test system on low volatility period (Dec 2024 - Feb 2025).
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy_wave_renko import generate_wave_signals
from engine.strategy import Signal
from engine.backtest import Backtest
from engine.timeframes import resample_to_timeframe
from engine.ict_structures import detect_all_structures

print("="*70)
print("LOW VOL TEST: Dec 2024 - Feb 2025 (CALM MARKETS)")
print("="*70)

# Load low vol data
print("\nStep 1: Loading low volatility data...")
provider = CSVDataProvider('data/QQQ_1m_lowvol_2024.csv')
df_1min = provider.load_bars()
print(f"  ✓ Loaded {len(df_1min)} bars")
print(f"  ✓ Price range: ${df_1min['low'].min():.2f} - ${df_1min['high'].max():.2f}")
print(f"  ✓ Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")

# Create 4H and daily
df_4h = resample_to_timeframe(df_1min, '4h')
df_daily = resample_to_timeframe(df_1min, '1d')

# Label sessions and detect ICT structures
print("\nStep 2: Detecting ICT structures...")
df_1min = label_sessions(df_1min)
df_1min = add_session_highs_lows(df_1min)
df_1min = detect_all_structures(df_1min, displacement_threshold=1.2)

# Build Renko
print("\nStep 3: Building Renko chart...")
brick_size = 0.66
renko_df = build_renko(df_1min, mode='atr', k=4.0, fixed_brick_size=brick_size)

# Detect regime
print("\nStep 4: Detecting regime...")
df_30min = resample_to_timeframe(df_1min, '30min')
renko_30min = build_renko(df_30min, mode="atr", k=1.0)
renko_direction_30min = get_renko_direction_series(df_30min, renko_30min)
regime_30min = detect_regime(df_30min, renko_direction_30min, lookback=20)

# Align regime to 1-min data
df_1min['regime'] = 'sideways'
for idx in range(len(df_1min)):
    ts = df_1min['timestamp'].iloc[idx]
    mask = df_30min['timestamp'] <= ts
    if mask.any():
        regime_idx = mask.sum() - 1
        if regime_idx < len(regime_30min):
            df_1min.loc[df_1min.index[idx], 'regime'] = regime_30min.iloc[regime_idx]

# Generate signals
print("\nStep 5: Generating wave signals (BASELINE config)...")
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

print(f"  ✓ Generated {len(wave_signals)} wave signals")

# Convert to Signal format
signals = []
for ws in wave_signals:
    sig = Signal(
        timestamp=ws.timestamp,
        index=df_1min[df_1min['timestamp'] == ws.timestamp].index[0] if (df_1min['timestamp'] == ws.timestamp).any() else 0,
        spot=ws.spot,
        direction=ws.direction,
        target=ws.tp1,
        source_session=None,
        meta={'stop': ws.stop, 'tp2': ws.tp2}
    )
    signals.append(sig)

# Run backtest
print("\nStep 6: Running backtest (0DTE options, scaling exits)...")
backtest = Backtest(df_1min, min_rr_ratio=1.2, use_scaling_exit=True)
results = backtest.run(signals, max_bars_held=120)

# Results
print("\n" + "="*70)
print("LOW VOL PERFORMANCE (Dec 2024 - Feb 2025)")
print("="*70)
print(f"Total Trades:        {results['total_trades']}")
print(f"Win Rate:            {results['win_rate']*100:.1f}%")
print(f"Average PnL:         ${results['avg_pnl']:.2f}")
if 'avg_r' in results:
    print(f"Average R-Multiple:  {results['avg_r']:.2f}R")
print(f"Total PnL:           ${results['total_pnl']:.2f}")
if 'max_drawdown' in results:
    print(f"Max Drawdown:        ${results['max_drawdown']:.2f}")
if 'profit_factor' in results:
    print(f"Profit Factor:       {results.get('profit_factor', 0):.2f}")
print("="*70)
