"""
Test Ultra-Low Vol V2 strategy on TRUE ultra-low vol data (2017).

This is the CORRECT test environment per designer spec:
- VIX proxy: ~4.6 (WAY below 13 threshold)
- Realized vol: 6.64% annualized
- ATR %: 0.63%
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data
from engine.strategy_ultra_low_vol_v2 import UltraLowVolStrategyV2
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe

print("="*70)
print("ULTRA-LOW VOL V2 TEST - TRUE ULTRA-LOW VOL ENVIRONMENT (2017)")
print("="*70)
print()
print("Designer Spec:")
print("  ✓ VIX <13: TRUE (proxy ~4.6)")
print("  ✓ ATR <0.5%: FALSE (0.63%, but close)")
print("  ✓ Target signals: 15-25")
print("  ✓ Signal A (false break + reclaim): REQUIRED")
print("  ✓ Signal B (exhaustion wick): RECOMMENDED")
print()

# Load 2017 ultra-low vol data
print("Step 1: Loading 2017 ultra-low vol data...")
provider = CSVDataProvider('data/QQQ_1m_ultralowvol_2017.csv')
df = provider.load_bars()
print(f"  ✓ Loaded {len(df)} bars")
print(f"  ✓ Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

# Calculate VIX proxy
print("\nStep 2: Calculating volatility...")
df_daily = resample_to_timeframe(df, '1d')
vix = calculate_vix_proxy(df_daily, lookback=20)
print(f"  ✓ VIX Proxy: {vix:.1f} (TRUE ultra-low vol!)")

# Preprocess
print("\nStep 3: Preprocessing market data...")
context = preprocess_market_data(df, vix=vix, renko_k=4.0)
print(f"  ✓ ATR %: {context.atr_pct:.2f}%")
print(f"  ✓ Regime: {context.regime}")

# Initialize strategy
print("\nStep 4: Initializing Ultra-Low Vol V2 strategy...")
strategy = UltraLowVolStrategyV2()
print("  ✓ Config:")
print(f"    - Adaptive bands: min(0.5×ATR, 1.0×σ)")
print(f"    - Signal A: False break + reclaim (REQUIRED)")
print(f"    - Signal B: Exhaustion wick (RECOMMENDED)")
print(f"    - Cooldown: 100 bars")
print(f"    - Min R:R: 0.8")

# Generate signals
print("\nStep 5: Generating PA-confirmed signals...")
signals = strategy.generate_signals(context)
print(f"  ✓ Generated {len(signals)} signals")

print()
print("="*70)
print("RESULTS")
print("="*70)
print(f"Signals Generated: {len(signals)}")
print(f"Designer Target: 15-25 signals")
print()

if len(signals) == 0:
    print("❌ FAIL: No signals generated")
    print("\nPossible reasons:")
    print("  - Strategy too strict for this environment")
    print("  - Signal A logic not working")
    print("  - Need to tune parameters")

elif 15 <= len(signals) <= 25:
    print("✅ PERFECT: Signal count matches designer target!")
    
elif len(signals) < 15:
    print(f"⚠️  BELOW TARGET: {15 - len(signals)} signals short")
    print("Strategy may be too strict")
    
else:
    print(f"⚠️  ABOVE TARGET: {len(signals) - 25} signals over")
    print("Strategy may be too permissive")

print()

if len(signals) > 0:
    # Signal breakdown
    setup_counts = {}
    for sig in signals:
        setup_counts[sig.setup_type] = setup_counts.get(sig.setup_type, 0) + 1
    
    print("Signal Breakdown:")
    print("-" * 70)
    for setup, count in sorted(setup_counts.items()):
        print(f"  {setup}: {count} ({count/len(signals)*100:.1f}%)")
    
    # Check Signal A presence
    signal_a_count = sum(1 for sig in signals if 'reclaim' in sig.setup_type)
    signal_b_count = sum(1 for sig in signals if 'wick' in sig.setup_type)
    
    print()
    print("Architect Validation:")
    print(f"  Signal A (required): {signal_a_count} signals ({signal_a_count/len(signals)*100:.1f}%)")
    print(f"  Signal B (recommended): {signal_b_count} signals ({signal_b_count/len(signals)*100:.1f}%)")
    
    if signal_a_count > 0:
        print("  ✅ Signal A is firing (REQUIRED pattern present)")
    else:
        print("  ❌ Signal A NOT firing (REQUIRED pattern missing)")
    
    # Sample signals
    print()
    print("Sample Signals (first 5):")
    print("-" * 70)
    for i, sig in enumerate(signals[:5], 1):
        print(f"{i}. {sig.timestamp} | {sig.direction.upper()}")
        print(f"   Setup: {sig.setup_type}")
        print(f"   Entry: ${sig.spot:.2f}, TP1: ${sig.tp1:.2f}, Stop: ${sig.stop:.2f}")
        print(f"   R:R: {sig.reward_risk_ratio:.2f}:1")
        if 'vwap' in sig.meta:
            print(f"   VWAP: ${sig.meta['vwap']:.2f}, Threshold: ${sig.meta['threshold']:.2f}")
        print()

print("="*70)
print("NEXT STEPS")
print("="*70)

if len(signals) >= 10:
    print("✅ Enough signals to backtest!")
    print("   Run: python main_backtest_ultra_low_vol.py")
else:
    print("⚠️  Too few signals for meaningful backtest")
    print("   Consider tuning parameters or accepting lower signal count")
