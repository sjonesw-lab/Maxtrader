"""
Live Trading Main - Production Trading Entry Point
Integrates SafetyManager with RegimeRouter for production 0DTE options trading
"""
import time
import logging
from datetime import datetime, timedelta
import pytz
import pandas as pd
from engine.regime_router import RegimeRouter
from engine.safety_manager import SafetyManager
from typing import Optional, Dict


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s]: %(message)s'
)
logger = logging.getLogger('LiveTrading')


class LiveTradingEngine:
    """
    Production trading engine with safety management
    
    Coordinates:
    - Regime detection and routing
    - Safety validation and monitoring
    - Signal generation and execution
    - Real-time monitoring and logging
    """
    
    def __init__(
        self,
        safety_config_path: str = 'configs/safety_config.yaml',
        initial_balance: float = 50000.0
    ):
        """Initialize live trading engine"""
        logger.info("Initializing LiveTradingEngine...")
        
        # Initialize components
        self.safety_manager = SafetyManager(safety_config_path)
        
        # Account state
        self.account_balance = initial_balance
        self.safety_manager.update_peak_balance(initial_balance)
        
        # Trading state
        self.current_regime: Optional[str] = None
        self.active_strategy: Optional[str] = None
        self.last_health_check: Optional[datetime] = None
        
        logger.info(f"LiveTradingEngine initialized with ${initial_balance:,.2f} balance")
    
    def pre_market_check(self) -> bool:
        """
        Run pre-market health checks
        
        Returns:
            True if system is ready to trade
        """
        logger.info("Running pre-market health checks...")
        
        # 1. Check if it's a trading day
        now = datetime.now(pytz.timezone('America/New_York'))
        if now.weekday() >= 5:  # Weekend
            logger.warning("Pre-market check failed: Weekend, no trading")
            return False
        
        # 2. Run system health checks
        healthy, issues = self.safety_manager.check_health()
        if not healthy:
            logger.error(f"Pre-market check failed: {', '.join(issues)}")
            return False
        
        # 3. Check safety controls
        if self.safety_manager.config['emergency']['kill_switch']:
            logger.error("Pre-market check failed: Kill switch is active")
            return False
        
        # 4. Reset daily state
        self.safety_manager.reset_daily_state()
        logger.info("Daily state reset complete")
        
        logger.info("✅ Pre-market checks passed - system ready to trade")
        return True
    
    def update_market_data(self, daily_data: pd.DataFrame, vix: float, atr_pct: float):
        """
        Update market data and detect regime
        
        Args:
            daily_data: Daily OHLCV bars
            vix: Current VIX value
            atr_pct: ATR as percentage of price
        """
        # Update data timestamp for health monitoring
        self.safety_manager.update_data_timestamp()
        
        # Detect current regime
        from engine.regime_router import RegimeRouter
        router = RegimeRouter(normal_vol_strategy=None)  # type: ignore
        
        prev_regime = self.current_regime
        self.current_regime = router.detect_regime(vix, atr_pct)
        
        if self.current_regime != prev_regime:
            logger.info(f"Regime change: {prev_regime} → {self.current_regime}")
            self._on_regime_change(prev_regime, self.current_regime)
    
    def _on_regime_change(self, old_regime: Optional[str], new_regime: str):
        """Handle regime transitions"""
        # EXTREME_CALM_PAUSE: Close all positions
        if new_regime == 'EXTREME_CALM_PAUSE':
            logger.warning("Entering EXTREME_CALM_PAUSE regime - closing all positions")
            self._close_all_positions("Regime change to EXTREME_CALM_PAUSE")
        
        # HIGH_VOL: Enable conservative mode
        elif new_regime == 'HIGH_VOL':
            logger.warning("Entering HIGH_VOL regime - enabling conservative mode")
            # HIGH_VOL strategy deferred to Phase 2, but safety limits apply
        
        # Log strategy activation
        strategy_map = {
            'NORMAL_VOL': 'wave_renko',
            'ULTRA_LOW_VOL': 'vwap_reversion',
            'EXTREME_CALM_PAUSE': 'none',
            'HIGH_VOL': 'none'  # Deferred to Phase 2
        }
        self.active_strategy = strategy_map.get(new_regime)
        logger.info(f"Active strategy: {self.active_strategy}")
    
    def process_signal(
        self,
        signal_type: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        premium: float
    ) -> bool:
        """
        Process a trading signal with safety validation
        
        Args:
            signal_type: Type of signal (e.g., 'wave_impulse', 'vwap_reversion')
            direction: 'long' or 'short'
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            premium: Options premium cost
            
        Returns:
            True if signal was executed
        """
        logger.info(f"Processing {signal_type} {direction} signal @ ${entry_price:.2f}")
        
        # 1. Validate trade with SafetyManager
        validation = self.safety_manager.validate_trade(
            strategy=self.active_strategy or 'unknown',
            regime=self.current_regime or 'unknown',
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            premium=premium,
            account_balance=self.account_balance
        )
        
        if not validation.approved:
            logger.warning(f"❌ Signal REJECTED: {validation.reason}")
            return False
        
        # 2. Log warnings if any
        for warning in validation.warnings:
            logger.warning(f"⚠️  {warning}")
        
        # 3. Execute trade (placeholder for actual broker integration)
        logger.info(f"✅ Signal APPROVED - executing {direction} trade...")
        self._execute_trade(signal_type, direction, entry_price, stop_loss, take_profit, premium)
        
        return True
    
    def _execute_trade(
        self,
        signal_type: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        premium: float
    ):
        """Execute trade (placeholder for broker integration)"""
        # Record trade in SafetyManager
        self.safety_manager.record_trade(
            strategy=self.active_strategy or 'unknown',
            regime=self.current_regime or 'unknown',
            direction=direction,
            entry_price=entry_price,
            premium=premium,
            stop_loss=stop_loss,
            take_profit=take_profit,
            signal_type=signal_type
        )
        
        logger.info(f"Trade executed: {direction} @ ${entry_price:.2f}, premium: ${premium:.2f}")
        
        # TODO: Integrate with Alpaca/broker API for actual order execution
        # Example:
        # self.broker.place_options_order(
        #     symbol='QQQ',
        #     direction=direction,
        #     premium=premium,
        #     stop_loss=stop_loss,
        #     take_profit=take_profit
        # )
    
    def close_trade(self, trade_id: int, exit_price: float, premium_received: float):
        """
        Close an existing trade
        
        Args:
            trade_id: ID of trade to close
            exit_price: Exit price
            premium_received: Premium received on exit
        """
        # Calculate P&L
        trade = self.safety_manager.open_positions[trade_id]
        pnl = premium_received - trade['premium']
        
        # Update account balance
        self.account_balance += pnl
        self.safety_manager.update_peak_balance(self.account_balance)
        
        # Record trade close in SafetyManager
        self.safety_manager.record_trade_close(trade_id, pnl)
        
        logger.info(f"Trade closed: P&L ${pnl:.2f}, Balance: ${self.account_balance:,.2f}")
    
    def _close_all_positions(self, reason: str):
        """Close all open positions"""
        logger.warning(f"Closing all positions: {reason}")
        
        # Placeholder: In production, would iterate through positions and close via broker
        open_count = len(self.safety_manager.open_positions)
        if open_count > 0:
            logger.info(f"Closing {open_count} open position(s)...")
            # TODO: Implement actual position closing via broker API
        
        # Clear positions from safety manager
        self.safety_manager.open_positions = []
    
    def periodic_health_check(self) -> bool:
        """
        Run periodic health checks during trading
        
        Returns:
            True if system is healthy
        """
        now = datetime.now(pytz.timezone('America/New_York'))
        
        # Run health check every 60 seconds
        if self.last_health_check and (now - self.last_health_check).total_seconds() < 60:
            return True
        
        healthy, issues = self.safety_manager.check_health()
        self.last_health_check = now
        
        if not healthy:
            logger.error(f"Health check failed: {', '.join(issues)}")
            # Trigger safe mode
            self.safety_manager.config['emergency']['safe_mode'] = True
            logger.warning("Safe mode activated - closing new positions disabled")
        
        return healthy
    
    def handle_error(self, error_type: str, message: str):
        """
        Record system error for circuit breaker monitoring
        
        Args:
            error_type: Type of error (e.g., 'API_ERROR', 'DATA_ERROR')
            message: Error message
        """
        logger.error(f"{error_type}: {message}")
        self.safety_manager.record_error(error_type, message)
    
    def get_status(self) -> Dict:
        """Get current system status"""
        status = {
            'timestamp': datetime.now(pytz.timezone('America/New_York')).isoformat(),
            'account_balance': self.account_balance,
            'current_regime': self.current_regime,
            'active_strategy': self.active_strategy,
            'safety_status': self.safety_manager.get_status()
        }
        return status
    
    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Initiating graceful shutdown...")
        
        # Close all positions
        self._close_all_positions("System shutdown")
        
        # Log final status
        status = self.get_status()
        logger.info(f"Final status: {status}")
        logger.info("Shutdown complete")


