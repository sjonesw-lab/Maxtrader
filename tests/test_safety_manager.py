"""
Unit tests for SafetyManager
Tests all safety features: validation, circuit breakers, health checks, monitoring
"""
import pytest
import os
import yaml
from datetime import datetime, timedelta
from engine.safety_manager import SafetyManager, TradeValidationResult
import pytz


@pytest.fixture
def temp_safety_config(tmp_path):
    """Create temporary safety config for testing"""
    config = {
        'account': {
            'max_account_size': 100000.0,
            'max_daily_loss_pct': 0.02,
            'max_daily_loss_absolute': 2000.0,
            'max_weekly_loss_pct': 0.05,
            'max_monthly_loss_pct': 0.10
        },
        'position': {
            'max_concurrent_positions': 3,
            'max_position_size_pct': 0.01,
            'max_position_size_absolute': 1000.0,
            'max_premium_per_trade': 500.0,
            'max_total_exposure_pct': 0.03
        },
        'circuit_breakers': {
            'rapid_loss': {
                'enabled': True,
                'max_losses': 3,
                'time_window_minutes': 30,
                'pause_duration_minutes': 60
            },
            'error_rate': {
                'enabled': True,
                'max_errors': 5,
                'time_window_minutes': 10,
                'pause_duration_minutes': 30
            },
            'drawdown': {
                'enabled': True,
                'max_drawdown_pct': 0.03,
                'pause_duration_minutes': 120
            }
        },
        'validation': {
            'min_seconds_between_trades': 60,
            'max_trades_per_day': 10,
            'max_trades_per_strategy_per_day': 5,
            'manual_approval_threshold': 500.0,
            'min_reward_risk_ratio': 1.5
        },
        'health_checks': {
            'api': {'enabled': True, 'check_interval_seconds': 60, 'max_consecutive_failures': 3},
            'data_freshness': {'enabled': True, 'max_staleness_seconds': 300},
            'market_hours': {'enabled': True, 'start_time': '09:30', 'end_time': '15:45'},
            'system': {'enabled': True, 'max_memory_usage_pct': 80, 'max_cpu_usage_pct': 90}
        },
        'emergency': {
            'kill_switch': False,
            'safe_mode': False,
            'auto_shutdown_on_critical': True,
            'emergency_contact': 'test@example.com'
        },
        'logging': {
            'level': 'INFO',
            'log_to_file': False,
            'alert_on': ['circuit_breaker_triggered', 'daily_loss_limit_exceeded']
        },
        'regime_overrides': {
            'NORMAL_VOL': {'max_trades_per_day': 10, 'max_concurrent_positions': 3},
            'ULTRA_LOW_VOL': {'max_trades_per_day': 5, 'max_concurrent_positions': 2},
            'EXTREME_CALM_PAUSE': {'max_trades_per_day': 0, 'max_concurrent_positions': 0}
        }
    }
    
    config_path = tmp_path / "safety_config.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    
    return str(config_path)


@pytest.fixture
def safety_manager(temp_safety_config):
    """Create SafetyManager instance for testing"""
    return SafetyManager(temp_safety_config)


# =============================================================================
# TRADE VALIDATION TESTS
# =============================================================================

def test_validate_trade_basic_approval(safety_manager):
    """Test that a normal trade is approved"""
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is True
    assert result.reason is None


def test_validate_trade_kill_switch(safety_manager):
    """Test that kill switch blocks all trades"""
    safety_manager.config['emergency']['kill_switch'] = True
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'kill switch' in result.reason.lower()


def test_validate_trade_safe_mode(safety_manager):
    """Test that safe mode blocks new trades"""
    safety_manager.config['emergency']['safe_mode'] = True
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'safe mode' in result.reason.lower()


def test_validate_trade_daily_loss_limit_pct(safety_manager):
    """Test that daily loss percentage limit blocks trades"""
    safety_manager.daily_pnl = -1100.0  # -2.2% on $50k account
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'daily loss' in result.reason.lower()


def test_validate_trade_daily_loss_limit_absolute(safety_manager):
    """Test that daily loss absolute limit blocks trades"""
    safety_manager.daily_pnl = -2100.0  # Exceeds $2000 limit
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=200000.0  # Large account, but absolute limit still applies
    )
    
    assert result.approved is False
    assert 'daily loss' in result.reason.lower()


def test_validate_trade_max_positions(safety_manager):
    """Test that max concurrent positions limit works"""
    # Add 3 open positions
    for i in range(3):
        safety_manager.open_positions.append({
            'id': i,
            'premium': 300.0
        })
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'max concurrent positions' in result.reason.lower()


def test_validate_trade_max_daily_trades(safety_manager):
    """Test that max trades per day limit works"""
    # Add 10 trades today
    for i in range(10):
        safety_manager.trades_today.append({
            'id': i,
            'timestamp': datetime.now(pytz.timezone('America/New_York'))
        })
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'max trades per day' in result.reason.lower()


