# MaxTrader Liquidity Options Engine v4

## Overview

MaxTrader is an **intraday NASDAQ trading research engine** that generates quantitative trading signals using ICT (Inner Circle Trader) liquidity concepts on QQQ and executes using options structures. The system is designed as a backtesting framework that combines advanced price action analysis with options trading strategies, with no hard stops on the underlying asset—risk is defined entirely by options payoff structures.

The engine analyzes three global trading sessions (Asia, London, NY), detects liquidity sweeps and price action patterns, and generates signals during the NY open window (09:30-11:00 ET). It supports multiple options structures including long calls/puts, debit spreads, butterflies, and broken-wing butterflies.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Design Principles

**Modular Pipeline Architecture**: The system uses a sequential pipeline approach where data flows through distinct transformation stages: data loading → session labeling → ICT structure detection → signal generation → options execution → backtesting. Each module is independent and testable.

**Options-First Risk Management**: Unlike traditional trading systems that use stop-losses on the underlying, this system defines all risk through options payoff structures. The maximum loss is capped at the premium paid for options, eliminating the need for stop-loss orders. This approach provides defined-risk exposure while maintaining unlimited profit potential on long positions.

**Session-Based Liquidity Tracking**: The architecture separates trading time into three global sessions (Asia: 18:00-03:00, London: 03:00-09:30, NY: 09:30-16:00, all in America/New_York timezone). Session highs and lows are tracked and used to identify liquidity zones that may be swept. The system handles midnight boundary crossings for the Asia session to prevent look-ahead bias.

**Signal Generation Window**: All trade signals are generated exclusively during the NY open window (09:30-11:00 ET). This design choice reflects real-world trading constraints and focuses on the highest-volatility period.

### Data Layer

**CSVDataProvider**: Currently implements file-based data loading for backtesting. The abstract `DataProvider` base class allows future integration with live data sources (Polygon, Alpaca) without changing downstream logic. All timestamps are converted to timezone-aware America/New_York format to ensure consistent session labeling.

**Data Format**: Expects standard OHLCV bars (open, high, low, close, volume) at 1-minute resolution for intraday analysis. The timestamp column must be ISO8601 UTC format in the CSV.

### ICT Structure Detection

**Liquidity Sweeps**: Detects when price briefly violates a session high/low (creating a wick) but closes back inside, indicating a liquidity grab. Bullish sweeps occur below session lows; bearish sweeps occur above session highs.

**Displacement Candles**: Uses ATR (Average True Range) to identify abnormally large candles that suggest institutional order flow. A displacement candle must exceed 1.5x the recent ATR.

**Fair Value Gaps (FVG)**: Identifies price gaps where candle N+2's low is above candle N's high (bullish FVG) or candle N+2's high is below candle N's low (bearish FVG), suggesting inefficient price discovery.

**Market Structure Shifts (MSS)**: Tracks swing highs and lows to detect when price breaks recent structure, signaling potential trend changes.

**Order Blocks**: Identifies the last opposite-colored candle before a strong move, representing potential institutional accumulation/distribution zones.

### Renko Chart Engine

**ATR-Based Brick Building**: Constructs Renko charts with brick sizes determined by the Average True Range (ATR) of the underlying price data. This adaptive approach ensures brick sizes scale with market volatility. Each brick represents a fixed price movement, filtering out time and small fluctuations to reveal clearer trend information.

**Direction Tracking**: Assigns a direction (+1 for up bricks, -1 for down bricks) to each Renko brick and aligns these directions with the original 1-minute bar timestamps, enabling regime detection on the time series.

**Trend Strength Calculation**: Computes rolling trend strength by analyzing the proportion of consecutive same-direction bricks over a lookback window, providing a smoothed measure of trend momentum.

### Regime Detection

**Market Classification**: Categorizes market conditions into three regimes:
- **Bull Trend**: Sustained upward Renko trend (trend strength > 0.6) with positive price slope
- **Bear Trend**: Sustained downward Renko trend (trend strength < -0.6) with negative price slope  
- **Sideways**: Mixed Renko directions or weak trend strength, indicating consolidation or choppy conditions

