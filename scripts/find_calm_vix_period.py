"""
Find 90-day periods with VIX <13 (ultra-low volatility) using Polygon API.

This script searches historical VIX data to identify calm market periods
suitable for testing the Ultra-Low Vol strategy.
"""

import os
import requests
from datetime import datetime, timedelta
import pandas as pd

# Get Polygon API key from environment
API_KEY = os.environ.get('POLYGON_API_KEY')

if not API_KEY:
    print("❌ POLYGON_API_KEY not found in environment")
    exit(1)

print("="*70)
print("FINDING ULTRA-LOW VOLATILITY PERIODS (VIX <13)")
print("="*70)
print()

# Search last 5 years for calm periods
end_date = datetime.now()
start_date = end_date - timedelta(days=5*365)

print(f"Searching period: {start_date.date()} to {end_date.date()}")
print()

# Fetch VIX daily data from Polygon
url = f"https://api.polygon.io/v2/aggs/ticker/I:VIX/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
params = {
    'adjusted': 'true',
    'sort': 'asc',
    'limit': 50000,
    'apiKey': API_KEY
}

print("Fetching VIX data from Polygon...")
response = requests.get(url, params=params)

if response.status_code != 200:
    print(f"❌ Error fetching VIX data: {response.status_code}")
    print(response.text)
    exit(1)

data = response.json()

if 'results' not in data or len(data['results']) == 0:
    print("❌ No VIX data returned")
    exit(1)

# Convert to DataFrame
vix_data = []
for bar in data['results']:
    vix_data.append({
        'date': datetime.fromtimestamp(bar['t'] / 1000),
        'vix': bar['c']  # Close price
    })

df_vix = pd.DataFrame(vix_data)
print(f"✓ Loaded {len(df_vix)} days of VIX data")
print()

# Find 90-day rolling windows with avg VIX <13
window_size = 90
ultra_low_windows = []

for i in range(len(df_vix) - window_size):
    window = df_vix.iloc[i:i+window_size]
    avg_vix = window['vix'].mean()
    min_vix = window['vix'].min()
    max_vix = window['vix'].max()
    
    if avg_vix < 13:
        ultra_low_windows.append({
            'start_date': window['date'].iloc[0],
            'end_date': window['date'].iloc[-1],
            'avg_vix': avg_vix,
            'min_vix': min_vix,
            'max_vix': max_vix
        })

if len(ultra_low_windows) == 0:
    print("❌ No 90-day windows found with avg VIX <13")
    print()
    print("Trying VIX <15 (slightly relaxed)...")
    
    for i in range(len(df_vix) - window_size):
        window = df_vix.iloc[i:i+window_size]
        avg_vix = window['vix'].mean()
        min_vix = window['vix'].min()
        max_vix = window['vix'].max()
        
        if avg_vix < 15:
            ultra_low_windows.append({
                'start_date': window['date'].iloc[0],
                'end_date': window['date'].iloc[-1],
                'avg_vix': avg_vix,
                'min_vix': min_vix,
                'max_vix': max_vix
            })

if len(ultra_low_windows) == 0:
    print("❌ No ultra-low vol periods found")
    print()
    print("Showing lowest VIX periods instead:")
    
    # Find periods with lowest VIX
    for i in range(len(df_vix) - window_size):
        window = df_vix.iloc[i:i+window_size]
        avg_vix = window['vix'].mean()
        min_vix = window['vix'].min()
        max_vix = window['vix'].max()
        
        ultra_low_windows.append({
            'start_date': window['date'].iloc[0],
            'end_date': window['date'].iloc[-1],
            'avg_vix': avg_vix,
            'min_vix': min_vix,
            'max_vix': max_vix
        })
    
    # Sort by avg VIX and take top 10
    ultra_low_windows.sort(key=lambda x: x['avg_vix'])
    ultra_low_windows = ultra_low_windows[:10]

# Sort by date (most recent first)
ultra_low_windows.sort(key=lambda x: x['start_date'], reverse=True)

print(f"✅ Found {len(ultra_low_windows)} calm periods")
print()
print("Top 10 Ultra-Low Volatility Windows (90 days):")
print("-"*70)

for i, window in enumerate(ultra_low_windows[:10], 1):
    print(f"{i}. {window['start_date'].date()} to {window['end_date'].date()}")
    print(f"   Avg VIX: {window['avg_vix']:.2f}")
    print(f"   Range: {window['min_vix']:.2f} - {window['max_vix']:.2f}")
    print()

# Select best window (lowest avg VIX)
best_window = min(ultra_low_windows, key=lambda x: x['avg_vix'])

print("="*70)
print("RECOMMENDED WINDOW FOR TESTING")
print("="*70)
print(f"Start: {best_window['start_date'].date()}")
print(f"End: {best_window['end_date'].date()}")
print(f"Avg VIX: {best_window['avg_vix']:.2f}")
print(f"Range: {best_window['min_vix']:.2f} - {best_window['max_vix']:.2f}")
print()

# Save to file for next script
with open('data/best_calm_window.txt', 'w') as f:
    f.write(f"{best_window['start_date'].strftime('%Y-%m-%d')}\n")
    f.write(f"{best_window['end_date'].strftime('%Y-%m-%d')}\n")
    f.write(f"{best_window['avg_vix']:.2f}\n")

print("✓ Saved window info to data/best_calm_window.txt")
print()
print("Next: Run download_calm_qqq_data.py to fetch QQQ 1m bars for this period")