def test_validate_trade_max_strategy_trades(safety_manager):
    """Test that max trades per strategy limit works"""
    # Add 5 trades for this strategy
    safety_manager.trades_by_strategy['wave_renko'] = [
        {'id': i, 'timestamp': datetime.now(pytz.timezone('America/New_York'))}
        for i in range(5)
    ]
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'wave_renko' in result.reason.lower()


def test_validate_trade_min_time_between_trades(safety_manager):
    """Test that minimum time between trades is enforced"""
    # Add a recent trade (30 seconds ago)
    safety_manager.trades_today.append({
        'id': 0,
        'timestamp': datetime.now(pytz.timezone('America/New_York')) - timedelta(seconds=30)
    })
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'minimum time' in result.reason.lower()


def test_validate_trade_position_size_pct(safety_manager):
    """Test that position size percentage limit works"""
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=600.0,  # 1.2% of $50k account (exceeds 1% limit)
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'position size' in result.reason.lower()


def test_validate_trade_premium_limit(safety_manager):
    """Test that max premium per trade limit works"""
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=600.0,  # Exceeds $500 limit
        account_balance=100000.0
    )
    
    assert result.approved is False
    assert 'premium' in result.reason.lower()


def test_validate_trade_total_exposure(safety_manager):
    """Test that total exposure limit works"""
    # Add 2 open positions with $750 premium each (total $1500 current exposure)
    for i in range(2):
        safety_manager.open_positions.append({
            'id': i,
            'premium': 750.0
        })
    
    # Try to add another $100 position (total would be $1600 > 3% of $50k = $1500)
    # Premium is small enough to pass position size check (0.2% < 1%)
    # But total exposure check should fail ($1600 > $1500)
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=100.0,  # Small enough to pass position size, but exceeds total exposure
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'exposure' in result.reason.lower()


def test_validate_trade_low_rr_ratio_warning(safety_manager):
    """Test that low R:R ratio generates warning but doesn't block trade"""
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=451.0,  # Only 1:2 R:R (below 1.5 minimum)
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is True  # Still approved
    assert len(result.warnings) > 0
    assert any('r:r' in w.lower() for w in result.warnings)


def test_validate_trade_regime_override(safety_manager):
    """Test that regime-specific limits override defaults"""
    # ULTRA_LOW_VOL has max 2 positions (not 3)
    safety_manager.open_positions = [{'id': 0}, {'id': 1}]
    
    result = safety_manager.validate_trade(
        strategy='vwap_reversion',
        regime='ULTRA_LOW_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert '2' in result.reason  # Max 2 positions for ULTRA_LOW_VOL


# =============================================================================
# CIRCUIT BREAKER TESTS
# =============================================================================

def test_circuit_breaker_rapid_loss(safety_manager):
    """Test that rapid loss circuit breaker triggers"""
    # Record 3 losses within time window
    now = datetime.now(pytz.timezone('America/New_York'))
    for i in range(3):
        safety_manager.recent_losses.append({
            'timestamp': now - timedelta(minutes=i),
            'pnl': -100.0
        })
    
    # Check circuit breaker
    safety_manager._check_circuit_breakers()
    
    assert safety_manager.circuit_breaker_active is True
    assert safety_manager.circuit_breaker_until is not None


def test_circuit_breaker_error_rate(safety_manager):
    """Test that error rate circuit breaker triggers"""
    # Record 5 errors within time window
    now = datetime.now(pytz.timezone('America/New_York'))
    for i in range(5):
        safety_manager.recent_errors.append({
            'timestamp': now - timedelta(minutes=i),
            'type': 'API_ERROR',
            'message': 'Connection failed'
        })
    
    # Check circuit breaker
    safety_manager._check_circuit_breakers()
    
    assert safety_manager.circuit_breaker_active is True


def test_circuit_breaker_drawdown(safety_manager):
    """Test that drawdown circuit breaker triggers"""
    safety_manager.peak_balance = 50000.0
    safety_manager.daily_pnl = -1600.0  # 3.2% drawdown (exceeds 3% limit)
    
    safety_manager._check_circuit_breakers()
    
    assert safety_manager.circuit_breaker_active is True


def test_circuit_breaker_blocks_trades(safety_manager):
    """Test that active circuit breaker blocks trades"""
    # Activate circuit breaker
    safety_manager.circuit_breaker_active = True
    safety_manager.circuit_breaker_until = datetime.now(pytz.timezone('America/New_York')) + timedelta(hours=1)
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    assert result.approved is False
    assert 'circuit breaker' in result.reason.lower()


def test_circuit_breaker_auto_reset(safety_manager):
    """Test that circuit breaker auto-resets after timeout"""
    # Set expired circuit breaker
    safety_manager.circuit_breaker_active = True
    safety_manager.circuit_breaker_until = datetime.now(pytz.timezone('America/New_York')) - timedelta(minutes=1)
    
    result = safety_manager.validate_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0,
        account_balance=50000.0
    )
    
    # Circuit breaker should have auto-reset
    assert safety_manager.circuit_breaker_active is False
    assert result.approved is True