**Regime-Based Signal Filtering**: Acts as an additional signal filter layered on top of ICT structure confluence. Long signals are permitted in bull_trend or sideways regimes; short signals in bear_trend or sideways regimes. This prevents counter-trend trades while still allowing range-bound opportunities.

**No Look-Ahead Bias**: Regime classification uses only current and historical Renko data, ensuring no future information leaks into trading decisions.

### Options Engine

**Strike Generation**: Creates a grid of strikes around the current spot price (default: 20 strikes with $1 increments) to enable precise options structure construction.

**Premium Estimation**: Uses Black-Scholes-inspired simplified model to estimate option premiums based on spot price, strike, time to expiry, and assumed volatility (20% IV). For backtesting purposes, this provides reasonable approximations without requiring full options chain data.

**Structure Selection Algorithm**: Automatically selects the optimal options structure based on risk-reward ratio, comparing:
- Long options (highest leverage, highest cost)
- Debit spreads (capped profit, reduced cost)
- Butterflies (limited risk/reward, very low cost)
- Broken-wing butterflies (asymmetric payoff)

The system chooses the structure with the best risk-reward ratio while respecting account size constraints.

**Payoff Simulation**: Uses actual price path data to simulate P&L over the holding period, accounting for time decay and options sensitivity to underlying price movements.

### Strategy Layer

**Signal Confluence**: Requires multiple ICT structures to align before generating a signal:
- Liquidity sweep in one direction
- Displacement candle confirming the move
- Fair Value Gap supporting the direction
- Market structure shift confirming trend change
- Optional: Order block zone interaction
- Optional: Regime filter (enabled by default) - long signals in bull/sideways, short signals in bear/sideways

**Target Calculation**: Dynamically finds targets based on recent swing highs (for longs) or swing lows (for shorts) within a configurable lookback window.

**Direction Logic**: Long signals require bullish sweeps + bullish displacement + bullish FVG. Short signals require bearish sweeps + bearish displacement + bearish FVG.

### Backtesting Engine

**Trade Execution**: Simulates entry at signal time, constructs the selected options position, and holds until either target is reached or maximum holding period expires (default: 60 bars = 1 hour).

**Performance Metrics**: Calculates win rate, average R-multiple (P&L / risk), total return, and individual trade results. Uses R-multiples to normalize performance across different position sizes.

**No Look-Ahead Bias**: Session highs/lows are calculated only from completed sessions, ensuring no future data leaks into trading decisions.

### Testing Strategy

**Unit Tests**: Each module has dedicated tests covering core functionality (session labeling, structure detection, Renko building, regime detection, options calculations, signal logic). Current test count: 24 passing tests.

**Regression Tests**: Specific test for Asia session midnight boundary handling to prevent look-ahead bias bugs.

**Fixtures**: Uses simple DataFrame fixtures with known values to verify calculations produce expected outputs.

**Renko Tests**: test_renko.py validates ATR/fixed brick building modes, direction alignment, trend strength calculation, and edge cases.

**Regime Tests**: test_regimes.py verifies bull/bear/sideways classification, regime statistics, and signal filtering logic.

## External Dependencies

### Python Libraries

**pandas**: Primary data manipulation library for time series operations, session grouping, and feature engineering.

**numpy**: Numerical computations for ATR calculations, payoff simulations, and statistical operations.

**matplotlib**: Visualization of price charts, session boundaries, and backtest equity curves. Uses 'Agg' backend for non-interactive rendering.

**pyyaml**: Configuration management (settings.yaml) for strategy parameters.

**pytest**: Testing framework for unit and integration tests.

**python-dotenv**: Environment variable management for future API key storage.

**requests**: HTTP library for future integration with external data/execution APIs.

### Future Integrations (Architected For)

**Polygon.io API**: Real-time and historical market data provider. The abstract DataProvider interface allows drop-in replacement of CSVDataProvider with PolygonDataProvider.

**Alpaca/Interactive Brokers**: Execution platforms for live options trading. The current options engine provides the structure definitions needed for order submission.

### Data Sources

**QQQ 1-Minute Bars**: Primary trading instrument (NASDAQ-100 ETF) used as proxy for NQ futures. Currently sourced from CSV files; production system would connect to live data feeds.

**Options Chain Data**: Currently estimated using simplified Black-Scholes model. Production system would require real options chain data from broker APIs for accurate pricing.