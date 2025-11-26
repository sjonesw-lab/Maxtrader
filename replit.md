# MaxTrader Liquidity Options Engine

## Overview

MaxTrader is an intraday NASDAQ trading research engine that uses a wave-based Renko framework and multi-timeframe confluence analysis to generate quality-driven trading signals. It identifies wave impulses and retracement patterns, integrating daily and 4-hour market context. All trades utilize options structures for defined risk. The system features a multi-regime architecture with robust runtime safety layers.

**CRITICAL CORRECTION (Nov 26, 2025):** After rigorous backtesting, the actual validated performance is **49% win rate** with **20% max drawdown** over 22 months (556 trades with position overlap prevention). Previous claims of 80.5% win rate and 3% drawdown were incorrect due to calculation errors. System is now configured with realistic performance expectations.

## User Preferences

Preferred communication style: Simple, everyday language. Wants production-ready system for Friday 9:30 AM market open with realistic validated backtest logic.

## System Architecture

### Core Design Principles

The system employs a **Modular Pipeline Architecture** for data processing, signal generation, and execution. **Options-First Risk Management** defines all risk through options payoff structures. **Session-Based Liquidity Tracking** identifies liquidity zones using global sessions, primarily generating signals during the NY open window.

### Data Layer

The `CSVDataProvider` handles file-based data for backtesting, expecting 1-minute OHLCV data. An abstract `DataProvider` allows for future live data integration.

### Polygon-Based Paper Trading System

The **Automated QQQ-Only Trader** (`engine/auto_trader.py`) conducts realistic paper trading using Polygon.io's real options pricing data. It executes entries at the ask price and exits at the bid price, tracking positions and account balance internally without broker integration. **QQQ-ONLY CONFIGURATION**: Trades QQQ exclusively. **Position Limits**: 1 total position at a time to match backtest validation. **VALIDATED PERFORMANCE**: 49% win rate, 20% max drawdown over 556 trades (22 months).

### ICT Structure Detection

The ICT module is **ENABLED** and acts as the primary signal generator. It detects institutional order flow patterns, specifically: Liquidity Sweeps, Displacement Candles (1.0x ATR threshold), and Market Structure Shifts (MSS). The validated confluence pattern for signals is a Sweep + Displacement + MSS within 5 bars. Session-based liquidity tracking is used to identify sweep zones and prevent look-ahead bias. **PRODUCTION PARAMETERS: 1.0x ATR displacement**

### Validated Backtest Results (22 Months: Jan 2024 - Oct 2025)

**PRODUCTION (1.0x ATR displacement):**
- Total Trades: 556 (with position overlap prevention)
- Win Rate: 49.3%
- Max Drawdown: 20%
- Total P&L: $296.89 (minimal in backtest due to simple dollar calculation)

**Configuration:** Position overlap prevention enabled (only 1 trade at a time)

### Renko Chart Engine

Uses an **ATR-Based Brick Building** method to construct Renko charts, adapting brick sizes to market volatility and tracking trend strength.

### Runtime Safety Layer

A production-grade **SafetyManager** (`engine/safety_manager.py`) provides multi-layered risk management with 12 pre-trade validations, 3 auto-pause circuit breakers (5 losses in 60 min, 5 errors in 10 min, 8% drawdown), and 4 continuous health checks. Circuit breaker thresholds are calibrated conservatively.

### System Reliability & Crash Recovery

A multi-layer **Reliability Architecture** ensures zero-gap market coverage and position protection:

- **Heartbeat Monitoring**: 5-second heartbeat thread updates state file with timestamps
- **Watchdog Protection**: 60-second stall detection auto-terminates frozen processes
- **External Supervisor**: (`engine/supervisor.py`) monitors heartbeat every 15 seconds, auto-restarts on failure, guarantees <60-second recovery
- **Atomic State Writes**: Temp-file writes with SHA256 checksums prevent corruption
- **Backup Recovery**: Maintains last 3 state backups with automatic rollback on corruption
- **Position Recovery**: On restart, evaluates open positions: exits if target hit/time exceeded/expired, resumes monitoring if valid, sends alerts if errors
- **Crash Alerts**: Pushover notifications for watchdog triggers, restart events, recovery actions, and critical failures

### Options Engine

The `Options Engine` generates a grid of strikes, estimates option premiums, and automatically selects optimal options structures (long options, debit spreads, butterflies) based on risk-reward ratios for maximum leverage efficiency.

### Professional Trading Dashboard

A production-ready web dashboard (`dashboard/app.py`) provides real-time monitoring and control:
- **Core Features**: Live P&L, position monitoring, regime status via WebSocket, account overview, Safety Manager visualization, circuit breaker monitoring, performance metrics, interactive P&L chart, and an emergency kill switch.
- **Pushover Notification System**: Delivers critical alerts for circuit breaker triggers, daily loss limits, trade execution/exit, and system errors.
- **Technical Stack**: Flask with Flask-SocketIO (backend), Vanilla JavaScript with Chart.js (frontend), background threads for real-time updates, Replit Secrets for security.

## External Dependencies

### Python Libraries

-   **pandas**: Data manipulation.
-   **numpy**: Numerical computations.
-   **matplotlib**: Visualization.
-   **pyyaml**: Configuration management.
-   **pytest**: Testing.
-   **python-dotenv**: Environment variables.
-   **requests**: HTTP requests (APIs, Pushover).
-   **flask**: Web framework.
-   **flask-socketio**: WebSocket for dashboard.

### Active API Integrations

-   **Polygon.io API**: Real-time 1-minute QQQ bars and live 0DTE options chain snapshots (bid/ask spreads).
-   **Alpaca API**: Historical 1-minute bar data.

### Data Sources

-   **QQQ 1-Minute Bars**: Sourced from Alpaca and Polygon.io APIs (22-month dataset: Jan 2024 - Oct 2025).
-   **0DTE Options Chain Data**: Real-time bid/ask spreads from Polygon.io.
-   **Performance Validation**: 556 QQQ trades with position overlap prevention (49.3% win rate, 20% max drawdown).

## Friday Trading (Nov 26, 2025)

**System Status: READY with REALISTIC EXPECTATIONS ✅**

- Auto-start: 9:25 AM ET (9:30 AM market open)
- Strategy: **ICT Confluence** (validated 49.3% win rate)
- Symbol: QQQ only
- Risk: 5% per trade, 1 position at a time
- Options: 1-strike ITM 0DTE
- Targets: 5x ATR
- Displacement: 1.0x ATR (Production threshold)
- Dashboard: Live at port 5000
- Reliability: Multi-layer heartbeat/watchdog/supervisor system
- Auto-stop: 4:05 PM ET

**Expected Performance:** ~49% win rate, ~20% max drawdown (validated over 22 months)
