"""
Alpaca paper trading execution engine for options.

Handles options order placement, position management, and P&L tracking.
"""

import os
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import pytz
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import OrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, OrderClass
from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest


class AlpacaOptionsExecutor:
    """Handles options execution via Alpaca paper trading API."""
    
    def __init__(self, paper: bool = True):
        """
        Initialize Alpaca trading client.
        
        Args:
            paper: Use paper trading (default: True)
        """
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_API_SECRET')
        
        if not api_key or not secret_key:
            raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET environment variables required")
        
        self.client = TradingClient(api_key, secret_key, paper=paper)
        self.data_client = OptionHistoricalDataClient(api_key, secret_key)
        self.paper = paper
        
        print(f"Alpaca {'Paper' if paper else 'Live'} Trading initialized")
        
    def get_account_info(self) -> Dict:
        """Get account information."""
        account = self.client.get_account()
        return {
            'buying_power': float(account.buying_power),
            'cash': float(account.cash),
            'portfolio_value': float(account.portfolio_value),
            'equity': float(account.equity)
        }
    
    def get_options_chain(self, underlying: str, days_to_expiry: int = 7) -> List:
        """
        Get options chain for underlying symbol.
        
        Args:
            underlying: Stock symbol (e.g., 'QQQ')
            days_to_expiry: Days until expiration (default: 7 for weekly)
            
        Returns:
            List of available option contracts
        """
        today = datetime.now(pytz.timezone('America/New_York'))
        expiry_start = today + timedelta(days=days_to_expiry-1)
        expiry_end = today + timedelta(days=days_to_expiry+1)
        
        request = OptionChainRequest(
            underlying_symbol=underlying,
            expiration_date_gte=expiry_start.strftime('%Y-%m-%d'),
            expiration_date_lte=expiry_end.strftime('%Y-%m-%d')
        )
        
        chain = self.data_client.get_option_chain(request)
        return chain
    
    def find_nearest_strike(self, spot: float, direction: str, chain: List, delta: float = 0.3) -> Optional[str]:
        """
        Find nearest strike for options position.
        
        Args:
            spot: Current underlying price
            direction: 'long' or 'short' 
            chain: Options chain data
            delta: Target delta (default: 0.3)
            
        Returns:
            OCC symbol for selected option or None
        """
        if not chain:
            return None
        
        option_type = 'C' if direction == 'long' else 'P'
        
        candidates = [c for c in chain if option_type in c.symbol]
        
        if not candidates:
            return None
        
        candidates.sort(key=lambda x: abs(x.strike_price - spot))
        
        if candidates:
            return candidates[0].symbol
        
        return None
    
    def place_long_option(
        self, 
        symbol: str,
        direction: str,
        spot: float,
        qty: int = 1,
        limit_price: Optional[float] = None
    ) -> Optional[str]:
        """
        Place long options order (call for bullish, put for bearish).
        
        Args:
            symbol: Underlying symbol (e.g., 'QQQ')
            direction: 'long' or 'short'
            spot: Current underlying price
            qty: Number of contracts (default: 1)
            limit_price: Limit price per contract (default: None = market order)
            
        Returns:
            Order ID or None if failed
        """
        try:
            chain = self.get_options_chain(symbol, days_to_expiry=7)
            option_symbol = self.find_nearest_strike(spot, direction, chain)
            
            if not option_symbol:
                print(f"No suitable options contract found for {symbol} @ ${spot}")
                return None
            
            if limit_price:
                order_data = LimitOrderRequest(
                    symbol=option_symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price
                )
            else:
                order_data = OrderRequest(
                    symbol=option_symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY
                )
            
            order = self.client.submit_order(order_data)
            
            print(f"Order submitted: {order.id}")
            print(f"  Symbol: {option_symbol}")
            print(f"  Qty: {qty}")
            print(f"  Side: BUY")
            
            return order.id
            
        except Exception as e:
            print(f"Error placing order: {e}")
            return None
    
    def get_positions(self) -> List:
        """Get current options positions."""
        try:
            positions = self.client.get_all_positions()
            return [
                {
                    'symbol': p.symbol,
                    'qty': float(p.qty),
                    'avg_entry_price': float(p.avg_entry_price),
                    'current_price': float(p.current_price),
                    'market_value': float(p.market_value),
                    'unrealized_pl': float(p.unrealized_pl),
                    'unrealized_plpc': float(p.unrealized_plpc)
                }
                for p in positions
            ]
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def close_position(self, symbol: str) -> bool:
        """
        Close an existing options position.
        
        Args:
            symbol: OCC symbol to close
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.client.close_position(symbol)
            print(f"Closed position: {symbol}")
            return True
        except Exception as e:
            print(f"Error closing position: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get order status.
        
        Args:
            order_id: Order ID to check
            
        Returns:
            Order details or None
        """
        try:
            order = self.client.get_order_by_id(order_id)
            return {
                'id': order.id,
                'symbol': order.symbol,
                'status': order.status,
                'filled_qty': float(order.filled_qty) if order.filled_qty else 0,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None
            }
        except Exception as e:
            print(f"Error fetching order: {e}")
            return None


if __name__ == '__main__':
    executor = AlpacaOptionsExecutor(paper=True)
    
    account = executor.get_account_info()
    print("\nAccount Info:")
    print(f"  Buying Power: ${account['buying_power']:.2f}")
    print(f"  Cash: ${account['cash']:.2f}")
    print(f"  Portfolio Value: ${account['portfolio_value']:.2f}")
    
    print("\nCurrent Positions:")
    positions = executor.get_positions()
    if positions:
        for p in positions:
            print(f"  {p['symbol']}: {p['qty']} contracts @ ${p['avg_entry_price']:.2f}")
            print(f"    Current: ${p['current_price']:.2f}, P&L: ${p['unrealized_pl']:.2f}")
    else:
        print("  No open positions")
