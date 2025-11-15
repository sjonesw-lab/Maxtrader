# Paper Trading Architecture

## Overview

MaxTrader is architected to support live paper trading with minimal code changes. The system is designed to transition from backtest → paper trading → live trading seamlessly.

## Current State (Backtest Mode)

The system currently operates in **backtest mode** using historical CSV data:
- Data source: CSV files
- Time: Historical bars
- Execution: Simulated options payoffs
- Risk: Zero (simulation only)

## Paper Trading Mode (Ready to Implement)

### Architecture Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Paper Trading Pipeline                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Live Data Feed (Polygon.io)                              │
│     ↓                                                         │
│  2. Renko + Regime Detection                                 │
│     ↓                                                         │
│  3. Session Labeling (Asia/London/NY)                        │
│     ↓                                                         │
│  4. ICT Structure Detection                                  │
│     ↓                                                         │
│  5. Signal Generation (regime-adaptive)                      │
│     ↓                                                         │
│  6. Options Structure Selection                              │
│     ↓                                                         │
│  7. Paper Order Submission (Alpaca/IBKR)                     │
│     ↓                                                         │
│  8. Position Monitoring & Exit Logic                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Required Integrations

#### 1. **Polygon.io** (Live Data Feed)
- **Purpose**: Real-time & historical QQQ 1-minute bars + options chain data
- **Endpoints Needed**:
  - `GET /v2/aggs/ticker/{ticker}/range/1/minute/{from}/{to}` - Historical bars
  - `GET /v2/last/trade/{ticker}` - Latest price
  - `GET /v3/snapshot/options/{ticker}` - Options chain snapshot
- **Authentication**: API key (free tier: 5 API calls/min, 2 years historical)
- **Use Replit Integration**: Search for "Polygon" integration to manage API keys

#### 2. **Alpaca** or **Interactive Brokers** (Paper Execution)
- **Purpose**: Paper trading account for options execution
- **Alpaca Paper**:
  - Free paper trading account
  - REST API for order submission
  - Supports options trading
  - Real-time position tracking
- **IBKR Paper**:
  - More realistic fill simulation
  - Requires IBKR account
  - TWS API integration

### Implementation Plan

#### Phase 1: Data Integration (Week 1)

**File**: `engine/data_provider_live.py`

```python
class PolygonDataProvider(DataProvider):
    """Live data provider using Polygon.io API."""
    
    def __init__(self, api_key: str, symbol: str):
        self.api_key = api_key
        self.symbol = symbol
        self.base_url = "https://api.polygon.io"
    
    def load_bars(self, from_date: str, to_date: str) -> pd.DataFrame:
        """Fetch historical bars from Polygon."""
        # Implementation
    
    def get_latest_bar(self) -> dict:
        """Get most recent 1-minute bar."""
        # Implementation
    
    def get_options_chain(self, expiry: str) -> pd.DataFrame:
        """Fetch options chain for given expiry."""
        # Implementation
```

#### Phase 2: Paper Execution (Week 2)

**File**: `engine/execution_engine.py`

```python
class PaperExecutionEngine:
    """Handles paper order submission and position management."""
    
    def __init__(self, broker: str = "alpaca"):
        self.broker = broker
        # Initialize broker API connection
    
    def submit_options_spread(self, structure: OptionPosition) -> str:
        """
        Submit multi-leg options order.
        Returns: order_id
        """
        # Implementation
    
    def get_position_pnl(self, order_id: str) -> float:
        """Get current P&L for position."""
        # Implementation
    
    def close_position(self, order_id: str) -> bool:
        """Close position at market."""
        # Implementation
```

#### Phase 3: Live Strategy Runner (Week 3)

**File**: `paper_trading_main.py`

