"""
Polygon.io API Data Fetcher
Fetches real 1-minute bar data for stocks and forex pairs
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time


class PolygonDataFetcher:
    """Fetches historical 1-minute bars from Polygon.io API"""
    
    BASE_URL = "https://api.polygon.io"
    
    def __init__(self, api_key=None):
        """
        Initialize Polygon data fetcher
        
        Args:
            api_key: Polygon API key (defaults to POLYGON_API_KEY env var)
        """
        self.api_key = api_key or os.getenv('POLYGON_API_KEY')
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY not found in environment")
    
    def fetch_stock_bars(self, ticker, from_date, to_date, limit=50000):
        """
        Fetch 1-minute stock bars
        
        Args:
            ticker: Stock symbol (e.g., 'QQQ', 'SPY')
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            limit: Max bars per request (default 50000)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        url = f"{self.BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{from_date}/{to_date}"
        params = {
            'apiKey': self.api_key,
            'adjusted': 'true',
            'sort': 'asc',
            'limit': limit
        }
        
        print(f"Fetching {ticker} bars from {from_date} to {to_date}...")
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"Polygon API error: {response.status_code} - {response.text}")
        
        data = response.json()
        
        status = data.get('status')
        if status not in ['OK', 'DELAYED']:
            raise Exception(f"Polygon API returned status: {status}")
        
        if status == 'DELAYED':
            print(f"  ⚠️  Using delayed data (15-min delay) - OK for paper trading")
        
        if 'results' not in data or len(data['results']) == 0:
            raise Exception(f"No data returned for {ticker}")
        
        bars = []
        for result in data['results']:
            bars.append({
                'timestamp': pd.to_datetime(result['t'], unit='ms', utc=True),
                'open': result['o'],
                'high': result['h'],
                'low': result['l'],
                'close': result['c'],
                'volume': result['v']
            })
        
        df = pd.DataFrame(bars)
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        print(f"  ✓ Fetched {len(df):,} bars for {ticker}")
        return df
    
    def fetch_forex_bars(self, from_currency, to_currency, from_date, to_date, limit=50000):
        """
        Fetch 1-minute forex bars
        
        Args:
            from_currency: Base currency (e.g., 'EUR')
            to_currency: Quote currency (e.g., 'USD')
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            limit: Max bars per request (default 50000)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        ticker = f"C:{from_currency}{to_currency}"
        url = f"{self.BASE_URL}/v2/aggs/ticker/{ticker}/range/1/minute/{from_date}/{to_date}"
        params = {
            'apiKey': self.api_key,
            'adjusted': 'true',
            'sort': 'asc',
            'limit': limit
        }
        
        print(f"Fetching {from_currency}/{to_currency} bars from {from_date} to {to_date}...")
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"Polygon API error: {response.status_code} - {response.text}")
        
        data = response.json()
        
        if data.get('status') != 'OK':
            raise Exception(f"Polygon API returned status: {data.get('status')}")
        
        if 'results' not in data or len(data['results']) == 0:
            raise Exception(f"No data returned for {from_currency}/{to_currency}")
        
        bars = []
        for result in data['results']:
            bars.append({
                'timestamp': pd.to_datetime(result['t'], unit='ms', utc=True),
                'open': result['o'],
                'high': result['h'],
                'low': result['l'],
                'close': result['c'],
                'volume': result.get('v', 0)  # Forex may not have volume
            })
        
        df = pd.DataFrame(bars)
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        print(f"  ✓ Fetched {len(df):,} bars for {from_currency}/{to_currency}")
        return df
    
    def fetch_multiple_instruments(self, instruments, from_date, to_date, rate_limit_delay=12):
        """
        Fetch data for multiple instruments (respects Polygon free tier: 5 calls/min)
        
        Args:
            instruments: List of dict with 'type' ('stock' or 'forex') and ticker info
                        Stock example: {'type': 'stock', 'ticker': 'QQQ'}
                        Forex example: {'type': 'forex', 'from': 'EUR', 'to': 'USD'}
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            rate_limit_delay: Seconds to wait between requests (default 12s for free tier)
            
        Returns:
            Dict mapping instrument name to DataFrame
        """
        results = {}
        
        for i, instrument in enumerate(instruments):
            if i > 0:
                # Rate limiting for free tier (5 calls/min)
                print(f"  Rate limiting... waiting {rate_limit_delay}s")
                time.sleep(rate_limit_delay)
            
            try:
                if instrument['type'] == 'stock':
                    ticker = instrument['ticker']
                    df = self.fetch_stock_bars(ticker, from_date, to_date)
                    results[ticker] = df
                    
                elif instrument['type'] == 'forex':
                    from_curr = instrument['from']
                    to_curr = instrument['to']
                    df = self.fetch_forex_bars(from_curr, to_curr, from_date, to_date)
                    results[f"{from_curr}{to_curr}"] = df
                    
            except Exception as e:
                print(f"  ✗ Error fetching {instrument}: {e}")
                continue
        
        return results
    
    def save_to_csv(self, df, filepath):
        """Save DataFrame to CSV file"""
        df.to_csv(filepath, index=False)
        print(f"  ✓ Saved to {filepath}")
