# MaxTrader Liquidity Options Engine v4

An **intraday NASDAQ trading research engine** that generates trading signals using ICT (Inner Circle Trader) liquidity concepts on QQQ and executes using options structures.

## Overview

This system combines advanced price action concepts with options trading strategies to create a quantitative backtest engine for intraday NASDAQ trading.

### Key Features

- **ICT Methodology**: Implements liquidity sweeps, displacement candles, Fair Value Gaps (FVG), Market Structure Shifts (MSS), and Order Blocks
- **Session Analysis**: Tracks Asia (18:00-03:00), London (03:00-09:30), and NY (09:30-16:00) sessions
- **Options Execution**: Supports long options, debit spreads, butterflies, and broken-wing butterflies
- **No Hard Stops**: Risk is defined entirely by options structure, not underlying price stops
- **Automated Structure Selection**: Chooses optimal options structure based on risk-reward analysis

## Project Structure

```
maxtrader_liquidity_options_v4/
├── data/
│   └── sample_QQQ_1m.csv          # Sample 1-minute QQQ data
├── engine/
│   ├── __init__.py
│   ├── data_provider.py           # Data loading and providers
│   ├── sessions_liquidity.py      # Session labeling and liquidity zones
│   ├── ict_structures.py          # ICT structure detection
│   ├── options_engine.py          # Options structure builders
│   ├── strategy.py                # Signal generation
│   └── backtest.py                # Backtesting engine
├── configs/
│   └── settings.yaml              # Configuration settings
├── tests/
│   └── test_*.py                  # Unit tests
├── main_backtest.py               # Main backtest script
├── generate_sample_data.py        # Sample data generator
├── requirements.txt               # Python dependencies
└── .env.example                   # Environment variables template
```

## Installation

1. **Clone or download** this project

2. **Install dependencies**:
   ```bash
   pip install pandas numpy matplotlib requests python-dotenv pytest pyyaml
   ```

3. **Generate sample data** (or provide your own QQQ 1-minute CSV):
   ```bash
   python generate_sample_data.py
   ```

## Usage

### Running a Backtest

```bash
python main_backtest.py
```

This will:
1. Load QQQ 1-minute data
2. Label trading sessions
3. Detect ICT structures
4. Generate trading signals
5. Execute options trades
6. Display performance metrics
7. Generate equity curve chart

### Expected Output

```
======================================================================
MaxTrader Liquidity Options Engine v4
Intraday NASDAQ Trading Research Engine
======================================================================

Step 1: Loading QQQ data...
  ✓ Loaded 7200 bars
  ✓ Date range: 2024-01-01 to 2024-01-06

Step 2: Labeling sessions (Asia/London/NY)...
  ✓ Session labels added

Step 3: Detecting ICT structures...
  ✓ All ICT structures detected

Step 4: Generating signals (NY window: 09:30-11:00)...
  ✓ Generated X signals

Step 5: Running options backtest...
  ✓ Backtest complete

======================================================================
PERFORMANCE SUMMARY
======================================================================
Total Trades:        X
Win Rate:            XX.X%
Average PnL:         $XX.XX
Average R-Multiple:  X.XXR
Total PnL:           $XXX.XX
Max Drawdown:        $XX.XX
```

## Data Format

The engine expects CSV data with these columns:

- `timestamp`: ISO8601 UTC timestamp
- `open`: Open price
- `high`: High price
- `low`: Low price
- `close`: Close price
- `volume`: Volume

Example:
```csv
timestamp,open,high,low,close,volume
2024-01-02T00:00:00Z,390.5,391.2,390.1,390.8,250000
```

## Signal Generation Logic

A **LONG signal** requires:
1. Time in NY window (09:30-11:00 America/New_York)
2. Bullish sweep of Asia OR London low
3. Bullish displacement candle (body > 1.2 * ATR)
4. Bullish Fair Value Gap
5. Bullish Market Structure Shift
6. (Optional) Bullish Order Block confluence

**SHORT signals** use the mirror logic.

## Options Structures

The engine builds and evaluates:
1. **Long options**: ATM calls (bullish) or puts (bearish)
2. **Debit spreads**: Long ATM, short near target
3. **Butterflies**: Balanced 3-leg structure
4. **Broken-wing butterflies**: Asymmetric risk/reward

Structure selection prioritizes best risk-reward ratio at target price.

## Exit Rules

- **Target hit**: Exit when underlying touches target price
- **Time/EOD exit**: Exit at end-of-day (16:00) or after max holding period (60 minutes)
- **No stop loss**: Risk is capped by options debit paid

## Future Enhancements

The architecture supports future integration with:

### Live Data Providers
- **Polygon.io**: Real-time and historical market data
- **Alpaca**: Market data and broker execution

### Broker Execution
- **Alpaca**: Paper and live trading
- **Interactive Brokers (IBKR)**: Professional execution platform

### Placeholders Ready
- `PolygonDataProvider` in `engine/data_provider.py`
- `AlpacaDataProvider` in `engine/data_provider.py`
- Environment variable support via `.env` file

To enable live trading:
1. Set API keys in `.env` file
2. Implement API calls in placeholder classes
3. Switch from `CSVDataProvider` to live provider

## Testing

Run unit tests:
```bash
pytest tests/
```

## Configuration

Edit `configs/settings.yaml` to adjust:
- ATR period
- Displacement multiplier
- NY trading window
- Options expiry rules
- Max bars held

## Performance Notes

- **Backtest Speed**: ~7200 bars processed in seconds
- **Memory Usage**: Minimal (pandas DataFrame-based)
- **Scalability**: Can handle multiple days/weeks of 1-minute data

## Disclaimer

This is a research tool for backtesting purposes only. Not financial advice. Past performance does not guarantee future results. Options trading involves substantial risk.

## License

MIT License - See LICENSE file for details

## Support

For questions or issues, please refer to the code documentation and inline comments.

---

**Built with Python 3.11+ | Powered by pandas, numpy, matplotlib**
