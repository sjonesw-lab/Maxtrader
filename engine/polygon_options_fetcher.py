"""
Polygon.io Options Data Fetcher
Fetches real historical options pricing for QQQ 0DTE options
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta


class PolygonOptionsFetcher:
    """Fetches historical options data from Polygon.io"""
    
    BASE_URL = "https://api.polygon.io"
    
    def __init__(self, api_key=None):
        """Initialize with API key."""
        self.api_key = api_key or os.getenv('POLYGON_API_KEY')
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY not found")
    
    def build_option_ticker(self, underlying, expiration_date, option_type, strike):
        """
        Build Polygon option ticker format.
        
        Args:
            underlying: 'QQQ'
            expiration_date: datetime or 'YYYY-MM-DD' string
            option_type: 'C' for call, 'P' for put
            strike: Strike price (e.g., 500.0)
            
        Returns:
            Option ticker like 'O:QQQ241117C00500000'
        """
        if isinstance(expiration_date, str):
            exp_date = datetime.strptime(expiration_date, '%Y-%m-%d')
        else:
            exp_date = expiration_date
        
        # Format: O:QQQ{YYMMDD}{C/P}{strike*1000, 8 digits}
        date_str = exp_date.strftime('%y%m%d')
        strike_str = f"{int(strike * 1000):08d}"
        
        return f"O:{underlying}{date_str}{option_type}{strike_str}"
    
    def fetch_option_bars(self, option_ticker, from_date, to_date):
        """
        Fetch 1-minute bars for an option contract.
        
        Args:
            option_ticker: Full option ticker (e.g., 'O:QQQ241117C00500000')
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            
        Returns:
            DataFrame with timestamp, open, high, low, close, volume
        """
        url = f"{self.BASE_URL}/v2/aggs/ticker/{option_ticker}/range/1/minute/{from_date}/{to_date}"
        params = {
            'apiKey': self.api_key,
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"Polygon API error: {response.status_code} - {response.text}")
        
        data = response.json()
        
        if data.get('status') != 'OK':
            return None  # No data for this contract
        
        if 'results' not in data or len(data['results']) == 0:
            return None
        
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
        
        return df
    
    def get_atm_strike(self, underlying_price, strike_interval=5):
        """
        Find the nearest ATM strike price.
        
        Args:
            underlying_price: Current price of underlying (e.g., 502.35)
            strike_interval: Strike price interval (default 5 for QQQ)
            
        Returns:
            Nearest strike price
        """
        return round(underlying_price / strike_interval) * strike_interval
    
    def fetch_multiple_strikes(self, underlying, expiration_date, underlying_price, 
                              option_type, num_strikes=3):
        """
        Fetch options data for multiple strikes around ATM.
        
        Args:
            underlying: 'QQQ'
            expiration_date: Date string 'YYYY-MM-DD'
            underlying_price: Current underlying price
            option_type: 'C' or 'P'
            num_strikes: Number of strikes to fetch (1=ATM, 2=ATM+1OTM, 3=ATM+2OTM)
            
        Returns:
            Dict of {strike: DataFrame}
        """
        atm_strike = self.get_atm_strike(underlying_price)
        
        results = {}
        
        for i in range(num_strikes):
            if option_type == 'C':
                strike = atm_strike + (i * 5)  # Calls go up
            else:
                strike = atm_strike - (i * 5)  # Puts go down
            
            ticker = self.build_option_ticker(underlying, expiration_date, option_type, strike)
            
            try:
                df = self.fetch_option_bars(ticker, expiration_date, expiration_date)
                if df is not None:
                    results[strike] = df
            except Exception as e:
                continue
        
        return results
