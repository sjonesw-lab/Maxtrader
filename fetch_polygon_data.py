"""
Fetch real QQQ 1-minute data from Polygon.io

Downloads historical intraday data and saves to CSV format compatible
with the existing backtest pipeline.

Usage:
    python fetch_polygon_data.py --start 2024-01-01 --end 2024-03-31
    python fetch_polygon_data.py --days 60  # Last 60 trading days
"""

import os
import argparse
from datetime import datetime, timedelta
import pandas as pd
import requests
from pathlib import Path
import time


def fetch_polygon_bars(symbol: str, start_date: str, end_date: str, api_key: str) -> pd.DataFrame:
    """
    Fetch 1-minute bars from Polygon.io.
    
    Args:
        symbol: Ticker symbol (e.g., 'QQQ')
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        api_key: Polygon API key
    
    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    base_url = "https://api.polygon.io/v2/aggs/ticker"
    
    url = f"{base_url}/{symbol}/range/1/minute/{start_date}/{end_date}"
    
    params = {
        'adjusted': 'true',
        'sort': 'asc',
        'limit': 50000,
        'apiKey': api_key
    }
    
    print(f"Fetching {symbol} data from {start_date} to {end_date}...")
    print(f"URL: {url}")
    
    all_results = []
    next_url = url
    
    while next_url:
        print(f"  Request: {len(all_results)} bars fetched so far...")
        
        if next_url == url:
            response = requests.get(url, params=params)
        else:
            response = requests.get(next_url + f"&apiKey={api_key}")
        
        if response.status_code != 200:
            print(f"ERROR: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            raise Exception(f"Polygon API error: {response.status_code}")
        
        data = response.json()
        
        if data['status'] == 'DELAYED':
            print(f"  Note: Free tier has 15-minute delay, continuing...")
        elif data['status'] != 'OK':
            print(f"ERROR: API returned status {data['status']}")
            print(f"Response: {data}")
            raise Exception(f"Polygon API error: {data.get('status')}")
        
        if 'results' in data and data['results']:
            all_results.extend(data['results'])
            print(f"    + {len(data['results'])} bars")
        
        next_url = data.get('next_url')
        
        if next_url:
            time.sleep(0.25)
    
    print(f"✓ Total bars fetched: {len(all_results)}")
    
    if not all_results:
        raise Exception("No data returned from Polygon API")
    
    df = pd.DataFrame(all_results)
    
    df['timestamp'] = pd.to_datetime(df['t'], unit='ms', utc=True)
    df = df.rename(columns={
        'o': 'open',
        'h': 'high',
        'l': 'low',
        'c': 'close',
        'v': 'volume'
    })
    
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    return df


def filter_trading_hours(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter to regular trading hours (09:30-16:00 ET) and extended hours for Asia session.
    
    Keeps:
    - Asia session: 18:00-03:00 ET (6pm-3am)
    - London session: 03:00-09:30 ET (3am-9:30am)
    - NY session: 09:30-16:00 ET (9:30am-4pm)
    """
    df = df.copy()
    df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York')
    
    df['hour'] = df['timestamp'].dt.hour
    df['minute'] = df['timestamp'].dt.minute
    
    mask = (
        ((df['hour'] >= 18) | (df['hour'] < 3)) |
        ((df['hour'] >= 3) & (df['hour'] < 9)) |
        ((df['hour'] == 9) & (df['minute'] >= 30)) |
        ((df['hour'] >= 10) & (df['hour'] < 16))
    )
    
    df = df[mask].copy()
    df = df.drop(['hour', 'minute'], axis=1)
    
    return df


def main():
    parser = argparse.ArgumentParser(description='Fetch QQQ data from Polygon.io')
    parser.add_argument('--symbol', type=str, default='QQQ', help='Ticker symbol')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, help='Number of days back from today')
    parser.add_argument('--output', type=str, default='data/QQQ_1m_real.csv',
                       help='Output CSV file path')
    parser.add_argument('--filter-hours', action='store_true', default=True,
                       help='Filter to trading hours only')
    
    args = parser.parse_args()
    
    api_key = os.getenv('POLYGON_API_KEY')
    if not api_key:
        print("ERROR: POLYGON_API_KEY environment variable not set")
        print("Please add your Polygon API key to Replit Secrets")
        return
    
    if args.days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
    elif args.start and args.end:
        start_str = args.start
        end_str = args.end
    else:
        print("ERROR: Must specify either --days or both --start and --end")
        return
    
    print("=" * 70)
    print("Polygon.io Data Fetcher")
    print("=" * 70)
    print()
    print(f"Symbol: {args.symbol}")
    print(f"Period: {start_str} to {end_str}")
    print(f"Output: {args.output}")
    print()
    
    try:
        df = fetch_polygon_bars(args.symbol, start_str, end_str, api_key)
        
        print(f"\nRaw data: {len(df)} bars")
        print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print()
        
        if args.filter_hours:
            print("Filtering to trading hours (Asia/London/NY sessions)...")
            df = filter_trading_hours(df)
            print(f"  ✓ Filtered to {len(df)} bars during trading hours")
            print()
        
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        
        df.to_csv(args.output, index=False)
        print(f"✓ Saved to {args.output}")
        print()
        
        print("Data Summary:")
        print("-" * 70)
        print(f"Total bars: {len(df)}")
        print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(f"Price range: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
        print(f"Avg volume: {df['volume'].mean():.0f}")
        print()
        
        print("First 5 bars:")
        print(df.head())
        print()
        
        print("=" * 70)
        print("SUCCESS - Real market data ready for optimization!")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1. Run: python optimizer_main.py --mode medium --splits 4")
        print("  2. Review: cat configs/strategy_params.json")
        print("  3. Backtest: python main_backtest_adaptive.py")
        print()
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
