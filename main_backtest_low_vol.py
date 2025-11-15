"""
Ultra-Low Volatility Strategy Backtest.

Tests VWAP mean-reversion strategy on Dec 2024 low-volatility period.

Target Performance:
- Win Rate: ≥60%
- Expectancy: ≥0.3R per trade
- Max consecutive losses: ≤3
- Max positions: 3-4

Setup: VWAP fades, range extremes, grind pullbacks
Risk: 1.25% per trade
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data, StrategySignal
from engine.strategy_ultra_low_vol import UltraLowVolStrategy
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe
from engine.strategy import Signal
from engine.backtest import Backtest

print("="*70)
print("ULTRA-LOW VOL STRATEGY BACKTEST: Dec 2024 (Dead Calm)")
print("="*70)

# Load Dec 2024 data
print("\nStep 1: Loading Dec 2024 low-volatility data...")
provider = CSVDataProvider('data/QQQ_1m_lowvol_2024.csv')
df_1min = provider.load_bars()
print(f"  ✓ Loaded {len(df_1min)} bars")
print(f"  ✓ Price range: ${df_1min['low'].min():.2f} - ${df_1min['high'].max():.2f}")
print(f"  ✓ Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")

# Calculate VIX proxy
print("\nStep 2: Calculating volatility metrics...")
df_daily = resample_to_timeframe(df_1min, '1d')
vix_proxy = calculate_vix_proxy(df_daily, lookback=20)
print(f"  ✓ VIX Proxy: {vix_proxy:.1f}")
print(f"  ✓ This should be <13 for Ultra-Low Vol strategy")

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

# Initialize Ultra-Low Vol strategy
print("\nStep 4: Initializing Ultra-Low Vol Strategy...")
config = {
    'vwap_std_threshold': 2.0,
    'range_definition_bars': 90,
    'risk_pct': 0.0125,  # 1.25%
    'target_atr_mult': 0.6,
    'min_range_pct': 0.003
}
strategy = UltraLowVolStrategy(config=config)
print(f"  ✓ Config: {config}")

# Generate signals
print("\nStep 5: Generating Ultra-Low Vol signals...")
print("  Strategy: VWAP mean-reversion + range fades")
print("  Setups:")
print("    1. VWAP Fade: Price ±2 std dev → fade back")
print("    2. Range Extreme: Small sweep at edge → fade inside")
print("    3. Grind Pullback: Trend + dip to VWAP → rejoin")
print("  Target: VWAP, range mid, or 0.5-0.75 ATR")

signals = strategy.generate_signals(context)
print(f"\n  ✓ Generated {len(signals)} signals")

if len(signals) == 0:
    print("\n⚠️ No signals generated!")
    print("Possible reasons:")
    print("  - Range too small (<0.3% of price)")
    print("  - No VWAP extremes (±2 std dev)")
    print("  - RR ratio too low (<1:1)")
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
        source_session=sig.setup_type,
        meta={'stop': sig.stop, 'tp2': sig.tp2}
    )
    backtest_signals.append(backtest_sig)

print(f"  ✓ Converted {len(backtest_signals)} signals")

# Run backtest
print("\nStep 7: Running backtest (0DTE options, scaling exits)...")
print("  Max hold: 90 bars (1.5 hours)")
print("  Exit strategy: 50% @ TP1, 50% trailing")
print("  Min R:R: 1.0:1 (accept lower in low vol)")

backtest = Backtest(context.df_1min, min_rr_ratio=1.0, use_scaling_exit=True)
results = backtest.run(backtest_signals, max_bars_held=90)

# Display results
print("\n" + "="*70)
print("ULTRA-LOW VOL STRATEGY PERFORMANCE (Dec 2024)")
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

# Calculate max consecutive losses
if 'trades' in results and len(results['trades']) > 0:
    consecutive_losses = 0
    max_consecutive_losses = 0
    for trade in results['trades']:
        if trade.get('pnl', 0) < 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0
else:
    max_consecutive_losses = 0

print(f"Max Consecutive Losses: {max_consecutive_losses}")
print()

# Target validation
print("TARGET VALIDATION:")
print("-" * 70)
targets = {
    'Win Rate': (results['win_rate'], 0.60, '≥60%'),
    'Expectancy': (results['avg_r'], 0.3, '≥0.3R'),
    'Max Consec Loss': (max_consecutive_losses, 3, '≤3')
}

all_passed = True
for metric, (actual, target, target_str) in targets.items():
    if metric == 'Max Consec Loss':
        passed = actual <= target
    else:
        passed = actual >= target
    
    status = '✓ PASS' if passed else '✗ FAIL'
    
    if metric == 'Max Consec Loss':
        print(f"{metric:<18} {int(actual)} (target: {target_str}) {status}")
    else:
        print(f"{metric:<18} {actual:.2f} (target: {target_str}) {status}")
    
    if not passed:
        all_passed = False

print()
if all_passed:
    print("🎯 ALL TARGETS MET - Strategy validated for Ultra-Low Vol regime!")
else:
    print("⚠️ Some targets missed - Strategy needs tuning")

print("\nDetailed Trades:")
print("-" * 70)
if 'trades' in results and len(results['trades']) > 0:
    for i, trade in enumerate(results['trades'][:15], 1):
        outcome = 'WIN' if trade.get('pnl', 0) > 0 else 'LOSS'
        print(f"{i}. {trade.get('timestamp', 'N/A')} | {outcome} | "
              f"R: {trade.get('r_multiple', 0):.2f} | PnL: ${trade.get('pnl', 0):.2f}")
