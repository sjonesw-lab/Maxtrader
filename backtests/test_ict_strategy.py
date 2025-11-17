#!/usr/bin/env python3
"""
Test the ICT strategy on real Polygon data to see if institutional detection works.
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

print("\n" + "="*70)
print("Testing ICT Structure Detection on Real Data")
print("="*70)

# Load May 2021 data
data_path = Path('data/polygon_downloads/QQQ_2021_05_1min.csv')
provider = CSVDataProvider(str(data_path))
df = provider.load_bars()

print(f"\nLoaded {len(df):,} bars from May 2021")
print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

# Label sessions
print("\nLabeling sessions...")
df = label_sessions(df)
df = add_session_highs_lows(df)

# Detect ICT structures
print("Detecting ICT structures...")
df = detect_all_structures(df, displacement_threshold=1.0)

# Count structures
liquidity_sweeps_bull = df['sweep_bullish'].sum()
liquidity_sweeps_bear = df['sweep_bearish'].sum()
displacement_bull = df['displacement_bullish'].sum()
displacement_bear = df['displacement_bearish'].sum()
mss_bull = df['mss_bullish'].sum()
mss_bear = df['mss_bearish'].sum()

print(f"\n📊 ICT Structure Detection Results:")
print(f"   Liquidity Sweeps (Bullish): {liquidity_sweeps_bull}")
print(f"   Liquidity Sweeps (Bearish): {liquidity_sweeps_bear}")
print(f"   Displacement (Bullish): {displacement_bull}")
print(f"   Displacement (Bearish): {displacement_bear}")
print(f"   MSS (Bullish): {mss_bull}")
print(f"   MSS (Bearish): {mss_bear}")

# Show some examples
print(f"\n🔍 Sample Bullish Liquidity Sweeps:")
sweeps = df[df['sweep_bullish'] == True][['timestamp', 'open', 'high', 'low', 'close', 'sweep_source']].head(5)
if len(sweeps) > 0:
    print(sweeps.to_string(index=False))
else:
    print("   No bullish sweeps detected!")

print(f"\n🔍 Sample Bullish Displacement Candles:")
displacements = df[df['displacement_bullish'] == True][['timestamp', 'open', 'high', 'low', 'close', 'atr']].head(5)
if len(displacements) > 0:
    print(displacements.to_string(index=False))
else:
    print("   No bullish displacements detected!")

print(f"\n🔍 Sample Bullish MSS:")
mss = df[df['mss_bullish'] == True][['timestamp', 'open', 'high', 'low', 'close']].head(5)
if len(mss) > 0:
    print(mss.to_string(index=False))
else:
    print("   No bullish MSS detected!")

# Check for confluence (sweep + displacement + MSS on same or nearby bars)
print(f"\n🎯 Looking for Confluence (Sweep + Displacement + MSS within 5 bars):")
confluence_count = 0

for i in range(len(df)):
    if df.iloc[i]['sweep_bullish']:
        # Check next 5 bars for displacement and MSS
        window = df.iloc[i:min(i+6, len(df))]
        if window['displacement_bullish'].any() and window['mss_bullish'].any():
            print(f"   Bullish confluence at {df.iloc[i]['timestamp']}")
            confluence_count += 1
            if confluence_count >= 3:
                break

if confluence_count == 0:
    print("   No bullish confluence patterns found in first scan")

print(f"\n{'='*70}\n")
