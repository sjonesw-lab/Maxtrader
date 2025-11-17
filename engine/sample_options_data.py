#!/usr/bin/env python3
"""
Sample real 0DTE options data to build premium estimation model
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from engine.polygon_options_fetcher import PolygonOptionsFetcher
from engine.data_provider import CSVDataProvider
import time
import pickle


# Sample dates across different market conditions
sample_dates = [
    # 2024
    '2024-03-01', '2024-03-15', '2024-04-10', '2024-04-25',
    '2024-05-08', '2024-05-22', '2024-07-03', '2024-07-17',
    '2024-08-05', '2024-08-19', '2024-09-04', '2024-09-18',
    '2024-10-02', '2024-10-16', '2024-10-30', '2024-11-13',
    # 2025
    '2025-02-05', '2025-02-19', '2025-03-06', '2025-03-20',
    '2025-05-07', '2025-05-21', '2025-09-03', '2025-09-17',
    '2025-10-01', '2025-10-15',
]

fetcher = PolygonOptionsFetcher()

print("\n" + "="*80)
print("SAMPLING REAL 0DTE OPTIONS DATA")
print("="*80)
print(f"Downloading {len(sample_dates)} days of QQQ options data...")
print("="*80 + "\n")

all_samples = []

for date_str in sample_dates:
    # Check if we have underlying data for this date
    year, month = date_str.split('-')[0], date_str.split('-')[1]
    underlying_file = f'data/polygon_downloads/QQQ_{year}_{month}_1min.csv'
    
    if not Path(underlying_file).exists():
        print(f"Skip {date_str} - no underlying data")
        continue
    
    try:
        # Load underlying QQQ data to get price at market open
        provider = CSVDataProvider(underlying_file)
        df_underlying = provider.load_bars()
        
        # Filter to this specific date
        date_mask = df_underlying['timestamp'].dt.date == pd.to_datetime(date_str).date()
        df_day = df_underlying[date_mask].copy()
        
        if len(df_day) == 0:
            print(f"Skip {date_str} - no data for this date")
            continue
        
        # Get market open price (9:30 AM)
        market_open_bar = df_day.iloc[0]
        underlying_price = market_open_bar['close']
        
        # Calculate ATM strike
        atm_strike = round(underlying_price / 5) * 5
        
        # Fetch options for 3 strikes: ATM, ATM+5, ATM+10 (calls)
        strikes_to_fetch = [atm_strike, atm_strike + 5, atm_strike + 10]
        
        print(f"{date_str}: QQQ @ ${underlying_price:.2f}, ATM strike ${atm_strike}")
        
        for strike in strikes_to_fetch:
            option_ticker = fetcher.build_option_ticker('QQQ', date_str, 'C', strike)
            
            try:
                df_option = fetcher.fetch_option_bars(option_ticker, date_str, date_str)
                
                if df_option is not None and len(df_option) > 0:
                    # Sample at various times during the day
                    for sample_time_minutes in [0, 30, 60, 120, 180, 240, 300]:
                        if sample_time_minutes >= len(df_option):
                            continue
                        
                        option_bar = df_option.iloc[sample_time_minutes]
                        underlying_bar = df_day.iloc[min(sample_time_minutes, len(df_day)-1)]
                        
                        # Calculate metrics
                        moneyness = (underlying_bar['close'] - strike) / strike
                        time_to_close = 390 - sample_time_minutes  # Minutes until 4 PM
                        
                        all_samples.append({
                            'date': date_str,
                            'strike': strike,
                            'underlying_price': underlying_bar['close'],
                            'option_premium': option_bar['close'],
                            'moneyness': moneyness,
                            'distance_from_strike': abs(underlying_bar['close'] - strike),
                            'time_to_close_minutes': time_to_close,
                            'sample_time_minutes': sample_time_minutes,
                        })
                    
                    print(f"  ${strike} Call: Premium ${df_option.iloc[0]['close']:.2f} - ${df_option.iloc[-1]['close']:.2f}")
                
                # Rate limiting (5 calls per minute for free tier)
                time.sleep(12)
                
            except Exception as e:
                print(f"  Error fetching ${strike} call: {str(e)[:50]}")
                continue
        
        print()
        
    except Exception as e:
        print(f"Error on {date_str}: {str(e)[:50]}\n")
        continue

# Save samples
samples_df = pd.DataFrame(all_samples)
print(f"\n{'='*80}")
print(f"COLLECTED {len(samples_df)} OPTION PREMIUM SAMPLES")
print(f"{'='*80}\n")

if len(samples_df) > 0:
    # Save to file
    samples_df.to_csv('data/options_premium_samples.csv', index=False)
    print(f"Saved to: data/options_premium_samples.csv")
    
    # Display statistics
    print(f"\nPremium Statistics:")
    print(f"  Mean: ${samples_df['option_premium'].mean():.2f}")
    print(f"  Median: ${samples_df['option_premium'].median():.2f}")
    print(f"  Min: ${samples_df['option_premium'].min():.2f}")
    print(f"  Max: ${samples_df['option_premium'].max():.2f}")
    
    print(f"\nMoneyness Distribution:")
    print(f"  ITM (>0): {(samples_df['moneyness'] > 0).sum()} samples")
    print(f"  ATM (~0): {(samples_df['moneyness'].abs() < 0.01).sum()} samples")
    print(f"  OTM (<0): {(samples_df['moneyness'] < 0).sum()} samples")

print(f"\n{'='*80}\n")
