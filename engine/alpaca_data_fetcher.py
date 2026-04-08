"""
Alpaca API Data Fetcher
Fetches real-time 1-minute bar data from Alpaca (for live trading)
"""
import os
import pandas as pd
from datetime import datetime
from collections import deque
from alpaca.data.live import StockDataStream
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
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
        try:
            self.client = StockHistoricalDataClient(self.api_key, self.api_secret)
            self.stream = StockDataStream(self.api_key, self.api_secret)
            self._buffers = {}
            print(f"✓ Alpaca client initialized ({'Paper' if paper else 'Live'} account)")
        except Exception as e:
            print(f"⚠️  Error initializing Alpaca client: {str(e)}")
    
    def start_bar_stream(self, symbol='QQQ', on_bar=None, maxlen=300):
        if symbol not in self._buffers:
            self._buffers[symbol] = deque(maxlen=maxlen)

        def handle_bar(bar):
            row = {
                'timestamp': bar.timestamp,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            }
            self._buffers[symbol].append(row)
            if on_bar:
                on_bar(row)

        self.stream.subscribe_bars(handle_bar, symbol)
        return self.stream

    def get_recent_bars(self, symbol='QQQ', lookback_minutes=390):
        buf = self._buffers.get(symbol)
        if not buf:
            return pd.DataFrame()
        df = pd.DataFrame(list(buf))
        if len(df) == 0:
            return df
        return df.sort_values('timestamp').reset_index(drop=True)

    def get_latest_bar(self, ticker):
        request = StockLatestBarRequest(symbol_or_symbols=ticker)
        bars = self.client.get_stock_latest_bar(request)
        if not bars or ticker not in bars:
            return None
        bar = bars[ticker]
        return {
            'timestamp': bar.timestamp,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume
        }

    def get_live_bar_history(self, ticker, minutes=390):
        return self.get_recent_bars(ticker, lookback_minutes=minutes)
