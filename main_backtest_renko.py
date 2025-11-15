"""
Hybrid Renko-based backtest: Original MaxTrader momentum + optional ICT + 0DTE options

System Flow:
1. Load 1-min data
2. Build Renko chart (price-driven, not time-driven)
3. Detect 30-min regime for bias
4. Generate signals on Renko brick formations
5. Execute with 0DTE options
6. ATR-based targets (2-4 bricks)

Expected: 10-20 trades/month, 60-70% win rate, 2-5R avg
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions
from engine.renko import build_renko
from engine.regimes import detect_regime, get_renko_direction_series
from engine.strategy_renko import generate_renko_signals, RenkoSignal
from engine.strategy import Signal  # For compatibility with backtest
from engine.backtest import Backtest
from engine.timeframes import resample_to_timeframe

print("="*70)
print("MaxTrader Hybrid: Renko + ICT + 0DTE Options")
print("="*70)

# Step 1: Load data
print("\nStep 1: Loading QQQ 1-minute data...")
provider = CSVDataProvider('data/qqq_1min.csv')
df_1min = provider.load()
print(f"  ✓ Loaded {len(df_1min)} bars")
print(f"  ✓ Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")

# Step 2: Label sessions (still useful for regime context)
print("\nStep 2: Labeling sessions...")
df_1min = label_sessions(df_1min)
print(f"  ✓ Sessions labeled")

# Step 3: Build Renko chart
print("\nStep 3: Building Renko chart (price-driven signal generation)...")
renko_df = build_renko(df_1min, mode="atr", k=1.0, atr_period=14)
print(f"  ✓ Built {len(renko_df)} Renko bricks from {len(df_1min)} bars")
print(f"  ✓ Brick-to-bar ratio: {len(df_1min)/len(renko_df):.1f}x compression")

# Step 4: Get 30-min regime for trend bias
print("\nStep 4: Detecting regime on 30-min timeframe...")
df_30min = resample_to_timeframe(df_1min, '30min')
renko_30min = build_renko(df_30min, mode="atr", k=1.0)
renko_direction_30min = get_renko_direction_series(df_30min, renko_30min)
regime_30min = detect_regime(df_30min, renko_direction_30min, lookback=20)

# Align regime to 1-min data
df_1min['regime'] = 'sideways'  # Default
for idx in range(len(df_1min)):
    ts = df_1min['timestamp'].iloc[idx]
    mask = df_30min['timestamp'] <= ts
    if mask.any():
        regime_idx = mask.sum() - 1
        if regime_idx < len(regime_30min):
            df_1min.loc[df_1min.index[idx], 'regime'] = regime_30min.iloc[regime_idx]

regime_counts = df_1min['regime'].value_counts()
print(f"  ✓ Regime detection complete:")
for regime, count in regime_counts.items():
    pct = (count / len(df_1min)) * 100
    print(f"    - {regime}: {pct:.1f}%")

# Step 5: Generate signals on Renko brick formations
print("\nStep 5: Generating signals from Renko bricks...")
brick_size = 1.0  # Approximate from ATR

renko_signals = generate_renko_signals(
    df_1min=df_1min,
    renko_df=renko_df,
    regime_series=df_1min['regime'],
    brick_size=brick_size,
    min_momentum=0.6,
    enable_ict_filter=False  # ICT optional, not required
)

print(f"  ✓ Generated {len(renko_signals)} signals from Renko bricks")

# Convert to standard Signal format for backtest
signals = []
for rs in renko_signals:
    sig = Signal(
        index=df_1min[df_1min['timestamp'] == rs.timestamp].index[0] if (df_1min['timestamp'] == rs.timestamp).any() else 0,
        timestamp=rs.timestamp,
        direction=rs.direction,
        spot=rs.spot,
        target=rs.target,
        source_session=None,
        meta={
            'renko_index': rs.brick_index,
            'momentum_strength': rs.momentum_strength,
            'regime': rs.regime,
            'has_ict': rs.has_ict_confluence,
            'brick_count': rs.brick_count_to_target
        }
    )
    signals.append(sig)

long_signals = [s for s in signals if s.direction == 'long']
short_signals = [s for s in signals if s.direction == 'short']
print(f"    - Long signals: {len(long_signals)}")
print(f"    - Short signals: {len(short_signals)}")

# Breakdown by regime
regime_breakdown = {}
for sig in signals:
    regime = sig.meta['regime']
    regime_breakdown[regime] = regime_breakdown.get(regime, 0) + 1

print(f"  Signals by regime:")
for regime, count in regime_breakdown.items():
    print(f"    - {regime}: {count}")

# Step 6: Run backtest with 0DTE options
print("\nStep 6: Running options backtest (0DTE, 1.2 R:R filter)...")
backtest = Backtest(df_1min, min_rr_ratio=1.2)  # Lower threshold for Renko system
results = backtest.run(signals, max_bars_held=60)

# Step 7: Print results
print("\n" + "="*70)
print("PERFORMANCE SUMMARY")
print("="*70)
print(f"Total Trades:        {results['total_trades']}")
print(f"Win Rate:            {results['win_rate']:.1f}%")
print(f"Average PnL:         ${results['avg_pnl']:.2f}")
print(f"Average R-Multiple:  {results['avg_r']:.2f}R")
print(f"Total PnL:           ${results['total_pnl']:.2f}")
print(f"Max Drawdown:        ${results['max_drawdown']:.2f}")

if results['total_trades'] > 0:
    trades_per_month = results['total_trades'] / 3  # 90 days ≈ 3 months
    print(f"\nTrade Frequency:     {trades_per_month:.1f} trades/month")
    
    print("\nTrade Details:")
    print("-" * 70)
    for i, trade in enumerate(results['trades'][:10], 1):  # Show first 10
        print(f"Trade {i}:")
        print(f"  Direction:   {trade.signal.direction.upper()}")
        print(f"  Entry:       {trade.signal.timestamp} @ ${trade.signal.spot:.2f}")
        print(f"  Target:      ${trade.signal.target:.2f}")
        print(f"  Entry Cost:  ${trade.entry_cost:.2f}")
        print(f"  PnL:         ${trade.pnl:.2f} ({trade.r_multiple:.2f}R)")
        print(f"  Exit:        {trade.exit_time}")
        print(f"  Momentum:    {trade.signal.meta.get('momentum_strength', 0):.2f}")
    
    if len(results['trades']) > 10:
        print(f"... and {len(results['trades']) - 10} more trades")

print("\n" + "="*70)
print(f"Generating equity curve chart...")
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

if results['total_trades'] > 0:
    pnls = [t.pnl for t in results['trades']]
    cumulative = [sum(pnls[:i+1]) for i in range(len(pnls))]
    
    plt.figure(figsize=(12, 6))
    plt.plot(cumulative, marker='o', linewidth=2)
    plt.axhline(0, color='red', linestyle='--', alpha=0.5)
    plt.title('Hybrid Renko System: Equity Curve', fontsize=14, fontweight='bold')
    plt.xlabel('Trade Number')
    plt.ylabel('Cumulative P&L ($)')
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig('equity_curve_renko.png', dpi=150)
    print(f"  ✓ Chart saved to: equity_curve_renko.png")

print("="*70)
print("Backtest complete!")
print("="*70)
