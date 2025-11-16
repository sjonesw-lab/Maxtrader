"""Debug why High Vol strategy has low win rate."""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data
from engine.strategy_high_vol import HighVolStrategy
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe

# Load March-April 2020 data
provider = CSVDataProvider('data/QQQ_1m_covid_2020.csv')
df_full = provider.load_bars()
df_1min = df_full[
    (df_full['timestamp'] >= '2020-03-01') &
    (df_full['timestamp'] < '2020-05-01')
].copy().reset_index(drop=True)

# Preprocess
df_daily = resample_to_timeframe(df_1min, '1d')
vix_proxy = calculate_vix_proxy(df_daily, lookback=20)
context = preprocess_market_data(df_1min, vix=vix_proxy, renko_k=4.0)

# Generate signals
strategy = HighVolStrategy()
signals = strategy.generate_signals(context)

print(f"Total signals: {len(signals)}")
print()

# Analyze first 10 signals
print("ANALYZING FIRST 10 SIGNALS:")
print("=" * 80)

for i, sig in enumerate(signals[:10], 1):
    idx = sig.index
    entry = sig.spot
    tp1 = sig.tp1
    stop = sig.stop
    
    # Check next 120 bars (2 hours)
    future_data = df_1min.iloc[idx:idx+120]
    
    if len(future_data) < 2:
        continue
    
    # Check if TP1 hit
    if sig.direction == 'long':
        tp1_hit = (future_data['high'] >= tp1).any()
        stop_hit = (future_data['low'] <= stop).any()
    else:  # short
        tp1_hit = (future_data['low'] <= tp1).any()
        stop_hit = (future_data['high'] >= stop).any()
    
    outcome = 'WIN' if tp1_hit and not stop_hit else ('LOSS' if stop_hit else 'NEUTRAL')
    
    print(f"{i}. {sig.timestamp} | {sig.direction.upper()} | {outcome}")
    print(f"   Entry: ${entry:.2f}, TP1: ${tp1:.2f}, Stop: ${stop:.2f}")
    print(f"   Setup: {sig.setup_type}")
    print(f"   TP1 hit: {tp1_hit}, Stop hit: {stop_hit}")
    
    if stop_hit:
        # Find when stop hit
        if sig.direction == 'long':
            stop_bar = future_data[future_data['low'] <= stop].iloc[0]
        else:
            stop_bar = future_data[future_data['high'] >= stop].iloc[0]
        
        bars_to_stop = len(future_data[future_data['timestamp'] < stop_bar['timestamp']])
        print(f"   Stop hit after {bars_to_stop} bars")
    
    print()

print()
print("PATTERN ANALYSIS:")
print("-" * 80)

# Group by outcome
wins = 0
losses = 0

for sig in signals[:50]:
    idx = sig.index
    future_data = df_1min.iloc[idx:idx+120]
    
    if len(future_data) < 2:
        continue
    
    if sig.direction == 'long':
        tp1_hit = (future_data['high'] >= sig.tp1).any()
        stop_hit = (future_data['low'] <= sig.stop).any()
    else:
        tp1_hit = (future_data['low'] <= sig.tp1).any()
        stop_hit = (future_data['high'] >= sig.stop).any()
    
    if tp1_hit and not stop_hit:
        wins += 1
    elif stop_hit:
        losses += 1

print(f"First 50 signals: {wins} wins, {losses} losses")
print(f"Win rate: {wins/(wins+losses)*100:.1f}%")
print()
print("ISSUE: If win rate <50%, targets may still be too far OR stops too tight")
print("SOLUTION: Adjust to 0.75% target / 0.5% stop (1.5:1 R:R) for higher hit rate")
