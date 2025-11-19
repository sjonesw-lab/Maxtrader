#!/usr/bin/env python3
"""
Fetch historical 1-minute data for SPY and INDA
NDX skipped - Polygon index data requires paid subscription
"""

import sys
sys.path.insert(0, '.')

import os
import pandas as pd
import time
from datetime import datetime, timedelta
from engine.polygon_data_fetcher import PolygonDataFetcher

def fetch_symbol_data_chunked(symbol, start_date, end_date):
    """Fetch data in chunks to bypass 50k bar limit"""
    print(f"\n{'='*60}")
    print(f"Fetching {symbol} from {start_date} to {end_date}")
    print('='*60)
    
    fetcher = PolygonDataFetcher()
    
    # Split into 3-month chunks
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    
    all_dfs = []
    current = start
    
    while current < end:
        chunk_end = min(current + pd.DateOffset(months=3), end)
        
        chunk_start_str = current.strftime('%Y-%m-%d')
        chunk_end_str = chunk_end.strftime('%Y-%m-%d')
        
        print(f"  Chunk: {chunk_start_str} to {chunk_end_str}")
        
        try:
            df = fetcher.fetch_stock_bars(
                ticker=symbol,
                from_date=chunk_start_str,
                to_date=chunk_end_str
            )
            
            if df is not None and len(df) > 0:
                all_dfs.append(df)
            
            # Rate limiting (5 calls/min on free tier)
            time.sleep(12)
            
        except Exception as e:
            print(f"  ⚠️  Error fetching chunk: {e}")
        
        current = chunk_end + pd.DateOffset(days=1)
    
    if len(all_dfs) > 0:
        final_df = pd.concat(all_dfs, ignore_index=True)
        final_df = final_df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        
        output_file = f'data/{symbol}_1m_2024_2025.csv'
        final_df.to_csv(output_file, index=False)
        print(f"✅ Saved {len(final_df):,} bars to {output_file}")
        print(f"   Date range: {final_df['timestamp'].min()} to {final_df['timestamp'].max()}")
        return True
    else:
        print(f"❌ No data retrieved for {symbol}")
        return False

if __name__ == '__main__':
    # Fetch all of 2024 + 2025 YTD (same as QQQ backtest)
    start_date = '2024-01-02'
    end_date = '2025-11-18'  # Match QQQ backtest
    
    # NDX requires paid Polygon subscription for index data, skip for now
    symbols = ['SPY', 'INDA']
    
    results = {}
    for symbol in symbols:
        success = fetch_symbol_data_chunked(symbol, start_date, end_date)
        results[symbol] = success
    
    print(f"\n{'='*60}")
    print("DOWNLOAD SUMMARY")
    print('='*60)
    for symbol, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{symbol}: {status}")
    
    print(f"\n⚠️  NDX skipped - requires paid Polygon subscription for index data")
    print(f"   Alternative: Use QQQ (highly correlated with NDX)")

