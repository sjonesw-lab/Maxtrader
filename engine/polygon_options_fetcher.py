"""
Polygon.io Options Data Fetcher
Fetches BOTH historical AND real-time options pricing for QQQ 0DTE options
"""
import os
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from typing import Dict, Optional, List


class PolygonOptionsFetcher:
    """Fetches historical AND real-time options data from Polygon.io"""
    
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
    
    def get_0dte_option_price(
        self,
        underlying_ticker: str,
        current_price: float,
        direction: str,
        strike_offset: int = 0
    ) -> Optional[Dict]:
        """
        Get REAL-TIME 0DTE option price from Polygon for paper trading.
        
        Args:
            underlying_ticker: Stock symbol (e.g., 'QQQ')
            current_price: Current underlying price
            direction: 'LONG' or 'SHORT'
            strike_offset: How many strikes OTM (0 = ATM, 1 = 1 OTM, etc.)
        
        Returns:
            Dict with option details or None if not found:
            {
                'contract': 'O:QQQ251117C00500000',
                'strike': 500.0,
                'bid': 2.15,
                'ask': 2.25,
                'last': 2.20,
                'midpoint': 2.20,
                'delta': 0.52,
                'iv': 0.18,
                'premium': 220.0  # ask * 100 for realistic entry fill
            }
        """
        try:
            # Get today's date for 0DTE
            today = date.today().strftime("%Y-%m-%d")
            
            # Determine contract type
            contract_type = "call" if direction == "LONG" else "put"
            
            # Calculate target strike (QQQ uses $5 increments)
            strike_increment = 5.0 if current_price >= 100 else 1.0
            atm_strike = round(current_price / strike_increment) * strike_increment
            
            # Adjust for OTM offset
            if direction == "LONG":
                target_strike = atm_strike + (strike_offset * strike_increment)
            else:
                target_strike = atm_strike - (strike_offset * strike_increment)
            
            # Fetch options chain snapshot from Polygon
            url = f"{self.BASE_URL}/v3/snapshot/options/{underlying_ticker}"
            params = {
                'apiKey': self.api_key,
                'expiration_date': today,
                'contract_type': contract_type,
                'strike_price.gte': target_strike - strike_increment,
                'strike_price.lte': target_strike + strike_increment,
                'limit': 10
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') != 'OK' or not data.get('results'):
                print(f"⚠️  No 0DTE options data for {underlying_ticker} {contract_type} @ ${target_strike}")
                return None
            
            # Find closest strike to target
            contracts = data['results']
            closest_contract = min(
                contracts,
                key=lambda x: abs(x['details']['strike_price'] - target_strike)
            )
            
            # Extract REAL pricing data
            last_quote = closest_contract.get('last_quote', {})
            greeks = closest_contract.get('greeks', {})
            details = closest_contract['details']
            
            bid = last_quote.get('bid', 0)
            ask = last_quote.get('ask', 0)
            last = closest_contract.get('last_trade', {}).get('price', 0)
            
            # Calculate midpoint
            if bid > 0 and ask > 0:
                midpoint = (bid + ask) / 2
            elif last > 0:
                midpoint = last
            else:
                print(f"⚠️  No valid pricing for {details.get('ticker')}")
                return None
            
            # Use ASK for entry (realistic fill - you pay the ask)
            premium = ask * 100 if ask > 0 else midpoint * 100
            
            option_data = {
                'contract': details.get('ticker', 'UNKNOWN'),
                'strike': details['strike_price'],
                'bid': bid,
                'ask': ask,
                'last': last,
                'midpoint': midpoint,
                'delta': greeks.get('delta', 0),
                'iv': closest_contract.get('implied_volatility', 0),
                'premium': premium,  # Cost per contract (ask * 100)
                'expiration': details.get('expiration_date', today)
            }
            
            print(f"✅ Real 0DTE {contract_type}: {option_data['contract']} @ ${option_data['strike']:.2f}")
            print(f"   Bid/Ask: ${bid:.2f}/${ask:.2f}, Premium: ${premium:.2f}, Delta: {option_data['delta']:.2f}")
            
            return option_data
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print("⚠️  Polygon API rate limit - too many requests")
            elif e.response.status_code == 403:
                print("⚠️  Polygon API access denied - check plan level for real-time data")
            else:
                print(f"❌ HTTP error: {e}")
            return None
        except Exception as e:
            print(f"❌ Error fetching 0DTE option: {e}")
            return None
    
    def get_exit_price(self, contract_ticker: str) -> Optional[float]:
        """
        Get REAL-TIME bid price for exiting an option position.
        Uses BID price (conservative - you sell at the bid).
        
        Args:
            contract_ticker: Option contract symbol (e.g., 'O:QQQ251117C00500000')
        
        Returns:
            Exit value per contract (bid * 100) or None
        """
        try:
            url = f"{self.BASE_URL}/v3/snapshot/options/{contract_ticker}"
            params = {'apiKey': self.api_key}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') != 'OK' or not data.get('results'):
                print(f"⚠️  No data for {contract_ticker}")
                return None
            
            result = data['results']
            last_quote = result.get('last_quote', {})
            bid = last_quote.get('bid', 0)
            
            # If bid is 0, option likely expired worthless or no market
            if bid == 0:
                last_trade = result.get('last_trade', {})
                last_price = last_trade.get('price', 0)
                if last_price > 0:
                    print(f"   Using last trade price (no bid): ${last_price:.2f}")
                    return last_price * 100
                print(f"   Option worthless: $0.00")
                return 0  # Worthless
            
            print(f"   Exit at bid: ${bid:.2f} = ${bid * 100:.2f} per contract")
            return bid * 100
            
        except Exception as e:
            print(f"❌ Error fetching exit price: {e}")
            return None
