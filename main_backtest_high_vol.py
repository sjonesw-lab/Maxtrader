"""
High Volatility Strategy Backtest.

Tests sweep+reclaim strategy on COVID crash period (Feb-May 2020).

Target Performance:
- Win Rate: ≥85%
- Max Drawdown: <2%
- R-multiple: ≥1.5:1
- Max positions: 2-3

Setup: Liquidity sweeps + reclaims at key levels
Risk: 0.75% per trade
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data, StrategySignal
from engine.strategy_high_vol import HighVolStrategy
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe
from engine.strategy import Signal
from engine.backtest import Backtest

print("="*70)
print("HIGH VOL STRATEGY BACKTEST: COVID Crash (Feb-May 2020)")
print("="*70)

# Load COVID crash data
print("\nStep 1: Loading COVID crash data...")
provider = CSVDataProvider('data/QQQ_1m_covid_2020.csv')
df_1min = provider.load_bars()
print(f"  ✓ Loaded {len(df_1min)} bars")
print(f"  ✓ Price range: ${df_1min['low'].min():.2f} - ${df_1min['high'].max():.2f}")
print(f"  ✓ Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")

# Calculate VIX proxy
print("\nStep 2: Calculating volatility metrics...")
df_daily = resample_to_timeframe(df_1min, '1d')
vix_proxy = calculate_vix_proxy(df_daily, lookback=20)
print(f"  ✓ VIX Proxy: {vix_proxy:.1f}")
print(f"  ✓ This should be >30 for High Vol strategy")

# Preprocess market data
print("\nStep 3: Preprocessing market data...")
context = preprocess_market_data(
    df_1min,
    vix=vix_proxy,
    renko_k=4.0,
    regime_lookback=20
)
print(f"  ✓ Sessions labeled")
print(f"  ✓ ICT structures detected")
print(f"  ✓ Regime: {context.regime}")
print(f"  ✓ ATR %: {context.atr_pct:.2f}%")

# Initialize High Vol strategy
print("\nStep 4: Initializing High Vol Strategy...")
config = {
    'min_wick_ratio': 2.0,
    'reclaim_bars': 3,
    'risk_pct': 0.0075,  # 0.75%
    'target_mode': 'vwap',
    'atr_target_mult': 1.0
}
strategy = HighVolStrategy(config=config)
print(f"  ✓ Config: {config}")

# Generate signals
print("\nStep 5: Generating High Vol signals...")
print("  Strategy: Sweep + Reclaim of key levels")
print("  Key levels: Prior day high/low, session levels, swings")
print("  Entry: Reclaim close after sweep")
print("  Stop: Just beyond sweep extreme")
print("  Target: VWAP or range mid")

signals = strategy.generate_signals(context)
print(f"\n  ✓ Generated {len(signals)} signals")

if len(signals) == 0:
    print("\n⚠️ No signals generated!")
    print("Possible reasons:")
    print("  - No clean sweep+reclaim setups found")
    print("  - RR ratio too low (<1.5:1)")
    print("  - Reclaim not confirmed within 3 bars")
    exit()

# Display sample signals
print("\nSample Signals (first 5):")
print("-" * 70)
for i, sig in enumerate(signals[:5]):
    print(f"{i+1}. {sig.timestamp} | {sig.direction.upper()}")
    print(f"   Setup: {sig.setup_type}")
    print(f"   Entry: ${sig.spot:.2f}, TP1: ${sig.tp1:.2f}, Stop: ${sig.stop:.2f}")
    print(f"   R:R: {sig.reward_risk_ratio:.2f}:1")
    print(f"   Confidence: {sig.confidence:.2f}")

# Convert to backtest format
print("\nStep 6: Converting to backtest format...")
backtest_signals = []
for sig in signals:
    # Find index in df_1min
    idx = context.df_1min[context.df_1min['timestamp'] == sig.timestamp].index
    if len(idx) == 0:
        continue
    
    backtest_sig = Signal(
        timestamp=sig.timestamp,
        index=idx[0],
        spot=sig.spot,
        direction=sig.direction,
        target=sig.tp1,
        source_session=sig.meta.get('level_name', 'unknown'),
        meta={'stop': sig.stop, 'tp2': sig.tp2}
    )
    backtest_signals.append(backtest_sig)

print(f"  ✓ Converted {len(backtest_signals)} signals")

# Run backtest
print("\nStep 7: Running backtest (0DTE options, scaling exits)...")
print("  Max hold: 120 bars (2 hours)")
print("  Exit strategy: 50% @ TP1, 50% trailing")
print("  Min R:R: 1.5:1")

backtest = Backtest(context.df_1min, min_rr_ratio=1.5, use_scaling_exit=True)
results = backtest.run(backtest_signals, max_bars_held=120)

# Display results
print("\n" + "="*70)
print("HIGH VOL STRATEGY PERFORMANCE (COVID 2020)")
print("="*70)
print(f"Period: {df_1min['timestamp'].min().date()} to {df_1min['timestamp'].max().date()}")
print(f"VIX Proxy: {vix_proxy:.1f}")
print()
print(f"Total Trades: {results['total_trades']}")
print(f"Win Rate: {results['win_rate']*100:.1f}%")
print(f"Avg R-multiple: {results['avg_r']:.2f}R")
print(f"Total Return: ${results['total_pnl']:.2f}")
print(f"Max Drawdown: {results['max_drawdown']*100:.1f}%")
print()

# Target validation
print("TARGET VALIDATION:")
print("-" * 70)
targets = {
    'Win Rate': (results['win_rate'], 0.85, '≥85%'),
    'Max DD': (results['max_drawdown'], 0.02, '<2%'),
    'Avg R': (results['avg_r'], 1.5, '≥1.5R')
}

all_passed = True
for metric, (actual, target, target_str) in targets.items():
    if metric == 'Max DD':
        passed = actual < target
    else:
        passed = actual >= target
    
    status = '✓ PASS' if passed else '✗ FAIL'
    print(f"{metric:<15} {actual:.2f} (target: {target_str}) {status}")
    
    if not passed:
        all_passed = False

print()
if all_passed:
    print("🎯 ALL TARGETS MET - Strategy validated for High Vol regime!")
else:
    print("⚠️ Some targets missed - Strategy needs tuning")

print("\nDetailed Trades:")
print("-" * 70)
if 'trades' in results and len(results['trades']) > 0:
    for i, trade in enumerate(results['trades'][:10], 1):
        outcome = 'WIN' if trade.get('pnl', 0) > 0 else 'LOSS'
        print(f"{i}. {trade.get('timestamp', 'N/A')} | {outcome} | "
              f"R: {trade.get('r_multiple', 0):.2f} | PnL: ${trade.get('pnl', 0):.2f}")
