"""
Real-time market data streaming from Polygon.io.

Streams 1-minute bars for QQQ and processes them through ICT structure detection.
"""

import os
from typing import Callable, Optional
from polygon import WebSocketClient
from polygon.websocket.models import WebSocketMessage, EquityAgg
import pandas as pd
from datetime import datetime
import pytz


class PolygonStreamHandler:
    """Handles real-time 1-minute bar streaming from Polygon."""
    
    def __init__(self, symbol: str = "QQQ", callback: Optional[Callable] = None):
        """
        Initialize Polygon WebSocket stream.
        
        Args:
            symbol: Stock symbol to stream (default: QQQ)
            callback: Function to call when new bar arrives (receives pd.Series)
        """
        self.symbol = symbol
        self.callback = callback
        
        api_key = os.getenv('POLYGON_API_KEY')
        if not api_key:
            raise ValueError("POLYGON_API_KEY environment variable not set")
        
        self.client = WebSocketClient(
            api_key=api_key,
            feed="delayed.polygon.io",
            market="stocks",
            verbose=True
        )
        
        self.bar_buffer = []
        
    def start(self):
        """Start streaming minute aggregates for the symbol."""
        self.client.subscribe(f"AM.{self.symbol}")
        print(f"Subscribed to {self.symbol} 1-minute bars")
        self.client.run(self._handle_message)
        
    def _handle_message(self, msgs: list):
        """
        Handle incoming WebSocket messages.
        
        Args:
            msgs: List of WebSocket messages from Polygon
        """
        for msg in msgs:
            if isinstance(msg, EquityAgg):
                bar = self._convert_to_bar(msg)
                
                if self.callback:
                    self.callback(bar)
                else:
                    print(f"New bar: {bar['timestamp']} O:{bar['open']:.2f} H:{bar['high']:.2f} "
                          f"L:{bar['low']:.2f} C:{bar['close']:.2f} V:{bar['volume']}")
    
    def _convert_to_bar(self, msg: EquityAgg) -> pd.Series:
        """
        Convert Polygon message to standard bar format.
        
        Args:
            msg: Polygon equity aggregate message
            
        Returns:
            Pandas Series with OHLCV data
        """
        ts_unix = msg.start_timestamp
        ts = datetime.fromtimestamp(ts_unix / 1000, tz=pytz.UTC)
        ts_ny = ts.astimezone(pytz.timezone('America/New_York'))
        
        bar = pd.Series({
            'timestamp': ts_ny,
            'open': msg.open,
            'high': msg.high,
            'low': msg.low,
            'close': msg.close,
            'volume': msg.volume,
            'symbol': msg.symbol
        })
        
        return bar
    
    def stop(self):
        """Stop the WebSocket stream."""
        if hasattr(self.client, 'websocket') and self.client.websocket:
            self.client.websocket.close()
            print(f"Stopped streaming {self.symbol}")


if __name__ == '__main__':
    def on_bar(bar):
        print(f"\nReceived bar at {bar['timestamp']}")
        print(f"  OHLCV: {bar['open']:.2f} / {bar['high']:.2f} / "
              f"{bar['low']:.2f} / {bar['close']:.2f} / {bar['volume']}")
    
    stream = PolygonStreamHandler(symbol="QQQ", callback=on_bar)
    
    try:
        stream.start()
    except KeyboardInterrupt:
        print("\nStopping stream...")
        stream.stop()