def main():
    """Example trading loop"""
    engine = LiveTradingEngine(initial_balance=50000.0)
    
    # Pre-market checks
    if not engine.pre_market_check():
        logger.error("Pre-market checks failed - aborting")
        return
    
    logger.info("Starting live trading loop...")
    
    try:
        while True:
            # 1. Periodic health check
            if not engine.periodic_health_check():
                logger.error("Health check failed - entering safe mode")
                time.sleep(60)
                continue
            
            # 2. Update market data (placeholder)
            # In production, fetch real-time data from Polygon/Alpaca
            # daily_data = fetch_daily_data()
            # intraday_data = fetch_intraday_data()
            # engine.update_market_data(daily_data, intraday_data)
            
            # 3. Generate signals based on regime (placeholder)
            # signals = generate_regime_signals(engine.current_regime)
            # for signal in signals:
            #     engine.process_signal(
            #         signal_type=signal.type,
            #         direction=signal.direction,
            #         entry_price=signal.entry,
            #         stop_loss=signal.stop,
            #         take_profit=signal.target,
            #         premium=signal.premium
            #     )
            
            # 4. Monitor open positions (placeholder)
            # check_exits()
            
            # 5. Sleep before next iteration
            time.sleep(1)  # In production, would be event-driven
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        engine.handle_error('SYSTEM_ERROR', str(e))
    finally:
        engine.shutdown()


if __name__ == '__main__':
    main()
