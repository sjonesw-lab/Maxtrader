"""
Download QQQ 1-minute data for the ultra-low volatility period.

Uses Polygon API to fetch intraday bars for backtesting.
"""

import os
import requests
from datetime import datetime, timedelta
import pandas as pd
import time

# Get Polygon API key
API_KEY = os.environ.get('POLYGON_API_KEY')

if not API_KEY:
    print("❌ POLYGON_API_KEY not found")
    exit(1)

# Load best window from previous script
with open('data/best_calm_window.txt', 'r') as f:
    lines = f.readlines()
    start_date = datetime.strptime(lines[0].strip(), '%Y-%m-%d')
    end_date = datetime.strptime(lines[1].strip(), '%Y-%m-%d')
    realized_vol = float(lines[2].strip())
    atr_pct = float(lines[3].strip())

print("="*70)
print("DOWNLOADING QQQ 1-MINUTE DATA FOR ULTRA-LOW VOL PERIOD")
print("="*70)
print()
print(f"Period: {start_date.date()} to {end_date.date()}")
print(f"Realized Vol: {realized_vol:.2f}%")
print(f"ATR %: {atr_pct:.2f}%")
print(f"VIX Proxy: ~{realized_vol * 0.7:.1f}")
print()

# Polygon rate limits: 5 requests/min for free tier
# We'll need to fetch data in chunks

all_bars = []
current_date = start_date

print("Fetching data (this may take a few minutes due to rate limits)...")
print()

while current_date <= end_date:
    # Fetch one day at a time
    date_str = current_date.strftime('%Y-%m-%d')
    
    url = f"https://api.polygon.io/v2/aggs/ticker/QQQ/range/1/minute/{date_str}/{date_str}"
    params = {
        'adjusted': 'true',
        'sort': 'asc',
        'limit': 50000,
        'apiKey': API_KEY
    }
    
    print(f"Fetching {date_str}...", end=' ')
    
    try:
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'results' in data and len(data['results']) > 0:
                for bar in data['results']:
                    all_bars.append({
                        'timestamp': datetime.fromtimestamp(bar['t'] / 1000),
                        'open': bar['o'],
                        'high': bar['h'],
                        'low': bar['l'],
                        'close': bar['c'],
                        'volume': bar['v']
                    })
                print(f"✓ {len(data['results'])} bars")
            else:
                print("⚠️  No data (likely weekend/holiday)")
        
        elif response.status_code == 429:
            print("⚠️  Rate limited, waiting 60s...")
            time.sleep(60)
            continue  # Retry same date
        
        else:
            print(f"❌ Error {response.status_code}")
    
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    # Move to next day
    current_date += timedelta(days=1)
    
    # Rate limit protection (free tier: 5 req/min)
    time.sleep(12)  # Wait 12 seconds between requests

print()
print(f"✓ Downloaded {len(all_bars)} 1-minute bars")
print()

if len(all_bars) == 0:
    print("❌ No data downloaded")
    exit(1)

# Convert to DataFrame and save
df = pd.DataFrame(all_bars)
df = df.sort_values('timestamp').reset_index(drop=True)

# Filter to market hours only (9:30-16:00 ET)
df['hour'] = df['timestamp'].dt.hour
df['minute'] = df['timestamp'].dt.minute
df = df[
    ((df['hour'] > 9) | ((df['hour'] == 9) & (df['minute'] >= 30))) &
    (df['hour'] < 16)
].copy()
df = df.drop(columns=['hour', 'minute'])

print(f"✓ Filtered to market hours: {len(df)} bars")
print()

# Save to CSV
output_file = 'data/QQQ_1m_ultralowvol_2017.csv'
df.to_csv(output_file, index=False)

print("="*70)
print("DOWNLOAD COMPLETE")
print("="*70)
print(f"File: {output_file}")
print(f"Bars: {len(df):,}")
print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print()
print("Next: Run test_ultra_low_vol_v2.py with this data")
