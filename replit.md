# MaxTrader Liquidity Options Engine

## Overview

MaxTrader is an intraday NASDAQ trading research engine designed for quality-driven trading signals using a wave-based Renko framework and multi-timeframe confluence analysis. It identifies wave impulses and retracement patterns, integrating daily and 4-hour market context. All trades utilize options structures for defined risk. The system currently features a multi-regime architecture with a validated Normal Vol strategy (43.5% WR, 9.39 PF) and robust runtime safety layers, with ongoing research into high-volatility environments.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Design Principles

The system employs a **Modular Pipeline Architecture** with independent, testable stages for data processing, signal generation, and execution. **Options-First Risk Management** defines all risk through options payoff structures, capping maximum loss at the premium paid. **Session-Based Liquidity Tracking** uses global sessions (Asia, London, NY) to identify liquidity zones, handling midnight boundary crossings to prevent look-ahead bias. Signals are primarily generated during the NY open window.

### Data Layer

The `CSVDataProvider` handles file-based data loading for backtesting, with an abstract `DataProvider` allowing future live data integration. It expects 1-minute OHLCV data with timezone-aware `America/New_York` timestamps.

### ICT Structure Detection (Disabled by Default)

While implemented with features like Liquidity Sweeps, Displacement Candles, Fair Value Gaps (FVG), Market Structure Shifts (MSS), and Order Blocks, this module is currently disabled as it degraded performance in testing. It can be re-enabled if tuning improves.

### Renko Chart Engine

Uses an **ATR-Based Brick Building** method to construct Renko charts, adapting brick sizes to market volatility. It tracks brick direction and calculates trend strength based on consecutive same-direction bricks.

### Runtime Safety Layer

A production-grade **SafetyManager** (`engine/safety_manager.py`) provides multi-layered risk management. It includes 12 pre-trade validations (e.g., kill switch, loss limits, position limits), 3 auto-pause circuit breakers (rapid loss, error rate, drawdown), and 4 continuous health checks. Default safety limits for a $50k account are 2% daily loss and 1% max position size per trade. The system is designed for live trading integration and includes 29 passing unit tests.

### Regime Detection & Routing

The **Multi-Regime Architecture** supports four market regimes: `NORMAL_VOL` (VIX 13-30), `ULTRA_LOW_VOL` (VIX 8-13), `EXTREME_CALM_PAUSE` (VIX <8), and `HIGH_VOL` (VIX >30, deferred). The `RegimeRouter` calculates VIX and ATR to route to the appropriate strategy, ensuring no look-ahead bias.

### Options Engine

The `Options Engine` generates a grid of strikes, estimates option premiums using a simplified Black-Scholes model for backtesting, and automatically selects optimal options structures (long options, debit spreads, butterflies, broken-wing butterflies) based on risk-reward ratios. It simulates P&L over holding periods.

### Strategy Layer

The **Strategy Layer** requires confluence of multiple indicators. A "Relaxed" configuration (Config D) uses Sweep + Displacement + MSS + Regime filter for higher signal frequency, while a "Standard" (Strict) configuration prioritizes higher confidence. Targets are dynamically calculated from recent swing highs/lows.

### Walk-Forward Optimizer

This component continuously learns optimal parameters for each market regime through walk-forward optimization, preventing overfitting by training on sequential data segments. It uses a composite scoring function to balance performance metrics and persists optimized parameters.

### Backtesting Engine

Simulates trade execution, constructs options positions, and holds until targets are reached or the holding period expires. It calculates performance metrics like win rate, average R-multiple, and total return, ensuring no look-ahead bias.

### Testing Strategy

The system utilizes a comprehensive testing strategy including unit tests for each module (35+ passing tests), regression tests for critical logic, and fixtures to verify calculations.

## External Dependencies

### Python Libraries

-   **pandas**: Data manipulation, time series operations.
-   **numpy**: Numerical computations.
-   **matplotlib**: Visualization.
-   **pyyaml**: Configuration management.
-   **pytest**: Testing framework.
-   **python-dotenv**: Environment variable management.
-   **requests**: HTTP library for future API integrations.

### Future Integrations (Architected For)

-   **Polygon.io API**: Real-time and historical market data (via WebSocket).
-   **Alpaca API**: Paper trading and live execution for options orders.

### Data Sources

-   **QQQ 1-Minute Bars**: Primary trading instrument, sourced from Polygon.io API.
-   **Options Chain Data**: Currently estimated; will require real options chain data from broker APIs for production.