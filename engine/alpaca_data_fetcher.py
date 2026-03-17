"""
Alpaca API Data Fetcher
Fetches real-time 1-minute bar data from Alpaca (for live trading)
"""
import os
import pandas as pd
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


class AlpacaDataFetcher:
    """Fetches real-time 1-minute bars from Alpaca API (live account)"""
    
    def __init__(self, api_key=None, api_secret=None, paper=False):
        """
        Initialize Alpaca data fetcher
        
        Args:
            api_key: Alpaca API key (defaults to ALPACA_API_KEY env var)
            api_secret: Alpaca API secret (defaults to ALPACA_API_SECRET env var)
            paper: Use paper trading endpoints (default: False for live account)
        """
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET not found in environment")
        
        # Initialize Alpaca data client for live account
        # Note: paper=False uses live trading data endpoint
        try:
            self.client = StockHistoricalDataClient(self.api_key, self.api_secret)
            print(f"✓ Alpaca client initialized ({'Paper' if paper else 'Live'} account)")
        except Exception as e:
            print(f"⚠️  Error initializing Alpaca client: {str(e)}")
    
    def fetch_stock_bars(self, ticker, from_date, to_date, limit=50000):
        """
        Fetch 1-minute stock bars from Alpaca
        
        Args:
            ticker: Stock symbol (e.g., 'QQQ', 'SPY')
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            limit: Max bars per request (default 50000)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            # Parse dates
            start = datetime.strptime(from_date, '%Y-%m-%d')
            end = datetime.strptime(to_date, '%Y-%m-%d')
            
            # Request bars from Alpaca
            request = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
                limit=limit
            )
            
            print(f"Fetching {ticker} bars from {from_date} to {to_date} (Alpaca)...")
            bars = self.client.get_stock_bars(request)
            
            if not bars:
                raise Exception(f"No data returned for {ticker}")
            
            # Convert to DataFrame using the built-in .df method
            df = bars.df.reset_index()
            
            # Rename/standardize columns
            df.columns = df.columns.str.lower()
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            print(f"  ✓ Fetched {len(df):,} bars for {ticker}")
            return df
            
        except Exception as e:
            print(f"⚠️  Alpaca API error: {str(e)}")
            raise
