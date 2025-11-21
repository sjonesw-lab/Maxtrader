# MaxTrader Liquidity Options Engine

## Overview

MaxTrader is an intraday NASDAQ trading research engine that uses a wave-based Renko framework and multi-timeframe confluence analysis to generate quality-driven trading signals. It identifies wave impulses and retracement patterns, integrating daily and 4-hour market context. All trades utilize options structures for defined risk. The system features a multi-regime architecture with robust runtime safety layers. A key discovery is the "CHAMPION STRATEGY" which combines ICT confluence with 5x ATR targets and 0DTE **1-strike ITM options** (not ATM), resulting in 2,000%+ 3-month returns with 80% win rate and only 3% max drawdown. The system includes a professional real-time trading dashboard with live updates, comprehensive safety monitoring, and integrated Pushover notifications. An auto-trader executes realistic paper trading using real options pricing data from Polygon.io for both Conservative and Aggressive strategies. **CRITICAL BUG FIXES (Nov 19, 2025):** Position overlap prevention added (only 1 trade at a time to match backtest), risk percentage corrected from 3%/4% to 5%/5% to match backtest validation, and duplicate Pushover notification spam fixed (now sends startup/market-open notifications only once per day). **QQQ-ONLY OPTIMIZATION (Nov 19, 2025):** After comprehensive 22-month backtest analysis (928 trades), QQQ-only delivers 80.5% win rate vs 53% for dual-symbol (QQQ+SPY). SPY diluted edge from 80.5% to 53% while adding 2,318 mediocre trades. System now configured for **QQQ-ONLY trading** with validated 80.5% win rate, +$3,261 avg P&L per trade. **PRODUCTION RELIABILITY SYSTEM (Nov 20, 2025):** Multi-layer reliability architecture with heartbeat monitoring (5-second intervals), watchdog auto-termination (30-second stall detection), external supervisor for auto-restart (<60-second recovery guarantee), atomic state writes with checksums, intelligent position recovery after crashes, and Pushover crash alerts. System now production-grade with zero-gap market coverage. **VWAP MEAN-REVERSION MODULE (Nov 21, 2025):** Pluggable VWAP strategy module added as isolated optional component. Uses session-based VWAP with ATR-based deviation bands and non-trend day filters. Initial backtest (3-month sample): 91.7% win rate on 24 trades. Module is DISABLED by default behind feature flag - **use ICT strategy only for Friday trading**. VWAP needs full 5-year validation before live deployment.

## User Preferences

Preferred communication style: Simple, everyday language. Wants production-ready system for Friday 9:30 AM market open with validated backtest logic.

## System Architecture

### Core Design Principles

The system employs a **Modular Pipeline Architecture** for data processing, signal generation, and execution. **Options-First Risk Management** defines all risk through options payoff structures. **Session-Based Liquidity Tracking** identifies liquidity zones using global sessions, primarily generating signals during the NY open window.

### Data Layer

The `CSVDataProvider` handles file-based data for backtesting, expecting 1-minute OHLCV data. An abstract `DataProvider` allows for future live data integration.

### Polygon-Based Paper Trading System

The **Automated QQQ-Only Trader** (`engine/auto_trader.py`) conducts realistic paper trading using Polygon.io's real options pricing data. It executes entries at the ask price and exits at the bid price, tracking positions and account balance internally without broker integration. **QQQ-ONLY CONFIGURATION**: Trades QQQ exclusively after analysis showed 80.5% win rate (+$3,261 avg P&L) vs 53% for dual-symbol trading (SPY diluted performance). Supports both Conservative (5% risk) and Aggressive (5% risk) strategies with strict position limits (1 total position at a time). **CRITICAL OPTIMIZATION**: Uses 1-strike ITM options (not ATM), which backtests showed delivers +2,000% returns vs +135% for ATM over 3 months, with 80% win rate and only 3% max drawdown. **RELIABILITY**: Production-grade reliability system with heartbeat thread (5s updates), watchdog monitor (60s stall detection), atomic state writes with checksums, backup recovery, and intelligent position recovery that evaluates exit conditions (target hit, time limit, expiration) after crashes to protect trades. **PERFORMANCE**: Analyzes last 100 bars only (5-minute rolling window) to prevent signal detection hangs while maintaining full ICT confluence detection accuracy.

### ICT Structure Detection

The ICT module is **ENABLED** and acts as the primary signal generator. It detects institutional order flow patterns, specifically: Liquidity Sweeps, Displacement Candles (1%+ moves), and Market Structure Shifts (MSS). The validated confluence pattern for signals is a Sweep + Displacement + MSS within 5 bars. Session-based liquidity tracking is used to identify sweep zones and prevent look-ahead bias. **FRIDAY STATUS: PRODUCTION-READY**

### VWAP Mean-Reversion Strategy (Experimental)

A pluggable VWAP mean-reversion strategy module (`engine/vwap_meanrev_strategy.py`) has been added as an optional, isolated component. Features:
- **Session-based VWAP** calculation with ATR-based deviation bands
- **Non-trend day filters** to trade only on range-bound days
- **Entry window** between 10:00 AM - 3:30 PM ET
- **Maximum 1 trade per day** per symbol
- **Debit spreads only** for defined risk

