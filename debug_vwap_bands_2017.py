"""
Debug VWAP bands in 2017 ultra-low vol environment.

Check if bands are reachable and what's happening with Signal A/B logic.
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data, calculate_atr
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe
import numpy as np

# Load 2017 data
provider = CSVDataProvider('data/QQQ_1m_ultralowvol_2017.csv')
df = provider.load_bars()

print("="*70)
print("VWAP BAND ANALYSIS - 2017 ULTRA-LOW VOL")
print("="*70)
print()

# Calculate VWAP bands for a sample window
sample_start = 1000
sample_end = 1100
sample_df = df.iloc[sample_start:sample_end]

# Calculate VWAP
typical_price = (sample_df['high'] + sample_df['low'] + sample_df['close']) / 3
vwap = (typical_price * sample_df['volume']).sum() / sample_df['volume'].sum()

# Calculate std dev
price_dev = typical_price - vwap
std = price_dev.std()

# Calculate ATR
atr = calculate_atr(sample_df, period=14)

# Adaptive threshold (designer spec)
atr_threshold = 0.5 * atr
sigma_threshold = 1.0 * std
threshold = max(0.02, min(atr_threshold, sigma_threshold))

upper_band = vwap + threshold
lower_band = vwap - threshold

print(f"Sample Window: bars {sample_start} to {sample_end}")
print(f"Price range: ${sample_df['low'].min():.2f} - ${sample_df['high'].max():.2f}")
print()
print("VWAP Band Calculation:")
print(f"  VWAP: ${vwap:.2f}")
print(f"  ATR: ${atr:.4f} ({atr/vwap*100:.2f}%)")
print(f"  Std Dev: ${std:.4f}")
print()
print("Adaptive Threshold:")
print(f"  0.5 × ATR = ${atr_threshold:.4f}")
print(f"  1.0 × σ   = ${sigma_threshold:.4f}")
print(f"  Threshold (min of above): ${threshold:.4f}")
print()
print("Bands:")
print(f"  Upper: ${upper_band:.2f}")
print(f"  Lower: ${lower_band:.2f}")
print(f"  Width: ${upper_band - lower_band:.4f} ({(upper_band - lower_band)/vwap*100:.2f}%)")
print()

# Check how many bars touch bands
touches_upper = (sample_df['high'] > upper_band).sum()
touches_lower = (sample_df['low'] < lower_band).sum()

print("Band Interactions:")
print(f"  Bars touching upper band: {touches_upper} ({touches_upper/len(sample_df)*100:.1f}%)")
print(f"  Bars touching lower band: {touches_lower} ({touches_lower/len(sample_df)*100:.1f}%)")
print()

if touches_upper == 0 and touches_lower == 0:
    print("❌ PROBLEM: Price NEVER reaches bands!")
    print("   Bands are too wide for ultra-low vol environment")
    print()
    print("Solution: Use wider bands or different signal logic")
    
    # Try wider bands
    print()
    print("Testing 2.0σ bands:")
    threshold_2sigma = 2.0 * std
    upper_2sigma = vwap + threshold_2sigma
    lower_2sigma = vwap - threshold_2sigma
    
    touches_upper_2s = (sample_df['high'] > upper_2sigma).sum()
    touches_lower_2s = (sample_df['low'] < lower_2sigma).sum()
    
    print(f"  Upper band: ${upper_2sigma:.2f}")
    print(f"  Lower band: ${lower_2sigma:.2f}")
    print(f"  Touches upper: {touches_upper_2s}")
    print(f"  Touches lower: {touches_lower_2s}")

else:
    print("✅ Bands are reachable")
    
    # Check for Signal B patterns (exhaustion wicks)
    print()
    print("Checking for exhaustion wick patterns...")
    
    wick_longs = 0
    wick_shorts = 0
    
    for i in range(len(sample_df)):
        bar = sample_df.iloc[i]
        
        # Long setup
        if bar['low'] < lower_band:
            lower_wick = min(bar['open'], bar['close']) - bar['low']
            body = abs(bar['close'] - bar['open'])
            
            if lower_wick > body * 2.0 and bar['close'] > lower_band:
                wick_longs += 1
        
        # Short setup
        elif bar['high'] > upper_band:
            upper_wick = bar['high'] - max(bar['open'], bar['close'])
            body = abs(bar['close'] - bar['open'])
            
            if upper_wick > body * 2.0 and bar['close'] < upper_band:
                wick_shorts += 1
    
    print(f"  Exhaustion wick longs: {wick_longs}")
    print(f"  Exhaustion wick shorts: {wick_shorts}")
    
    if wick_longs + wick_shorts == 0:
        print("  ❌ No exhaustion wicks found (requirements too strict)")

print()
print("="*70)
print("RECOMMENDATION")
print("="*70)

if touches_upper + touches_lower == 0:
    print("Price NEVER reaches adaptive bands in ultra-low vol.")
    print()
    print("Designer spec may not work for EXTREME low vol (VIX ~6).")
    print()
    print("Options:")
    print("  1. Use WIDER bands (1.5σ or 2.0σ instead of min)")
    print("  2. Use different signal: price crosses VWAP itself")
    print("  3. Treat VIX <8 as no-trade (too calm)")
