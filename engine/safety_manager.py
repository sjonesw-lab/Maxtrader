"""
Runtime Safety Manager
Production-grade safety system with real-time validation, circuit breakers, and health checks
"""
import yaml
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import psutil
import pytz


@dataclass
class SafetyEvent:
    """Records a safety-related event"""
    timestamp: datetime
    event_type: str  # 'trade_blocked', 'circuit_breaker', 'health_check_failure', etc.
    severity: str  # 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    message: str
    details: Dict = field(default_factory=dict)


@dataclass
class TradeValidationResult:
    """Result of trade validation"""
    approved: bool
    reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


class SafetyManager:
    """
    Central safety management system for production trading
    
    Responsibilities:
    - Pre-trade validation (position limits, loss limits)
    - Circuit breakers (rapid loss, error rate, drawdown)
    - Health checks (API, data, market hours)
    - Real-time monitoring and alerting
    """
    
    def __init__(self, config_path: str = 'configs/safety_config.yaml'):
        """Initialize safety manager with configuration"""
        self.config = self._load_config(config_path)
        self.logger = self._setup_logging()
        
        # State tracking
        self.trades_today: List[Dict] = []
        self.trades_by_strategy: Dict[str, List[Dict]] = {}
        self.open_positions: List[Dict] = []
        self.daily_pnl: float = 0.0
        self.weekly_pnl: float = 0.0
        self.monthly_pnl: float = 0.0
        self.peak_balance: float = 0.0
        
        # Circuit breaker state
        self.recent_losses: deque = deque(maxlen=10)
        self.recent_errors: deque = deque(maxlen=20)
        self.circuit_breaker_active: bool = False
        self.circuit_breaker_until: Optional[datetime] = None
        
        # Health check state
        self.last_api_check: Optional[datetime] = None
        self.api_failures: int = 0
        self.last_data_update: Optional[datetime] = None
        
        # Safety events log
        self.safety_events: deque = deque(maxlen=1000)
        
        self.logger.info("SafetyManager initialized")
        self._log_event('SYSTEM', 'INFO', 'Safety Manager started')
    
    def _load_config(self, config_path: str) -> Dict:
        """Load safety configuration from YAML"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging for safety events"""
        logger = logging.getLogger('SafetyManager')
        logger.setLevel(getattr(logging, self.config['logging']['level']))
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
        )
        logger.addHandler(console_handler)
        
        # File handler if enabled
        if self.config['logging'].get('log_to_file', False):
            file_handler = logging.FileHandler(
                self.config['logging']['log_file_path']
            )
            file_handler.setFormatter(
                logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
            )
            logger.addHandler(file_handler)
        
        return logger
    
    def _log_event(self, event_type: str, severity: str, message: str, details: Optional[Dict] = None):
        """Log a safety event"""
        event = SafetyEvent(
            timestamp=datetime.now(pytz.timezone('America/New_York')),
            event_type=event_type,
            severity=severity,
            message=message,
            details=details if details is not None else {}
        )
        self.safety_events.append(event)
        
        # Log to logger
        log_func = getattr(self.logger, severity.lower())
        log_func(f"[{event_type}] {message}")
        
        # Alert on critical events
        if event_type in self.config['logging'].get('alert_on', []):
            self._trigger_alert(event)
    
    def _trigger_alert(self, event: SafetyEvent):
        """Trigger alert for critical event (placeholder for integration)"""
        self.logger.critical(f"ALERT: {event.event_type} - {event.message}")
        # TODO: Integrate with actual alerting system (email, SMS, etc.)
    
    # =========================================================================
    # PRE-TRADE VALIDATION
    # =========================================================================
    
    def validate_trade(
        self,
        strategy: str,
        regime: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        premium: float,
        account_balance: float
    ) -> TradeValidationResult:
        """
        Comprehensive pre-trade validation
        
        Returns:
            TradeValidationResult with approval status and reasons
        """
        warnings = []
        
        # 1. Check kill switch
        if self.config['emergency']['kill_switch']:
            return TradeValidationResult(
                approved=False,
                reason="Kill switch activated - all trading suspended"
            )
        
        # 2. Check safe mode
        if self.config['emergency']['safe_mode']:
            return TradeValidationResult(
                approved=False,
                reason="Safe mode active - only position closes allowed"
            )
        
        # 3. Check circuit breakers
        if self.circuit_breaker_active:
            if self.circuit_breaker_until and datetime.now(pytz.timezone('America/New_York')) < self.circuit_breaker_until:
                return TradeValidationResult(
                    approved=False,
                    reason=f"Circuit breaker active until {self.circuit_breaker_until}"
                )
            else:
                # Reset circuit breaker
                self.circuit_breaker_active = False
                self.circuit_breaker_until = None
                self._log_event('CIRCUIT_BREAKER', 'INFO', 'Circuit breaker reset')
        
        # 4. Check daily loss limits
        if not self._check_daily_loss_limit(account_balance):
            return TradeValidationResult(
                approved=False,
                reason=f"Daily loss limit exceeded ({self.daily_pnl:.2f})"
            )
        
        # 5. Check position limits
        max_positions = self._get_regime_config(regime, 'max_concurrent_positions')
        if len(self.open_positions) >= max_positions:
            return TradeValidationResult(
                approved=False,
                reason=f"Max concurrent positions reached ({len(self.open_positions)}/{max_positions})"
            )
        
        # 6. Check daily trade limits
        max_trades = self._get_regime_config(regime, 'max_trades_per_day')
        if len(self.trades_today) >= max_trades:
            return TradeValidationResult(
                approved=False,
                reason=f"Max trades per day reached ({len(self.trades_today)}/{max_trades})"
            )
        
        # 7. Check strategy-specific limits
        strategy_trades_today = self.trades_by_strategy.get(strategy, [])
        max_strategy_trades = self.config['validation']['max_trades_per_strategy_per_day']
        if len(strategy_trades_today) >= max_strategy_trades:
            return TradeValidationResult(
                approved=False,
                reason=f"Max trades for {strategy} reached ({len(strategy_trades_today)}/{max_strategy_trades})"
            )
        
        # 8. Check minimum time between trades
        if self.trades_today:
            last_trade_time = self.trades_today[-1]['timestamp']
            min_interval = timedelta(seconds=self.config['validation']['min_seconds_between_trades'])
            if datetime.now(pytz.timezone('America/New_York')) - last_trade_time < min_interval:
                return TradeValidationResult(
                    approved=False,
                    reason="Minimum time between trades not elapsed"
                )
        
        # 9. Check position size limits
        position_size_pct = (premium / account_balance) * 100
        max_size_pct = self.config['position']['max_position_size_pct'] * 100
        if position_size_pct > max_size_pct:
            return TradeValidationResult(
                approved=False,
                reason=f"Position size ({position_size_pct:.2f}%) exceeds limit ({max_size_pct:.2f}%)"
            )
        
        if premium > self.config['position']['max_premium_per_trade']:
            return TradeValidationResult(
                approved=False,
                reason=f"Premium (${premium:.2f}) exceeds limit (${self.config['position']['max_premium_per_trade']:.2f})"
            )
        
        # 10. Check total exposure
        current_exposure = sum(pos['premium'] for pos in self.open_positions)
        total_exposure = current_exposure + premium
        max_exposure = account_balance * self.config['position']['max_total_exposure_pct']
        if total_exposure > max_exposure:
            return TradeValidationResult(
                approved=False,
                reason=f"Total exposure (${total_exposure:.2f}) would exceed limit (${max_exposure:.2f})"
            )
        
        # 11. Check risk-reward ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr_ratio = reward / risk if risk > 0 else 0
        min_rr = self.config['validation']['min_reward_risk_ratio']
        if rr_ratio < min_rr:
            warnings.append(f"R:R ratio ({rr_ratio:.2f}) below recommended ({min_rr})")
        
        # 12. Check if manual approval needed
        if premium > self.config['validation']['manual_approval_threshold']:
            warnings.append(f"Trade size (${premium:.2f}) exceeds auto-approval threshold")
        
        # All checks passed
        return TradeValidationResult(approved=True, warnings=warnings)
    
    def _check_daily_loss_limit(self, account_balance: float) -> bool:
        """Check if daily loss limit has been exceeded"""
        max_loss_pct = self.config['account']['max_daily_loss_pct']
        max_loss_abs = self.config['account']['max_daily_loss_absolute']
        
        if self.daily_pnl < 0:
            loss_pct = abs(self.daily_pnl) / account_balance
            if loss_pct >= max_loss_pct:
                self._log_event(
                    'DAILY_LOSS_LIMIT',
                    'CRITICAL',
                    f"Daily loss limit exceeded: {loss_pct*100:.2f}% (limit: {max_loss_pct*100:.2f}%)"
                )
                return False
            
            if abs(self.daily_pnl) >= max_loss_abs:
                self._log_event(
                    'DAILY_LOSS_LIMIT',
                    'CRITICAL',
                    f"Daily loss limit exceeded: ${abs(self.daily_pnl):.2f} (limit: ${max_loss_abs:.2f})"
                )
                return False
        
        return True
    
    def _get_regime_config(self, regime: str, key: str):
        """Get regime-specific config value with fallback to default"""
        regime_config = self.config.get('regime_overrides', {}).get(regime, {})
        if key in regime_config:
            return regime_config[key]
        
        # Try position config first, then validation config
        if key in self.config.get('position', {}):
            return self.config['position'][key]
        elif key in self.config.get('validation', {}):
            return self.config['validation'][key]
        else:
            raise KeyError(f"Config key '{key}' not found in position or validation sections")
    
    # =========================================================================
    # POST-TRADE MONITORING
    # =========================================================================
    
    def record_trade(
        self,
        strategy: str,
        regime: str,
        direction: str,
        entry_price: float,
        premium: float,
        **kwargs
    ):
        """Record a new trade for monitoring"""
        trade = {
            'timestamp': datetime.now(pytz.timezone('America/New_York')),
            'strategy': strategy,
            'regime': regime,
            'direction': direction,
            'entry_price': entry_price,
            'premium': premium,
            **kwargs
        }
        
        self.trades_today.append(trade)
        
        if strategy not in self.trades_by_strategy:
            self.trades_by_strategy[strategy] = []
        self.trades_by_strategy[strategy].append(trade)
        
        self.open_positions.append(trade)
        
        self._log_event(
            'TRADE_OPENED',
            'INFO',
            f"{strategy} {direction} trade opened: ${premium:.2f} premium",
            details=trade
        )
    
    def record_trade_close(self, trade_id: int, pnl: float):
        """Record trade close and update P&L tracking"""
        # Update P&L
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.monthly_pnl += pnl
        
        # Remove from open positions
        if trade_id < len(self.open_positions):
            self.open_positions.pop(trade_id)
        
        # Track losses for circuit breaker
        if pnl < 0:
            self.recent_losses.append({
                'timestamp': datetime.now(pytz.timezone('America/New_York')),
                'pnl': pnl
            })
            self._check_circuit_breakers()
        
        self._log_event(
            'TRADE_CLOSED',
            'INFO',
            f"Trade closed: P&L ${pnl:.2f} (Daily: ${self.daily_pnl:.2f})",
            details={'pnl': pnl, 'daily_pnl': self.daily_pnl}
        )
    
    def record_error(self, error_type: str, message: str):
        """Record system error for circuit breaker monitoring"""
        self.recent_errors.append({
            'timestamp': datetime.now(pytz.timezone('America/New_York')),
            'type': error_type,
            'message': message
        })
        
        self._log_event('ERROR', 'ERROR', f"{error_type}: {message}")
        self._check_circuit_breakers()
    
    # =========================================================================
    # CIRCUIT BREAKERS
    # =========================================================================
    
    def _check_circuit_breakers(self):
        """Check if any circuit breakers should be triggered"""
        now = datetime.now(pytz.timezone('America/New_York'))
        
        # 1. Rapid loss circuit breaker
        if self.config['circuit_breakers']['rapid_loss']['enabled']:
            time_window = timedelta(
                minutes=self.config['circuit_breakers']['rapid_loss']['time_window_minutes']
            )
            recent_window = [
                loss for loss in self.recent_losses
                if now - loss['timestamp'] < time_window
            ]
            
            max_losses = self.config['circuit_breakers']['rapid_loss']['max_losses']
            if len(recent_window) >= max_losses:
                self._trigger_circuit_breaker(
                    'RAPID_LOSS',
                    f"{len(recent_window)} losses in {time_window.total_seconds()/60:.0f} minutes",
                    self.config['circuit_breakers']['rapid_loss']['pause_duration_minutes']
                )
                return
        
        # 2. Error rate circuit breaker
        if self.config['circuit_breakers']['error_rate']['enabled']:
            time_window = timedelta(
                minutes=self.config['circuit_breakers']['error_rate']['time_window_minutes']
            )
            recent_window = [
                error for error in self.recent_errors
                if now - error['timestamp'] < time_window
            ]
            
            max_errors = self.config['circuit_breakers']['error_rate']['max_errors']
            if len(recent_window) >= max_errors:
                self._trigger_circuit_breaker(
                    'ERROR_RATE',
                    f"{len(recent_window)} errors in {time_window.total_seconds()/60:.0f} minutes",
                    self.config['circuit_breakers']['error_rate']['pause_duration_minutes']
                )
                return
        
        # 3. Drawdown circuit breaker
        if self.config['circuit_breakers']['drawdown']['enabled']:
            if self.peak_balance > 0:
                current_drawdown = (self.peak_balance - (self.peak_balance + self.daily_pnl)) / self.peak_balance
                max_drawdown = self.config['circuit_breakers']['drawdown']['max_drawdown_pct']
                
                if current_drawdown >= max_drawdown:
                    self._trigger_circuit_breaker(
                        'DRAWDOWN',
                        f"Drawdown {current_drawdown*100:.2f}% exceeds {max_drawdown*100:.2f}%",
                        self.config['circuit_breakers']['drawdown']['pause_duration_minutes']
                    )
                    return
    
    def _trigger_circuit_breaker(self, breaker_type: str, reason: str, pause_minutes: int):
        """Activate circuit breaker and pause trading"""
        self.circuit_breaker_active = True
        self.circuit_breaker_until = datetime.now(pytz.timezone('America/New_York')) + timedelta(minutes=pause_minutes)
        
        self._log_event(
            'circuit_breaker_triggered',
            'CRITICAL',
            f"{breaker_type} circuit breaker triggered: {reason}. Trading paused until {self.circuit_breaker_until}",
            details={'breaker_type': breaker_type, 'pause_until': str(self.circuit_breaker_until)}
        )
    
    # =========================================================================
    # HEALTH CHECKS
    # =========================================================================
    
    def check_health(self) -> Tuple[bool, List[str]]:
        """
        Perform all health checks
        
        Returns:
            (healthy, issues) tuple
        """
        issues = []
        
        # 1. Market hours check
        if self.config['health_checks']['market_hours']['enabled']:
            if not self._is_market_hours():
                issues.append("Outside market hours")
        
        # 2. Data freshness check
        if self.config['health_checks']['data_freshness']['enabled']:
            if self.last_data_update:
                staleness = (datetime.now(pytz.timezone('America/New_York')) - self.last_data_update).total_seconds()
                max_staleness = self.config['health_checks']['data_freshness']['max_staleness_seconds']
                if staleness > max_staleness:
                    issues.append(f"Data stale: {staleness:.0f}s (max: {max_staleness}s)")
        
        # 3. System resources check
        if self.config['health_checks']['system']['enabled']:
            cpu_usage = psutil.cpu_percent(interval=1)
            memory_usage = psutil.virtual_memory().percent
            
            if cpu_usage > self.config['health_checks']['system']['max_cpu_usage_pct']:
                issues.append(f"High CPU usage: {cpu_usage:.1f}%")
            
            if memory_usage > self.config['health_checks']['system']['max_memory_usage_pct']:
                issues.append(f"High memory usage: {memory_usage:.1f}%")
        
        healthy = len(issues) == 0
        
        if not healthy:
            self._log_event('health_check_failure', 'WARNING', f"Health check failed: {', '.join(issues)}")
        
        return healthy, issues
    
    def _is_market_hours(self) -> bool:
        """Check if current time is within market hours"""
        now = datetime.now(pytz.timezone('America/New_York'))
        
        # Check if weekend
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        
        # Check time window
        start_time = datetime.strptime(
            self.config['health_checks']['market_hours']['start_time'], '%H:%M'
        ).time()
        end_time = datetime.strptime(
            self.config['health_checks']['market_hours']['end_time'], '%H:%M'
        ).time()
        
        return start_time <= now.time() <= end_time
    
    def update_data_timestamp(self):
        """Update the last data update timestamp"""
        self.last_data_update = datetime.now(pytz.timezone('America/New_York'))
    
    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================
    
    def reset_daily_state(self):
        """Reset daily state (call at start of new trading day)"""
        self.trades_today = []
        self.trades_by_strategy = {}
        self.daily_pnl = 0.0
        self._log_event('SYSTEM', 'INFO', 'Daily state reset')
    
    def update_peak_balance(self, current_balance: float):
        """Update peak balance for drawdown calculation"""
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
    
    def get_status(self) -> Dict:
        """Get current safety manager status"""
        return {
            'circuit_breaker_active': self.circuit_breaker_active,
            'circuit_breaker_until': str(self.circuit_breaker_until) if self.circuit_breaker_until else None,
            'open_positions': len(self.open_positions),
            'trades_today': len(self.trades_today),
            'daily_pnl': self.daily_pnl,
            'weekly_pnl': self.weekly_pnl,
            'monthly_pnl': self.monthly_pnl,
            'recent_losses': len(self.recent_losses),
            'recent_errors': len(self.recent_errors),
            'kill_switch': self.config['emergency']['kill_switch'],
            'safe_mode': self.config['emergency']['safe_mode']
        }
