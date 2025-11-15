"""
Download QQQ 1-minute data for extreme volatility periods.

High Vol: Feb 19 - May 19, 2020 (COVID crash - 90 days)
Low Vol: Dec 1, 2024 - Feb 28, 2025 (calm period - 90 days)
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time

API_KEY = os.getenv('POLYGON_API_KEY')
BASE_URL = "https://api.polygon.io/v2/aggs/ticker/QQQ/range/1/minute"

def download_period(start_date, end_date, filename):
    """Download 1-min bars for a date range."""
    
    print(f"\nDownloading {filename}...")
    print(f"  Period: {start_date} to {end_date}")
    
    all_bars = []
    
    # Polygon limits to 50,000 bars per request
    # Split into daily chunks to be safe
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    while current_date <= end_dt:
        day_start = current_date.strftime('%Y-%m-%d')
        day_end = (current_date + timedelta(days=1)).strftime('%Y-%m-%d')
        
        url = f"{BASE_URL}/{day_start}/{day_end}"
        params = {
            'apiKey': API_KEY,
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000
        }
        
        print(f"  Fetching {day_start}...", end='')
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get('results'):
                all_bars.extend(data['results'])
                print(f" ✓ {len(data['results'])} bars")
            else:
                print(f" (no data - weekend/holiday)")
            
            # Rate limit: 5 requests per minute for free tier
            time.sleep(0.5)
            
        except Exception as e:
            print(f" ✗ Error: {e}")
        
        current_date += timedelta(days=1)
    
    # Convert to DataFrame
    if not all_bars:
        print(f"  ✗ No data retrieved!")
        return None
    
    df = pd.DataFrame(all_bars)
    
    # Rename columns to match our format
    df = df.rename(columns={
        'v': 'volume',
        'o': 'open',
        'c': 'close',
        'h': 'high',
        'l': 'low',
        't': 'timestamp'
    })
    
    # Convert timestamp from milliseconds to datetime
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York')
    
    # Keep only trading hours (9:30-16:00 ET)
    df = df[df['timestamp'].dt.hour.between(9, 15) | 
            ((df['timestamp'].dt.hour == 9) & (df['timestamp'].dt.minute >= 30))]
    
    # Select columns
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    # Save
    df.to_csv(f'data/{filename}', index=False)
    print(f"  ✓ Saved {len(df)} bars to data/{filename}")
    
    return df

# Download both periods
print("="*70)
print("DOWNLOADING EXTREME VOLATILITY PERIODS")
print("="*70)

# High volatility: COVID crash
high_vol = download_period(
    '2020-02-19',
    '2020-05-19',
    'QQQ_1m_covid_2020.csv'
)

# Low volatility: Dec 2024
low_vol = download_period(
    '2024-12-01',
    '2025-02-28',
    'QQQ_1m_lowvol_2024.csv'
)

print("\n" + "="*70)
print("DOWNLOAD COMPLETE")
print("="*70)

if high_vol is not None:
    print(f"\nHigh Vol (COVID 2020):")
    print(f"  Bars: {len(high_vol)}")
    print(f"  Date range: {high_vol['timestamp'].min()} to {high_vol['timestamp'].max()}")
    print(f"  Price range: ${high_vol['low'].min():.2f} - ${high_vol['high'].max():.2f}")

if low_vol is not None:
    print(f"\nLow Vol (Dec 2024):")
    print(f"  Bars: {len(low_vol)}")
    print(f"  Date range: {low_vol['timestamp'].min()} to {low_vol['timestamp'].max()}")
    print(f"  Price range: ${low_vol['low'].min():.2f} - ${low_vol['high'].max():.2f}")

print("\nReady for backtesting!")
