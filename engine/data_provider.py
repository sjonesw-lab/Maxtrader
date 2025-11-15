"""
Data provider module for loading and preparing market data.

Supports CSV data loading with timezone conversion and provides
abstract interface for future live data providers (Polygon, Alpaca).
"""

from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd
import os


class DataProvider(ABC):
    """Abstract base class for data providers."""
    
    @abstractmethod
    def load_bars(self) -> pd.DataFrame:
        """
        Load OHLCV bar data.
        
        Returns:
            pd.DataFrame: DataFrame with columns: timestamp, open, high, low, close, volume
                         Timestamp should be tz-aware (America/New_York)
        """
        pass


class CSVDataProvider(DataProvider):
    """CSV-based data provider for backtesting."""
    
    def __init__(self, path: str, symbol: str = "QQQ"):
        """
        Initialize CSV data provider.
        
        Args:
            path: Path to CSV file
            symbol: Symbol name (default: QQQ)
        """
        self.path = path
        self.symbol = symbol
        
    def load_bars(self) -> pd.DataFrame:
        """
        Load OHLCV data from CSV, convert timestamps to tz-aware America/New_York,
        sort by time, and return a clean DataFrame.
        
        Expected CSV columns: timestamp, open, high, low, close, volume
        Timestamp should be in ISO8601 UTC format.
        
        Returns:
            pd.DataFrame: Clean OHLCV data with tz-aware timestamps
        """
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Data file not found: {self.path}")
            
        df = pd.read_csv(self.path)
        
        required_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        missing = set(required_columns) - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York')
        
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        result: pd.DataFrame = df[required_columns]
        
        return result


class PolygonDataProvider(DataProvider):
    """
    Polygon.io data provider (placeholder for future implementation).
    
    Usage will require POLYGON_API_KEY from environment variables.
    """
    
    def __init__(self, symbol: str = "QQQ", api_key: Optional[str] = None):
        """
        Initialize Polygon data provider.
        
        Args:
            symbol: Symbol to fetch
            api_key: Polygon API key (if None, will read from env var POLYGON_API_KEY)
        """
        self.symbol = symbol
        self.api_key = api_key or os.getenv('POLYGON_API_KEY')
        
    def load_bars(self) -> pd.DataFrame:
        """
        Load bars from Polygon API.
        
        Future implementation will:
        1. Use requests library to call Polygon REST API
        2. Fetch minute bars for specified date range
        3. Convert timestamps to America/New_York timezone
        4. Return standardized DataFrame
        
        Returns:
            pd.DataFrame: OHLCV data
        """
        raise NotImplementedError(
            "Polygon integration not yet implemented. "
            "Set POLYGON_API_KEY environment variable and implement API calls here."
        )


class AlpacaDataProvider(DataProvider):
    """
    Alpaca data provider (placeholder for future implementation).
    
    Usage will require ALPACA_API_KEY and ALPACA_SECRET_KEY from environment.
    """
    
    def __init__(self, symbol: str = "QQQ", 
                 api_key: Optional[str] = None,
                 secret_key: Optional[str] = None):
        """
        Initialize Alpaca data provider.
        
        Args:
            symbol: Symbol to fetch
            api_key: Alpaca API key
            secret_key: Alpaca secret key
        """
        self.symbol = symbol
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.secret_key = secret_key or os.getenv('ALPACA_SECRET_KEY')
        
    def load_bars(self) -> pd.DataFrame:
        """
        Load bars from Alpaca API.
        
        Future implementation will:
        1. Use Alpaca REST API to fetch historical bars
        2. Convert to standardized OHLCV format
        3. Handle timezone conversion to America/New_York
        
        Returns:
            pd.DataFrame: OHLCV data
        """
        raise NotImplementedError(
            "Alpaca integration not yet implemented. "
            "Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables."
        )
