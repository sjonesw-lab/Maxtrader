# Runtime Safety Layer - Operational Guide

## Overview

The Runtime Safety Layer is a production-grade safety system designed to protect capital and prevent catastrophic losses during live trading. It provides multi-layered protection through pre-trade validation, real-time monitoring, circuit breakers, and health checks.

**Last Updated:** November 17, 2025  
**Status:** ✅ Complete (29/29 tests passing)

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Configuration](#configuration)
3. [Safety Features](#safety-features)
4. [Integration Guide](#integration-guide)
5. [Operational Procedures](#operational-procedures)
6. [Troubleshooting](#troubleshooting)

---

## System Architecture

### Components

**SafetyManager** (`engine/safety_manager.py`)
- Core safety validation and monitoring system
- Pre-trade validation (12 checks)
- Post-trade monitoring and P&L tracking
- Circuit breakers (3 types)
- Health checks (4 types)
- State management and event logging

**LiveTradingEngine** (`live_trading_main.py`)
- Production trading coordinator
- Integrates SafetyManager with regime detection
- Handles signal processing and execution
- Manages account state and positions
- Provides graceful shutdown and error handling

**Configuration** (`configs/safety_config.yaml`)
- Centralized safety parameters
- Regime-specific overrides
- Emergency controls
- Logging and alert settings

---

## Configuration

### Key Parameters

#### Account Limits
```yaml
account:
  max_daily_loss_pct: 0.02      # 2% max daily loss
  max_daily_loss_absolute: 2000.0  # $2,000 hard cap
  max_weekly_loss_pct: 0.05     # 5% max weekly loss
  max_monthly_loss_pct: 0.10    # 10% max monthly loss
```

#### Position Limits
```yaml
position:
  max_concurrent_positions: 3    # Max 3 positions at once
  max_position_size_pct: 0.01   # 1% of account per trade
  max_premium_per_trade: 500.0  # $500 max options premium
  max_total_exposure_pct: 0.03  # 3% total account exposure
```

#### Circuit Breakers
```yaml
circuit_breakers:
  rapid_loss:
    max_losses: 3                # 3 consecutive losses
    time_window_minutes: 30      # In 30 minutes
    pause_duration_minutes: 60   # Pause for 1 hour
  
  error_rate:
    max_errors: 5                # 5 errors
    time_window_minutes: 10      # In 10 minutes
    pause_duration_minutes: 30   # Pause for 30 minutes
  
  drawdown:
    max_drawdown_pct: 0.03      # 3% drawdown
    pause_duration_minutes: 120  # Pause for 2 hours
```

#### Trade Validation
```yaml
validation:
  min_seconds_between_trades: 60    # Minimum 1 minute between trades
  max_trades_per_day: 10            # Max 10 trades/day globally
  max_trades_per_strategy_per_day: 5  # Max 5 trades/day per strategy
  min_reward_risk_ratio: 1.5        # Minimum 1.5:1 R:R ratio
```

### Regime-Specific Overrides

Different volatility regimes have different risk profiles:

```yaml
regime_overrides:
  NORMAL_VOL:
    max_trades_per_day: 10
    max_concurrent_positions: 3
  
  ULTRA_LOW_VOL:
    max_trades_per_day: 5
    max_concurrent_positions: 2
  
  EXTREME_CALM_PAUSE:
    max_trades_per_day: 0       # No trading
    max_concurrent_positions: 0
  
  HIGH_VOL:
    max_trades_per_day: 3       # Conservative
    max_concurrent_positions: 1
```

---

## Safety Features

### 1. Pre-Trade Validation (12 Checks)

Every trade goes through comprehensive validation before execution:

| Check | Description | Action on Failure |
|-------|-------------|-------------------|
| **Kill Switch** | Manual emergency stop | Block trade |
| **Safe Mode** | Position-close-only mode | Block new entries |
| **Circuit Breaker** | Active pause from rapid loss/errors | Block until timeout |
| **Daily Loss Limit** | Percentage and absolute loss caps | Block trade |
| **Max Positions** | Concurrent position limit | Block trade |
| **Daily Trade Limit** | Global trades per day | Block trade |
| **Strategy Trade Limit** | Per-strategy trades per day | Block trade |
| **Trade Frequency** | Minimum time between trades | Block trade |
| **Position Size %** | Percentage of account | Block trade |
| **Premium Limit** | Maximum options premium | Block trade |
| **Total Exposure** | Combined position exposure | Block trade |
| **Risk-Reward Ratio** | Minimum R:R validation | Warning only |

**Example Pre-Trade Validation:**

```python
validation = safety_manager.validate_trade(
    strategy='wave_renko',
    regime='NORMAL_VOL',
    direction='long',
    entry_price=450.0,
    stop_loss=448.0,
    take_profit=454.0,
    premium=300.0,
    account_balance=50000.0
)

if validation.approved:
    # Execute trade
    execute_trade(...)
else:
    logger.warning(f"Trade rejected: {validation.reason}")
```

### 2. Circuit Breakers (3 Types)

Circuit breakers automatically pause trading when risk conditions are detected:

#### Rapid Loss Circuit Breaker
- **Trigger:** 3 losses in 30 minutes
- **Action:** Pause trading for 60 minutes
- **Purpose:** Prevent emotional revenge trading

#### Error Rate Circuit Breaker
- **Trigger:** 5 system errors in 10 minutes
- **Action:** Pause trading for 30 minutes
- **Purpose:** Protect against API/data issues

#### Drawdown Circuit Breaker
- **Trigger:** 3% drawdown from peak balance
- **Action:** Pause trading for 120 minutes
- **Purpose:** Prevent deep losses in adverse conditions

**Circuit Breaker Auto-Reset:**
Circuit breakers automatically reset after the pause duration. The next trade validation will check if the timeout has expired and clear the circuit breaker flag.

### 3. Health Checks (4 Types)

Real-time monitoring of system health:

#### Market Hours Check
- **Validates:** Trading only during 09:30-15:45 ET, Monday-Friday
- **Frequency:** Before each trade
- **Action:** Block trades outside market hours

#### Data Freshness Check
- **Validates:** Data received within last 5 minutes
- **Frequency:** Continuous
- **Action:** Enable safe mode if data stale

#### System Resources Check
- **Validates:** CPU <90%, Memory <80%
- **Frequency:** Every 60 seconds
- **Action:** Enable safe mode if overloaded

#### API Connectivity Check
- **Validates:** Broker API responsive
- **Frequency:** Every 60 seconds
- **Action:** Enable safe mode if unavailable

### 4. Post-Trade Monitoring

Continuous monitoring of open positions:

- **P&L Tracking:** Real-time profit/loss calculation
- **Drawdown Detection:** Monitors distance from peak balance
- **Loss Recording:** Tracks losses for circuit breaker logic
- **Position Lifecycle:** Monitors from entry to exit

---

## Integration Guide

### Basic Integration

```python
from engine.safety_manager import SafetyManager
from live_trading_main import LiveTradingEngine

# Initialize trading engine with safety
engine = LiveTradingEngine(
    safety_config_path='configs/safety_config.yaml',
    initial_balance=50000.0
)

# Pre-market checks
if engine.pre_market_check():
    # Process signals
    engine.process_signal(
        signal_type='wave_impulse',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0
    )
```

### Advanced Integration with Regime Router

```python
# Update market data and regime
vix = calculate_vix_proxy(daily_data)
atr_pct = (atr_value / current_price) * 100

engine.update_market_data(daily_data, vix, atr_pct)

# Regime automatically routes to appropriate strategy
# SafetyManager applies regime-specific limits
```

### Error Handling

```python
try:
    # Execute trade logic
    place_order(...)
except APIError as e:
    # Record error for circuit breaker monitoring
    engine.handle_error('API_ERROR', str(e))
except DataError as e:
    engine.handle_error('DATA_ERROR', str(e))
```

---

## Operational Procedures

### Daily Startup Checklist

1. **Pre-Market Checks** (08:00-09:00 ET)
   ```python
   if not engine.pre_market_check():
       # Review issues
       # Fix problems or skip trading day
       return
   ```

2. **Review Configuration**
   - Check `safety_config.yaml` for any manual changes
   - Verify `kill_switch` is `false`
   - Verify `safe_mode` is `false`
   - Confirm loss limits are appropriate for account size

3. **System Health Baseline**
   ```python
   healthy, issues = engine.safety_manager.check_health()
   if not healthy:
       logger.error(f"Health issues: {issues}")
   ```

4. **Start Trading Loop**
   ```python
   engine.run()  # Starts event-driven trading loop
   ```

### During Trading Hours

**Continuous Monitoring:**
- Monitor SafetyManager event log: `logs/safety_events.log`
- Watch for circuit breaker activations
- Track daily P&L vs limits
- Monitor open positions count
- Check health check status

**Status Checks (Every 30 Minutes):**
```python
status = engine.get_status()
print(f"Regime: {status['current_regime']}")
print(f"Open Positions: {status['safety_status']['open_positions']}")
print(f"Daily P&L: ${status['safety_status']['daily_pnl']:.2f}")
print(f"Trades Today: {status['safety_status']['trades_today']}")
```

### Emergency Procedures

#### Activate Kill Switch

**When to Use:**
- Unexpected market event (flash crash, news)
- System behaving erratically
- Need immediate trading halt

**How to Activate:**
```python
# Option 1: Via code
engine.safety_manager.config['emergency']['kill_switch'] = True

# Option 2: Edit config file
# Set `kill_switch: true` in configs/safety_config.yaml
# Restart system
```

**Effect:**
- All new trades blocked immediately
- Open positions remain (not auto-closed)
- System stays running for monitoring

#### Activate Safe Mode

**When to Use:**
- Data quality concerns
- API connectivity issues
- Want to close positions only

**How to Activate:**
```python
# Via code
engine.safety_manager.config['emergency']['safe_mode'] = True
```

**Effect:**
- New entries blocked
- Position closes allowed
- System continues monitoring

#### Emergency Shutdown

```python
# Graceful shutdown
engine.shutdown()  # Closes all positions and logs final state
```

### End of Day Procedures

1. **Review Daily Performance**
   ```python
   status = engine.get_status()
   daily_pnl = status['safety_status']['daily_pnl']
   trades_executed = status['safety_status']['trades_today']
   ```

2. **Check Circuit Breaker Activity**
   - Review safety_events.log for any triggered breakers
   - Analyze root causes
   - Adjust parameters if needed

3. **Graceful Shutdown**
   ```python
   engine.shutdown()  # Closes all positions cleanly
   ```

4. **Backup Logs**
   - Archive `logs/safety_events.log`
   - Save daily status reports

---

## Troubleshooting

### Common Issues

#### Trade Rejected: "Circuit breaker active"

**Cause:** System detected rapid losses, high error rate, or excessive drawdown

**Solution:**
1. Check circuit breaker type in logs
2. Wait for auto-reset (30-120 minutes)
3. Review root cause
4. Manual reset only if appropriate:
   ```python
   engine.safety_manager.circuit_breaker_active = False
   engine.safety_manager.circuit_breaker_until = None
   ```

#### Trade Rejected: "Daily loss limit exceeded"

**Cause:** Cumulative losses hit 2% of account or $2,000 absolute limit

**Solution:**
1. **DO NOT** override limit
2. Stop trading for the day
3. Review losing trades
4. Check strategy performance
5. Resume next trading day with fresh limits

#### Trade Rejected: "Max concurrent positions reached"

**Cause:** Already holding maximum allowed positions for regime

**Solution:**
1. Wait for existing position to close
2. Review regime-specific limits
3. Consider if position sizing is appropriate

#### Health Check Failed: "Data stale"

**Cause:** No data received in last 5 minutes

**Solution:**
1. Check data provider API status
2. Check network connectivity
3. Restart data feed
4. System auto-enables safe mode for protection

#### High CPU/Memory Usage

**Cause:** System resource limits exceeded

**Solution:**
1. Check for runaway processes
2. Restart system
3. Reduce position monitoring frequency if needed
4. Consider infrastructure upgrade

---

## Testing

### Unit Tests

Run comprehensive safety tests:

```bash
python -m pytest tests/test_safety_manager.py -v
```

**Test Coverage:**
- 29 comprehensive tests
- All 12 validation checks
- All 3 circuit breakers
- All 4 health checks
- State management
- Error handling

**Current Status:** ✅ 29/29 passing (100%)

### Integration Testing

```python
# Test pre-trade validation
def test_integration():
    engine = LiveTradingEngine(initial_balance=50000.0)
    
    # Should approve normal trade
    result = engine.process_signal(
        signal_type='wave_impulse',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=300.0
    )
    assert result is True
    
    # Should reject oversized trade
    result = engine.process_signal(
        signal_type='wave_impulse',
        direction='long',
        entry_price=450.0,
        stop_loss=448.0,
        take_profit=454.0,
        premium=600.0  # Exceeds 1% limit
    )
    assert result is False
```

---

## Performance Impact

**Latency Added per Trade:**
- Pre-trade validation: <1ms
- Post-trade recording: <1ms
- Health checks: <50ms (async, non-blocking)

**Total Impact:** Negligible (<52ms per trade)

**Memory Footprint:**
- SafetyManager: ~2MB
- Event log: ~100KB per day

---

## Future Enhancements

**Phase 2 Roadmap:**

1. **External Alerting**
   - Email alerts for circuit breakers
   - SMS alerts for critical events
   - Webhook integration for monitoring dashboards

2. **Advanced Analytics**
   - P&L attribution by strategy/regime
   - Circuit breaker frequency analysis
   - Health check failure patterns

3. **Dynamic Limits**
   - Adjust position size based on account growth
   - VIX-adaptive loss limits
   - Win streak detection (increase size)

4. **Machine Learning Integration**
   - Anomaly detection in trading patterns
   - Predictive circuit breaker triggers
   - Optimal parameter tuning

---

## Support

**Documentation:**
- This guide: `docs/SAFETY_LAYER_GUIDE.md`
- SafetyManager API: `engine/safety_manager.py`
- Configuration schema: `configs/safety_config.yaml`
- Unit tests: `tests/test_safety_manager.py`

**Logging:**
- Safety events: `logs/safety_events.log`
- System logs: `logs/system.log`

**Emergency Contact:**
- See `configs/safety_config.yaml` → `emergency.emergency_contact`

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-17 | 1.0 | Initial release - Complete Runtime Safety Layer |

---

**End of Runtime Safety Layer Guide**
