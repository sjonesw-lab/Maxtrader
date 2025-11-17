# MaxTrader Liquidity Options Engine v4

## Overview

MaxTrader is an **intraday NASDAQ trading research engine** built on a wave-based Renko framework with multi-timeframe confluence analysis. The system generates quality-driven trading signals by detecting wave impulses, analyzing retracement patterns, and combining daily/4H market context. All trades execute using options structures for defined risk.

**Current Status (as of Nov 17, 2025):**

**Phase 1: Multi-Regime System (In Progress)**
- ✅ **Normal Vol (VIX 13-30):** Wave-Renko strategy working - 43.5% WR, 9.39 PF, $2,249 PnL
- ✅ **Ultra-Low Vol (VIX 8-13):** PA-confirmed VWAP mean-reversion complete
- ✅ **EXTREME_CALM_PAUSE (VIX <8):** Trading pause implemented and tested
- ⏭️ **High Vol (VIX >30):** Deferred to Phase 2 (see HIGH_VOL_DECISION.md, SMARTMONEY_HOMMA_RESEARCH.md)
- ⏭️ **Runtime Safety Layer:** Next implementation priority

**Normal Vol Strategy (Validated):**
- Win Rate: 43.5%, Profit Factor: 9.39
- Trade Frequency: 23/month (quality-driven)
- Total PnL: $2,249 over 90 days (Aug 18 - Nov 14, 2025)
- Uses wave-based Renko + regime filtering (ICT structures disabled)

**High Vol Research (Completed but Deferred):**
- Tested 2 approaches: Sweep-reclaim (Sharpe -3.50) and Smart Money + Homma MTF (Sharpe 0.94)
- Smart Money 1H/5min showed promise (75% WR, 3.32R avg) but only 2-4 trades/90 days
- Insufficient trade frequency for production deployment
- Phase 2: Will explore longer timeframes, multi-instrument deployment, or hybrid integration

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Design Principles

**Modular Pipeline Architecture**: The system uses a sequential pipeline approach where data flows through distinct transformation stages: data loading → session labeling → ICT structure detection → signal generation → options execution → backtesting. Each module is independent and testable.

**Options-First Risk Management**: Unlike traditional trading systems that use stop-losses on the underlying, this system defines all risk through options payoff structures. The maximum loss is capped at the premium paid for options, eliminating the need for stop-loss orders. This approach provides defined-risk exposure while maintaining unlimited profit potential on long positions.

**Session-Based Liquidity Tracking**: The architecture separates trading time into three global sessions (Asia: 18:00-03:00, London: 03:00-09:30, NY: 09:30-16:00, all in America/New_York timezone). Session highs and lows are tracked and used to identify liquidity zones that may be swept. The system handles midnight boundary crossings for the Asia session to prevent look-ahead bias.

**Signal Generation Window**: Signals are generated during the NY open window. Config D (relaxed) uses an extended window (09:30-12:00 ET) to increase signal frequency while maintaining quality. The standard configuration uses 09:30-11:00 ET.

### Data Layer

**CSVDataProvider**: Currently implements file-based data loading for backtesting. The abstract `DataProvider` base class allows future integration with live data sources (Polygon, Alpaca) without changing downstream logic. All timestamps are converted to timezone-aware America/New_York format to ensure consistent session labeling.

**Data Format**: Expects standard OHLCV bars (open, high, low, close, volume) at 1-minute resolution for intraday analysis. The timestamp column must be ISO8601 UTC format in the CSV.

### ICT Structure Detection (Optional, Disabled by Default)

**Status: Implemented but disabled** - Testing showed ICT confluence boost degraded performance (Win Rate -12pp, PF -2.8, PnL -$516).

**Available Structures:**
- **Liquidity Sweeps**: Detects when price briefly violates a session high/low (creating a wick) but closes back inside, indicating a liquidity grab.
- **Displacement Candles**: Uses ATR (Average True Range) with directional logic to identify abnormally large candles suggesting institutional order flow.
- **Fair Value Gaps (FVG)**: Identifies price gaps suggesting inefficient price discovery.
- **Market Structure Shifts (MSS)**: Tracks swing highs and lows to detect when price breaks recent structure.
- **Order Blocks**: Identifies the last opposite-colored candle before a strong move.

**Why Disabled:**
- ICT structures too common (73-83% presence) to add selectivity
- Multiplicative confidence blending suppressed scores below minimum threshold
- Distance-based target selection pulled TP1 too close, reducing win rate
- Can be re-enabled with `use_ict_boost=True` if tuning is improved

### Renko Chart Engine

**ATR-Based Brick Building**: Constructs Renko charts with brick sizes determined by the Average True Range (ATR) of the underlying price data. This adaptive approach ensures brick sizes scale with market volatility. Each brick represents a fixed price movement, filtering out time and small fluctuations to reveal clearer trend information.

**Direction Tracking**: Assigns a direction (+1 for up bricks, -1 for down bricks) to each Renko brick and aligns these directions with the original 1-minute bar timestamps, enabling regime detection on the time series.

