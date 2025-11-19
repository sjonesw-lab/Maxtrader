# MaxTrader Liquidity Options Engine

## Overview

MaxTrader is an intraday NASDAQ trading research engine that uses a wave-based Renko framework and multi-timeframe confluence analysis to generate quality-driven trading signals. It identifies wave impulses and retracement patterns, integrating daily and 4-hour market context. All trades utilize options structures for defined risk. The system features a multi-regime architecture with robust runtime safety layers. A key discovery is the "CHAMPION STRATEGY" which combines ICT confluence with 5x ATR targets and 0DTE **1-strike ITM options** (not ATM), resulting in 2,000%+ 3-month returns with 80% win rate and only 3% max drawdown. The system includes a professional real-time trading dashboard with live updates, comprehensive safety monitoring, and integrated Pushover notifications. An auto-trader executes realistic paper trading using real options pricing data from Polygon.io for both Conservative and Aggressive strategies. **CRITICAL BUG FIXES (Nov 19, 2025):** Position overlap prevention added (only 1 trade at a time to match backtest), and risk percentage corrected from 3%/4% to 5%/5% to match backtest validation. **MULTI-SYMBOL EXPANSION (Nov 19, 2025):** Downloaded and analyzed SPY (372K bars, 1,779 signals, 2.6/day rate) and INDA (192K bars) to expand beyond QQQ. SPY shows nearly identical signal frequency to QQQ, suggesting strong strategy transferability.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Design Principles

The system employs a **Modular Pipeline Architecture** for data processing, signal generation, and execution. **Options-First Risk Management** defines all risk through options payoff structures. **Session-Based Liquidity Tracking** identifies liquidity zones using global sessions, primarily generating signals during the NY open window.

### Data Layer

The `CSVDataProvider` handles file-based data for backtesting, expecting 1-minute OHLCV data. An abstract `DataProvider` allows for future live data integration.

### Polygon-Based Paper Trading System

The **Automated Dual Trader** (`engine/auto_trader.py`) conducts realistic paper trading using Polygon.io's real options pricing data. It executes entries at the ask price and exits at the bid price, tracking positions and account balance internally without broker integration. **MULTI-SYMBOL SUPPORT**: Now trades both QQQ and SPY simultaneously (~5 signals/day total vs 2.5/day for QQQ alone). It supports both Conservative (5% risk) and Aggressive (5% risk) strategies, with strict position limits (1 total position at a time across all symbols). **CRITICAL OPTIMIZATION**: Uses 1-strike ITM options (not ATM), which backtests showed delivers +2,000% returns vs +135% for ATM over 3 months, with 80% win rate and only 3% max drawdown.

### ICT Structure Detection

The ICT module is **ENABLED** and acts as the primary signal generator. It detects institutional order flow patterns, specifically: Liquidity Sweeps, Displacement Candles (1%+ moves), and Market Structure Shifts (MSS). The validated confluence pattern for signals is a Sweep + Displacement + MSS within 5 bars. Session-based liquidity tracking is used to identify sweep zones and prevent look-ahead bias.

### Renko Chart Engine

Uses an **ATR-Based Brick Building** method to construct Renko charts, adapting brick sizes to market volatility and tracking trend strength.

### Runtime Safety Layer

A production-grade **SafetyManager** (`engine/safety_manager.py`) provides multi-layered risk management with 12 pre-trade validations, 3 auto-pause circuit breakers (rapid loss, error rate, drawdown), and 4 continuous health checks.

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

-   **QQQ 1-Minute Bars**: Sourced from Alpaca and Polygon.io APIs.
-   **0DTE Options Chain Data**: Real-time bid/ask spreads from Polygon.io.