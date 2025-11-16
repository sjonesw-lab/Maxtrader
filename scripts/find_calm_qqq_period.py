"""
Find 90-day periods with low QQQ volatility using Polygon API.

Since VIX data requires paid tier, we calculate realized volatility
directly from QQQ daily price data.
"""

import os
import requests
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# Get Polygon API key from environment
API_KEY = os.environ.get('POLYGON_API_KEY')

if not API_KEY:
    print("❌ POLYGON_API_KEY not found in environment")
    exit(1)

print("="*70)
print("FINDING LOW VOLATILITY PERIODS FROM QQQ PRICE DATA")
print("="*70)
print()

# Search last 5 years for calm periods
# Use known calm periods: 2017, 2021, 2023
search_periods = [
    ('2017-01-01', '2018-01-31'),  # 2017 famous low vol
    ('2021-01-01', '2021-12-31'),  # Post-COVID calm
    ('2023-01-01', '2024-01-31'),  # Recent calm
]

all_windows = []

for period_start, period_end in search_periods:
    print(f"Analyzing period: {period_start} to {period_end}")
    
    # Fetch QQQ daily data
    url = f"https://api.polygon.io/v2/aggs/ticker/QQQ/range/1/day/{period_start}/{period_end}"
    params = {
        'adjusted': 'true',
        'sort': 'asc',
        'limit': 50000,
        'apiKey': API_KEY
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        print(f"  ⚠️  Error fetching data: {response.status_code}")
        continue
    
    data = response.json()
    
    if 'results' not in data or len(data['results']) == 0:
        print(f"  ⚠️  No data returned")
        continue
    
    # Convert to DataFrame
    bars = []
    for bar in data['results']:
        bars.append({
            'date': datetime.fromtimestamp(bar['t'] / 1000),
            'open': bar['o'],
            'high': bar['h'],
            'low': bar['l'],
            'close': bar['c'],
            'volume': bar['v']
        })
    
    df = pd.DataFrame(bars)
    
    # Calculate daily returns
    df['return'] = df['close'].pct_change()
    
    # Calculate realized volatility (annualized) in 90-day windows
    window_size = 90
    
    for i in range(len(df) - window_size):
        window = df.iloc[i:i+window_size]
        
        # Realized volatility (annualized)
        vol = window['return'].std() * np.sqrt(252) * 100  # As percentage
        
        # Calculate ATR %
        window['tr'] = window[['high', 'low']].apply(
            lambda x: x['high'] - x['low'], axis=1
        )
        atr = window['tr'].mean()
        atr_pct = (atr / window['close'].mean()) * 100
        
        all_windows.append({
            'start_date': window['date'].iloc[0],
            'end_date': window['date'].iloc[-1],
            'realized_vol': vol,
            'atr_pct': atr_pct,
            'avg_price': window['close'].mean()
        })
    
    print(f"  ✓ Analyzed {len(df)} days, found {len(df) - window_size} windows")

if len(all_windows) == 0:
    print("❌ No data found")
    exit(1)

# Sort by realized volatility (lowest first)
all_windows.sort(key=lambda x: x['realized_vol'])

print()
print("="*70)
print("TOP 10 CALMEST 90-DAY PERIODS (Lowest Realized Volatility)")
print("="*70)
print()

for i, window in enumerate(all_windows[:10], 1):
    print(f"{i}. {window['start_date'].date()} to {window['end_date'].date()}")
    print(f"   Realized Vol: {window['realized_vol']:.2f}% (annualized)")
    print(f"   ATR %: {window['atr_pct']:.2f}%")
    print(f"   VIX Proxy: ~{window['realized_vol'] * 0.7:.1f}")  # Rough estimate
    print()

# Select best window (lowest volatility)
best_window = all_windows[0]

print("="*70)
print("RECOMMENDED WINDOW FOR ULTRA-LOW VOL TESTING")
print("="*70)
print(f"Start: {best_window['start_date'].date()}")
print(f"End: {best_window['end_date'].date()}")
print(f"Realized Vol: {best_window['realized_vol']:.2f}% (annualized)")
print(f"ATR %: {best_window['atr_pct']:.2f}%")
print(f"VIX Proxy: ~{best_window['realized_vol'] * 0.7:.1f}")
print()

# Check if this truly qualifies as ultra-low vol
vix_proxy = best_window['realized_vol'] * 0.7
if vix_proxy < 13:
    print("✅ TRUE ULTRA-LOW VOL (VIX proxy <13)")
elif vix_proxy < 15:
    print("⚠️  MODERATE-LOW VOL (VIX proxy 13-15)")
else:
    print("❌ NOT ULTRA-LOW VOL (VIX proxy >15)")

print()

# Save to file for download script
with open('data/best_calm_window.txt', 'w') as f:
    f.write(f"{best_window['start_date'].strftime('%Y-%m-%d')}\n")
    f.write(f"{best_window['end_date'].strftime('%Y-%m-%d')}\n")
    f.write(f"{best_window['realized_vol']:.2f}\n")
    f.write(f"{best_window['atr_pct']:.2f}\n")

print("✓ Saved window info to data/best_calm_window.txt")
print()
print("Next: Run download_calm_qqq_data.py to fetch QQQ 1m bars")