**Trend Strength Calculation**: Computes rolling trend strength by analyzing the proportion of consecutive same-direction bricks over a lookback window, providing a smoothed measure of trend momentum.

### Regime Detection & Routing

**Multi-Regime Architecture (NEW)**: System now supports 4 distinct market regimes with dedicated strategies:

1. **NORMAL_VOL (VIX 13-30):** Wave-Renko strategy (validated, working)
2. **ULTRA_LOW_VOL (VIX 8-13):** VWAP mean-reversion (complete, needs live tuning)
3. **EXTREME_CALM_PAUSE (VIX <8):** Trading pause, capital preservation
4. **HIGH_VOL (VIX >30):** Deferred to Phase 2 (0DTE incompatible with crash volatility)

**RegimeRouter**: Central routing component that:
- Calculates VIX proxy from daily price data
- Calculates ATR percentage for volatility confirmation
- Routes to appropriate strategy based on market conditions
- Returns empty signals for EXTREME_CALM_PAUSE and HIGH_VOL regimes
- Logs regime changes for monitoring

**Regime-Based Signal Filtering (Legacy)**: Original Renko-based classification (bull_trend, bear_trend, sideways) still used within Normal Vol strategy for directional filtering.

**No Look-Ahead Bias**: All regime detection uses only current and historical data.

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

**Signal Confluence**: Requires multiple ICT structures to align. Two configurations available:
- **Config D (Relaxed)**: Sweep + Displacement (1.0x ATR) + MSS + Regime filter. Extended window (09:30-12:00). FVG optional. Delivers 11.3 signals/month with 67.6% win rate.
- **Standard (Strict)**: Sweep + Displacement (1.2x ATR) + FVG + MSS + Regime filter. Standard window (09:30-11:00). Higher confidence, fewer signals.

**Target Calculation**: Dynamically finds targets based on recent swing highs (for longs) or swing lows (for shorts) within a configurable lookback window.

**Direction Logic**: Config D (Relaxed): Long signals require bullish sweep + bullish displacement + bullish MSS in bull_trend/sideways regime. Short signals require bearish sweep + bearish displacement + bearish MSS in bear_trend/sideways regime. FVG is optional.

### Walk-Forward Optimizer

**Regime-Adaptive Parameter Tuning**: The system continuously learns optimal parameters for each market regime through walk-forward optimization. Parameters like Renko brick size (k), regime lookback period, exit timing, and filter settings are optimized separately for bull_trend, bear_trend, and sideways conditions.

**Walk-Forward Validation**: Splits historical data into sequential segments, trains on segment N, tests on segment N+1. This prevents overfitting and simulates real-world deployment where parameters are periodically reoptimized.

**Scoring Function**: Evaluates parameter sets using a composite score that balances win rate, average R-multiple, maximum drawdown, and trade frequency. Penalizes parameter sets that generate too few trades or excessive drawdown.

**Persistence**: Saves optimized parameters to `configs/strategy_params.json` and full optimization results to `configs/walkforward_results.json`. The strategy automatically loads regime-specific parameters at runtime.

**Continuous Learning**: Designed to be run weekly or monthly with new data via `optimizer_main.py`, allowing the system to adapt to changing market conditions over time.

### Backtesting Engine

**Trade Execution**: Simulates entry at signal time, constructs the selected options position, and holds until either target is reached or maximum holding period expires (default: 60 bars = 1 hour).

**Performance Metrics**: Calculates win rate, average R-multiple (P&L / risk), total return, and individual trade results. Uses R-multiples to normalize performance across different position sizes.

**No Look-Ahead Bias**: Session highs/lows are calculated only from completed sessions, ensuring no future data leaks into trading decisions.

### Testing Strategy

**Unit Tests**: Each module has dedicated tests covering core functionality (session labeling, structure detection, Renko building, regime detection, options calculations, signal logic, directional displacement). Current test count: 35 passing tests.

**Regression Tests**: Asia session midnight boundary handling, directional displacement logic (4 tests ensuring bullish/bearish signals require correct candle direction and are mutually exclusive).

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

**Polygon.io API**: Real-time and historical market data provider. Implemented via WebSocket streaming (engine/polygon_stream.py) for 1-minute bar delivery. Free tier provides 15-min delayed data suitable for paper trading.

**Alpaca API**: Paper trading execution platform (engine/alpaca_execution.py) for options orders. Level 3 options access by default in paper accounts. Live trading runner (live_trading_main.py) combines Polygon data stream with ICT signal generation and Alpaca execution.

### Data Sources

**QQQ 1-Minute Bars**: Primary trading instrument (NASDAQ-100 ETF). Real market data via Polygon.io API (90 days, 48,665 bars). Live streaming via WebSocket for paper trading deployment.

**Options Chain Data**: Currently estimated using simplified Black-Scholes model. Production system would require real options chain data from broker APIs for accurate pricing.