# =============================================================================
# HEALTH CHECK TESTS
# =============================================================================

def test_health_check_data_staleness(safety_manager):
    """Test that stale data is detected"""
    # Set stale data timestamp (10 minutes ago)
    safety_manager.last_data_update = datetime.now(pytz.timezone('America/New_York')) - timedelta(minutes=10)
    
    healthy, issues = safety_manager.check_health()
    
    assert healthy is False
    assert any('stale' in issue.lower() for issue in issues)


def test_health_check_fresh_data(safety_manager):
    """Test that fresh data passes health check"""
    safety_manager.last_data_update = datetime.now(pytz.timezone('America/New_York'))
    
    healthy, issues = safety_manager.check_health()
    
    # May fail on market hours check depending on when test runs
    # But should not fail on data staleness
    assert not any('stale' in issue.lower() for issue in issues)


# =============================================================================
# STATE MANAGEMENT TESTS
# =============================================================================

def test_record_trade(safety_manager):
    """Test that trades are recorded correctly"""
    safety_manager.record_trade(
        strategy='wave_renko',
        regime='NORMAL_VOL',
        direction='long',
        entry_price=450.0,
        premium=300.0
    )
    
    assert len(safety_manager.trades_today) == 1
    assert len(safety_manager.open_positions) == 1
    assert 'wave_renko' in safety_manager.trades_by_strategy
    assert len(safety_manager.trades_by_strategy['wave_renko']) == 1


def test_record_trade_close_profit(safety_manager):
    """Test that profitable trade close is recorded"""
    safety_manager.open_positions.append({'id': 0})
    
    safety_manager.record_trade_close(trade_id=0, pnl=150.0)
    
    assert safety_manager.daily_pnl == 150.0
    assert len(safety_manager.open_positions) == 0
    assert len(safety_manager.recent_losses) == 0


def test_record_trade_close_loss(safety_manager):
    """Test that losing trade is tracked for circuit breaker"""
    safety_manager.open_positions.append({'id': 0})
    
    safety_manager.record_trade_close(trade_id=0, pnl=-100.0)
    
    assert safety_manager.daily_pnl == -100.0
    assert len(safety_manager.recent_losses) == 1


def test_reset_daily_state(safety_manager):
    """Test that daily state reset works"""
    # Add some state
    safety_manager.trades_today = [{'id': 0}]
    safety_manager.trades_by_strategy = {'wave_renko': [{'id': 0}]}
    safety_manager.daily_pnl = -500.0
    
    # Reset
    safety_manager.reset_daily_state()
    
    assert len(safety_manager.trades_today) == 0
    assert len(safety_manager.trades_by_strategy) == 0
    assert safety_manager.daily_pnl == 0.0


def test_update_peak_balance(safety_manager):
    """Test that peak balance tracking works"""
    safety_manager.update_peak_balance(50000.0)
    assert safety_manager.peak_balance == 50000.0
    
    safety_manager.update_peak_balance(49000.0)  # Lower, shouldn't update
    assert safety_manager.peak_balance == 50000.0
    
    safety_manager.update_peak_balance(51000.0)  # Higher, should update
    assert safety_manager.peak_balance == 51000.0


def test_get_status(safety_manager):
    """Test that status dict is correctly generated"""
    safety_manager.trades_today = [{'id': 0}]
    safety_manager.open_positions = [{'id': 0}, {'id': 1}]
    safety_manager.daily_pnl = 200.0
    
    status = safety_manager.get_status()
    
    assert status['trades_today'] == 1
    assert status['open_positions'] == 2
    assert status['daily_pnl'] == 200.0
    assert status['circuit_breaker_active'] is False
    assert status['kill_switch'] is False
    assert status['safe_mode'] is False


# =============================================================================
# ERROR RECORDING TESTS
# =============================================================================

def test_record_error(safety_manager):
    """Test that errors are recorded"""
    safety_manager.record_error('API_ERROR', 'Connection timeout')
    
    assert len(safety_manager.recent_errors) == 1
    assert safety_manager.recent_errors[0]['type'] == 'API_ERROR'


def test_record_multiple_errors_triggers_circuit_breaker(safety_manager):
    """Test that multiple errors trigger circuit breaker"""
    # Record 5 errors rapidly
    for i in range(5):
        safety_manager.record_error('API_ERROR', f'Error {i}')
    
    assert safety_manager.circuit_breaker_active is True
