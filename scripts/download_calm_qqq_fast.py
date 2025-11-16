"""
Download QQQ 1-minute data using aggregates API (faster).
Uses weekly chunks to minimize API calls.
"""

import os
import requests
from datetime import datetime, timedelta
import pandas as pd
import time

API_KEY = os.environ.get('POLYGON_API_KEY')

# Load best window
with open('data/best_calm_window.txt', 'r') as f:
    lines = f.readlines()
    start_date = datetime.strptime(lines[0].strip(), '%Y-%m-%d')
    end_date = datetime.strptime(lines[1].strip(), '%Y-%m-%d')

print(f"Downloading QQQ 1m: {start_date.date()} to {end_date.date()}")
print("Using weekly chunks to reduce API calls...")
print()

all_bars = []
current = start_date

# Fetch in weekly chunks
while current <= end_date:
    chunk_end = min(current + timedelta(days=7), end_date)
    
    url = f"https://api.polygon.io/v2/aggs/ticker/QQQ/range/1/minute/{current.strftime('%Y-%m-%d')}/{chunk_end.strftime('%Y-%m-%d')}"
    params = {'adjusted': 'true', 'sort': 'asc', 'limit': 50000, 'apiKey': API_KEY}
    
    print(f"{current.date()} to {chunk_end.date()}...", end=' ')
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        
        if resp.status_code == 200:
            data = resp.json()
            if 'results' in data:
                count = len(data['results'])
                for bar in data['results']:
                    all_bars.append({
                        'timestamp': datetime.fromtimestamp(bar['t'] / 1000),
                        'open': bar['o'], 'high': bar['h'],
                        'low': bar['l'], 'close': bar['c'], 'volume': bar['v']
                    })
                print(f"✓ {count} bars")
            else:
                print("⚠️  No data")
        else:
            print(f"❌ {resp.status_code}")
            if resp.status_code == 429:
                print("Rate limited, waiting 60s...")
                time.sleep(60)
                continue
    
    except Exception as e:
        print(f"❌ {e}")
    
    current = chunk_end + timedelta(days=1)
    time.sleep(12)  # Rate limit

print(f"\n✓ Total: {len(all_bars)} bars")

df = pd.DataFrame(all_bars).sort_values('timestamp').reset_index(drop=True)

# Market hours only
df['hour'] = df['timestamp'].dt.hour
df['minute'] = df['timestamp'].dt.minute
df = df[((df['hour'] > 9) | ((df['hour'] == 9) & (df['minute'] >= 30))) & (df['hour'] < 16)].copy()
df = df.drop(columns=['hour', 'minute'])

df.to_csv('data/QQQ_1m_ultralowvol_2017.csv', index=False)
print(f"\n✅ Saved {len(df)} bars to data/QQQ_1m_ultralowvol_2017.csv")
print(f"Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