```python
"""
Live paper trading runner.
Runs continuously, checking for signals every minute.
"""

import time
from datetime import datetime
from engine.data_provider_live import PolygonDataProvider
from engine.optimizer import load_best_params_per_regime
from engine.execution_engine import PaperExecutionEngine

def run_live_strategy():
    """Main paper trading loop."""
    
    # Initialize
    data_provider = PolygonDataProvider(api_key=os.getenv("POLYGON_API_KEY"))
    execution = PaperExecutionEngine(broker="alpaca")
    params = load_best_params_per_regime()
    
    # Track open positions
    open_positions = {}
    
    while True:
        current_time = datetime.now()
        
        # Only trade during market hours
        if not is_market_open(current_time):
            time.sleep(60)
            continue
        
        # Fetch latest bar
        latest_bar = data_provider.get_latest_bar()
        
        # Update rolling window (last 500 bars)
        df = update_rolling_window(latest_bar)
        
        # Detect regime
        regime = detect_current_regime(df)
        
        # Use regime-specific params
        current_params = params[regime]
        
        # Check for signals (only during NY open window)
        if in_ny_open_window(current_time):
            signals = generate_signals(df, current_params)
            
            if signals:
                # Submit paper order
                for signal in signals:
                    order_id = execution.submit_options_spread(signal)
                    open_positions[order_id] = {
                        'signal': signal,
                        'entry_time': current_time
                    }
        
        # Monitor open positions
        for order_id, position in list(open_positions.items()):
            # Check exit conditions
            pnl = execution.get_position_pnl(order_id)
            signal = position['signal']
            
            # Exit if target hit or max time held
            if should_exit(pnl, signal, position['entry_time']):
                execution.close_position(order_id)
                del open_positions[order_id]
        
        # Sleep until next minute
        time.sleep(60)
```

### Configuration Requirements

**File**: `configs/paper_trading.yaml`

```yaml
# Paper Trading Configuration

data:
  provider: "polygon"
  polygon_api_key_env: "POLYGON_API_KEY"
  
execution:
  broker: "alpaca"  # or "ibkr"
  alpaca_api_key_env: "ALPACA_API_KEY"
  alpaca_api_secret_env: "ALPACA_API_SECRET"
  paper_mode: true
  
risk:
  max_positions: 3
  max_daily_loss: 500
  max_position_cost: 200
  
trading_hours:
  ny_open_start: "09:30"
  ny_open_end: "11:00"
  force_close_time: "15:45"
```

### Safety Features

1. **Position Limits**: Max 3 concurrent positions
2. **Daily Loss Limit**: Stop trading if down $500 in a day
3. **Max Position Size**: Cap each trade at $200 premium
4. **Force Close**: Close all positions at 3:45pm ET
5. **Paper Mode Flag**: Prevents accidental live trading

### Monitoring & Logging

**File**: `engine/trade_logger.py`

```python
class TradeLogger:
    """Log all trading activity for review."""
    
    def log_signal(self, signal: Signal):
        """Log signal generation."""
    
    def log_entry(self, order_id: str, position: OptionPosition):
        """Log position entry."""
    
    def log_exit(self, order_id: str, pnl: float):
        """Log position exit."""
    
    def daily_summary(self) -> dict:
        """Generate end-of-day summary."""
```

### Testing Strategy

1. **Dry Run**: Run paper_trading_main.py with `DRY_RUN=true` (no actual orders)
2. **Paper Account**: Test with Alpaca paper trading for 1 week
3. **Monitor Fills**: Ensure realistic fill simulation
4. **Compare to Backtest**: Verify live results match backtest expectations

### Timeline to Paper Trading

- **Week 1**: Polygon integration + live data pipeline
- **Week 2**: Alpaca paper execution engine
- **Week 3**: Live strategy runner + monitoring
- **Week 4**: 1 week paper trading validation
- **Week 5**: Ready for live (if paper results satisfy)

### Code Changes Required

**Minimal**:
1. Create `data_provider_live.py` (new file)
2. Create `execution_engine.py` (new file)
3. Create `paper_trading_main.py` (new file)
4. Add Polygon/Alpaca integrations via Replit

**Zero changes needed** to:
- Renko engine
- Regime detection
- ICT structures
- Strategy logic
- Options builder
- Optimizer

The architecture is **already paper-trading ready** - just add data/execution layers!

### Next Steps

1. **Get real historical QQQ data** (Polygon free tier)
2. **Run optimizer_main.py** with real data
3. **Validate backtest** with optimized params
4. **Set up Alpaca paper account**
5. **Implement live data provider**
6. **Build execution engine**
7. **Deploy to production** (Monday morning 9:30am ET)