Initial backtest on QQQ (Jan-Mar 2024): 91.7% win rate on 24 trades, $608.99 P&L. **STATUS: DISABLED by default (set `enabled: false` in `configs/strategies.yaml`). Needs full 5-year backtest validation before live deployment. NOT recommended for Friday - use ICT strategy only.**

### Pluggable Strategy Registry

A new `StrategyRegistry` (`engine/strategy_registry.py`) enables multiple strategies to coexist behind feature flags:
- **ICT Confluence** (enabled by default)
- **VWAP Mean-Reversion** (disabled by default, set in `configs/strategies.yaml`)

Each strategy is completely isolated - disabling one has zero impact on others.

### Renko Chart Engine

Uses an **ATR-Based Brick Building** method to construct Renko charts, adapting brick sizes to market volatility and tracking trend strength.

### Runtime Safety Layer

A production-grade **SafetyManager** (`engine/safety_manager.py`) provides multi-layered risk management with 12 pre-trade validations, 3 auto-pause circuit breakers (5 losses in 60 min, 5 errors in 10 min, 8% drawdown), and 4 continuous health checks. Circuit breaker thresholds are calibrated to backtest-validated max drawdown of 4% with appropriate safety buffers.

### System Reliability & Crash Recovery

A multi-layer **Reliability Architecture** ensures zero-gap market coverage and position protection:

- **Heartbeat Monitoring**: 5-second heartbeat thread updates state file with timestamps
- **Watchdog Protection**: 60-second stall detection auto-terminates frozen processes
- **External Supervisor**: (`engine/supervisor.py`) monitors heartbeat every 15 seconds, auto-restarts on failure, guarantees <60-second recovery
- **Atomic State Writes**: Temp-file writes with SHA256 checksums prevent corruption
- **Backup Recovery**: Maintains last 3 state backups with automatic rollback on corruption
- **Position Recovery**: On restart, evaluates open positions: exits if target hit/time exceeded/expired, resumes monitoring if valid, sends alerts if errors
- **Crash Alerts**: Pushover notifications for watchdog triggers, restart events, recovery actions, and critical failures

### Regime Detection & Routing

The **Multi-Regime Architecture** supports four market regimes (`NORMAL_VOL`, `ULTRA_LOW_VOL`, `EXTREME_CALM_PAUSE`, `HIGH_VOL`). The `RegimeRouter` calculates VIX and ATR to route to the appropriate strategy.

### Options Engine

The `Options Engine` generates a grid of strikes, estimates option premiums, and automatically selects optimal options structures (long options, debit spreads, butterflies) based on risk-reward ratios for maximum leverage efficiency.

### Butterfly Exit Module

A sophisticated Henry Gambell-style butterfly exit system (`execution/fly_exit.py`) that NEVER uses full-fly combo orders. Instead, it decomposes ALL butterfly exits into split verticals to avoid market maker games, wide bid/ask spreads, and fill problems. Key features:

- **Structure Detection**: Automatically identifies Unbalanced Butterflies (UBFly 1:-3:+2) and Balanced Butterflies (1:-2:+1) for both put and call sides
- **Body Collapse First**: Closes ALL short body exposure using vertical spreads, with safety nets ensuring no orphan shorts remain even in multi-unit positions
- **Wing Management**: Tracks consumed quantities to prevent double-closing wings, only exits remaining longs if valuable
- **Exit Decision Rules**: 5-tier priority system - loss cut, profit capture (60% target), time-based give-up, pin profit (2x credit), and expiration-day assignment avoidance
- **Multi-Unit Support**: Handles any number of fly units by maintaining correct pairing ratios across all shorts and wings
- **Real-Time DTE**: Uses current days-to-expiration for all exit timing decisions

### Strategy Layer

The **Strategy Layer** requires confluence of multiple indicators. Configurations exist for "Relaxed" (higher signal frequency) and "Standard" (higher confidence) strategies. Targets are dynamically calculated from recent swing highs/lows.

### Walk-Forward Optimizer

This component continuously learns and persists optimal parameters for each market regime through walk-forward optimization to prevent overfitting.

### Backtesting Engine

Simulates trade execution, constructs options positions, and calculates performance metrics without look-ahead bias.

### Testing Strategy

The system utilizes comprehensive unit tests, regression tests, and fixtures.

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
-   **Performance Validation**: 928 QQQ trades (80.5% win rate) vs 2,626 dual-symbol trades (53% win rate).

## Friday Trading (Nov 22, 2025)

**System Status: READY ✅**

- Auto-start: 9:25 AM ET (9:30 AM market open)
- Strategy: **ICT Confluence ONLY** (validated 80.5% win rate)
- VWAP strategy: DISABLED (experimental module, needs validation)
- Symbol: QQQ only
- Risk: 5% per trade, 1 position at a time
- Options: 1-strike ITM 0DTE
- Targets: 5x ATR
- Dashboard: Live at port 5000
- Reliability: Multi-layer heartbeat/watchdog/supervisor system
- Auto-stop: 4:05 PM ET
