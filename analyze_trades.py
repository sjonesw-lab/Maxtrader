"""Analyze trade details to understand stop loss behavior and time to profit."""

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

print("\n" + "="*70)
print("STOP LOSS & TIME TO PROFIT ANALYSIS")
print("="*70)

# Analyze each signal
stop_hits = 0
tp_hits = 0
time_expired = 0
winning_times = []
losing_times = []

for ws in wave_signals:
    entry_time = ws.timestamp
    entry_price = ws.spot
    tp1 = ws.tp1
    stop = ws.stop
    direction = ws.direction
    
    # Get future price data (120 minutes max)
    future_mask = (
        (df_1min['timestamp'] > entry_time) &
        (df_1min['timestamp'] <= entry_time + pd.Timedelta(minutes=120))
    )
    future_data = df_1min.loc[future_mask]
    
    if len(future_data) == 0:
        continue
    
    # Check each minute for stop or target hit
    stop_hit = False
    tp_hit = False
    exit_time = None
    
    for idx, row in future_data.iterrows():
        price = row['close']
        timestamp = row['timestamp']
        
        # Check stop first
        if stop > 0:
            if (direction == 'long' and price <= stop) or \
               (direction == 'short' and price >= stop):
                stop_hit = True
                exit_time = timestamp
                break
        
        # Check target
        if (direction == 'long' and price >= tp1) or \
           (direction == 'short' and price <= tp1):
            tp_hit = True
            exit_time = timestamp
            break
    
    # Calculate time to exit
    if exit_time:
        time_to_exit = (exit_time - entry_time).total_seconds() / 60  # minutes
    else:
        time_to_exit = 120  # max hold
        exit_time = future_data['timestamp'].iloc[-1]
    
    if stop_hit:
        stop_hits += 1
        losing_times.append(time_to_exit)
    elif tp_hit:
        tp_hits += 1
        winning_times.append(time_to_exit)
    else:
        time_expired += 1
        # Check if last price was winner or loser
        final_price = future_data['close'].iloc[-1]
        if (direction == 'long' and final_price > entry_price) or \
           (direction == 'short' and final_price < entry_price):
            winning_times.append(time_to_exit)
        else:
            losing_times.append(time_to_exit)

print(f"\nTotal Signals: {len(wave_signals)}")
print(f"\nExit Breakdown:")
print(f"  - Target hits: {tp_hits} ({tp_hits/len(wave_signals)*100:.1f}%)")
print(f"  - Stop hits: {stop_hits} ({stop_hits/len(wave_signals)*100:.1f}%)")
print(f"  - Time expired: {time_expired} ({time_expired/len(wave_signals)*100:.1f}%)")

if winning_times:
    print(f"\nWinning Trades Time to Profit:")
    print(f"  - Average: {sum(winning_times)/len(winning_times):.1f} minutes")
    print(f"  - Median: {sorted(winning_times)[len(winning_times)//2]:.1f} minutes")
    print(f"  - Min: {min(winning_times):.1f} minutes")
    print(f"  - Max: {max(winning_times):.1f} minutes")

if losing_times:
    print(f"\nLosing Trades Time to Loss:")
    print(f"  - Average: {sum(losing_times)/len(losing_times):.1f} minutes")
    print(f"  - Median: {sorted(losing_times)[len(losing_times)//2]:.1f} minutes")

print("\n" + "="*70)
