"""
Order Executor - Abstraction layer for order routing and fill simulation.

Provides a unified interface for:
- Backtest mode (simulated fills with realistic slippage/spreads)
- Live/Paper mode (real broker API integration)
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import random
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderFill:
    """Represents a filled order."""
    fill_price: float
    fill_time: datetime
    latency_ms: float  # Time from order submission to fill
    slippage: float = 0.0


class OrderExecutor:
    """
    Abstract order executor for both backtest and live modes.
    
    In backtest mode: Simulates fills with realistic bid/ask/spread assumptions
    In live mode: Routes orders to broker API (Alpaca, IBKR, etc.)
    """
    
    def __init__(self, mode: str = 'backtest', **kwargs):
        """
        Initialize order executor.
        
        Args:
            mode: 'backtest' or 'live'
            **kwargs: Mode-specific configuration
        """
        self.mode = mode
        self.config = kwargs
        logger.info(f"OrderExecutor initialized in {mode} mode")
    
    def execute_spread_exit(
        self,
        spread: 'VerticalSpread',
        limit_price: float,
        max_slippage: float
    ) -> Optional[OrderFill]:
        """
        Execute exit of a vertical spread.
        
        Args:
            spread: Vertical spread to close
            limit_price: Limit price for the spread order
            max_slippage: Maximum acceptable slippage
            
        Returns:
            OrderFill if successful, None if failed
        """
        if self.mode == 'backtest':
            return self._simulate_spread_fill(spread, limit_price, max_slippage)
        elif self.mode == 'live':
            return self._execute_live_spread(spread, limit_price, max_slippage)
        else:
            raise ValueError(f"Unknown executor mode: {self.mode}")
    
    def _simulate_spread_fill(
        self,
        spread: 'VerticalSpread',
        limit_price: float,
        max_slippage: float
    ) -> Optional[OrderFill]:
        """
        Simulate spread fill with realistic assumptions.
        
        Simulation model:
        - Use current bid/ask to calculate realistic spread
        - Add random slippage within bounds
        - Simulate latency (10-100ms typical)
        """
        if not spread.leg1.current_bid or not spread.leg1.current_ask:
            logger.error("Missing bid/ask data for simulation")
            return None
        
        if not spread.leg2.current_bid or not spread.leg2.current_ask:
            logger.error("Missing bid/ask data for simulation")
            return None
        
        # Calculate natural bid/ask for the spread
        # When closing a debit spread, we're selling it back:
        # - Sell the long leg at bid
        # - Buy back the short leg at ask
        leg1_price = spread.leg1.current_bid if spread.leg1.side == 'long' else spread.leg1.current_ask
        leg2_price = spread.leg2.current_ask if spread.leg2.side == 'short' else spread.leg2.current_bid
        
        # Natural spread price (what we'd get in perfect conditions)
        natural_price = abs(leg1_price - leg2_price) * 100  # Contract multiplier
        
        # Simulate realistic slippage (0-2% of natural price)
        slippage_config = self.config.get('slippage_model', {})
        min_slippage_pct = slippage_config.get('min_pct', 0.001)  # 0.1%
        max_slippage_pct = slippage_config.get('max_pct', 0.020)  # 2.0%
        
        slippage_pct = random.uniform(min_slippage_pct, max_slippage_pct)
        slippage_amount = natural_price * slippage_pct
        
        # Apply slippage (we receive less when closing)
        fill_price = natural_price - slippage_amount
        
        # ENFORCE slippage limits - reject fill if exceeds maximum
        if slippage_amount > max_slippage:
            logger.error(
                f"Simulated slippage ${slippage_amount:.2f} exceeds max ${max_slippage:.2f} - REJECTING FILL"
            )
            return None  # Fill rejected
        
        # Also check limit price
        if fill_price < limit_price:
            logger.error(
                f"Fill price ${fill_price:.2f} below limit ${limit_price:.2f} - REJECTING FILL"
            )
            return None  # Fill rejected
        
        # Simulate latency (10-150ms)
        latency_ms = random.uniform(10, 150)
        
        # CRITICAL: Apply latency to fill timestamp for realistic timing
        from datetime import timedelta
        fill_time = datetime.now() + timedelta(milliseconds=latency_ms)
        
        return OrderFill(
            fill_price=fill_price,
            fill_time=fill_time,
            latency_ms=latency_ms,
            slippage=slippage_amount
        )
    
    def _execute_live_spread(
        self,
        spread: 'VerticalSpread',
        limit_price: float,
        max_slippage: float
    ) -> Optional[OrderFill]:
        """
        Execute spread order via live broker API.
        
        This would integrate with Alpaca, Interactive Brokers, etc.
        
        TODO: Implement live broker integration
        - Place spread order as combo order
        - Monitor for fill
        - Return OrderFill on success
        """
        raise NotImplementedError(
            "Live broker integration not yet implemented. "
            "Use mode='backtest' for simulation."
        )


class BacktestExecutor(OrderExecutor):
    """
    Specialized executor for backtesting with configurable slippage models.
    """
    
    def __init__(self, slippage_model: Optional[dict] = None):
        """
        Initialize backtest executor.
        
        Args:
            slippage_model: Dictionary with slippage configuration:
                - min_pct: Minimum slippage percentage (default: 0.001 = 0.1%)
                - max_pct: Maximum slippage percentage (default: 0.020 = 2.0%)
                - spread_pct: Bid-ask spread as % of mid (default: 0.01 = 1.0%)
        """
        slippage_model = slippage_model or {
            'min_pct': 0.001,
            'max_pct': 0.020,
            'spread_pct': 0.01
        }
        super().__init__(mode='backtest', slippage_model=slippage_model)


class LiveExecutor(OrderExecutor):
    """
    Specialized executor for live/paper trading via broker API.
    """
    
    def __init__(self, broker: str = 'alpaca', api_key: Optional[str] = None,
                 api_secret: Optional[str] = None, paper: bool = True):
        """
        Initialize live executor.
        
        Args:
            broker: Broker name ('alpaca', 'ibkr', etc.)
            api_key: API key for broker
            api_secret: API secret for broker
            paper: Use paper trading mode
        """
        super().__init__(
            mode='live',
            broker=broker,
            api_key=api_key,
            api_secret=api_secret,
            paper=paper
        )
        logger.info(f"LiveExecutor configured for {broker} (paper={paper})")
