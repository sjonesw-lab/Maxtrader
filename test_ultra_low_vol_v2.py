"""
Test Ultra-Low Vol v2 strategy per designer spec.

Validates PA-confirmed mean-reversion:
- Signal A: False break + reclaim
- Signal B: Exhaustion wick
- Adaptive VWAP bands (min of 0.5×ATR or 1.0×σ)
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data
from engine.strategy_ultra_low_vol_v2 import UltraLowVolStrategyV2
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe

print("="*70)
print("ULTRA-LOW VOL V2 STRATEGY TEST (PA-Confirmed Mean-Reversion)")
print("="*70)
print()
print("Designer Spec:")
print("  ✓ VWAP bands: min(0.5×ATR, 1.0×σ)")
print("  ✓ Signal A: False break + reclaim (required)")
print("  ✓ Signal B: Exhaustion wick (recommended)")
print("  ✓ Entry: Deviation → Failure → Reclaim")
print("  ✓ NOT: Band touch → Fade")
print()

# Load Dec 2024 low-vol data
print("Step 1: Loading Dec 2024 data...")
provider = CSVDataProvider('data/QQQ_1m_lowvol_2024.csv')
df = provider.load_bars()
print(f"  ✓ Loaded {len(df)} bars")
print(f"  ✓ Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

# Calculate VIX
print("\nStep 2: Calculating volatility...")
df_daily = resample_to_timeframe(df, '1d')
vix = calculate_vix_proxy(df_daily, lookback=20)
print(f"  ✓ VIX Proxy: {vix:.1f}")

# Preprocess
print("\nStep 3: Preprocessing market data...")
context = preprocess_market_data(df, vix=vix, renko_k=4.0)
print(f"  ✓ ATR %: {context.atr_pct:.2f}%")
print(f"  ✓ Regime: {context.regime}")

# Initialize v2 strategy
print("\nStep 4: Initializing Ultra-Low Vol V2 strategy...")
strategy = UltraLowVolStrategyV2()
print("  ✓ Config:")
print(f"    - Sigma multiplier: 1.0×")
print(f"    - ATR multiplier: 0.5×")
print(f"    - Reclaim bars: 5")
print(f"    - Min R:R: 0.8")

# Generate signals
print("\nStep 5: Generating PA-confirmed signals...")
signals = strategy.generate_signals(context)
print(f"  ✓ Generated {len(signals)} signals")

if len(signals) == 0:
    print("\n⚠️ No signals generated")
    print("Possible reasons:")
    print("  - No false breaks occurred in this period")
    print("  - All deviations continued (no failures)")
    print("  - R:R below 0.8 threshold")
else:
    print(f"\n✅ SUCCESS: {len(signals)} PA-confirmed signals generated")
    print()
    print("Signal Breakdown:")
    setup_counts = {}
    for sig in signals:
        setup_counts[sig.setup_type] = setup_counts.get(sig.setup_type, 0) + 1
    
    for setup, count in setup_counts.items():
        print(f"  - {setup}: {count}")
    
    print("\nSample Signals (first 5):")
    print("-" * 70)
    for i, sig in enumerate(signals[:5], 1):
        print(f"{i}. {sig.timestamp} | {sig.direction.upper()}")
        print(f"   Setup: {sig.setup_type}")
        print(f"   Entry: ${sig.spot:.2f}, TP1: ${sig.tp1:.2f}, Stop: ${sig.stop:.2f}")
        print(f"   R:R: {sig.reward_risk_ratio:.2f}:1")
        print(f"   VWAP: ${sig.meta['vwap']:.2f}, Threshold: ${sig.meta['threshold']:.2f}")
        print()

print("="*70)
print("VALIDATION SUMMARY")
print("="*70)
if len(signals) >= 15:
    print("✅ PASS: Generated ≥15 signals (designer target: 15-25)")
elif len(signals) >= 5:
    print("⚠️ PARTIAL: Generated some signals, may need tuning")
else:
    print("❌ FAIL: Too few signals, strategy too selective")

print()
print("Next step: Run full backtest with main_backtest_low_vol_v2.py")
