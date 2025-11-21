"""
VWAP Mean-Reversion Strategy Backtest Runner.

Runs isolated backtest of VWAP strategy only to validate performance
before enabling in production.

Usage:
    python scripts/backtest_vwap_only.py --symbol QQQ --start 2023-01-01 --end 2025-10-31
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
import pandas as pd
import yaml

sys.path.append(str(Path(__file__).parent.parent))

from engine.backtest import Backtest
from engine.vwap_meanrev_strategy import VWAPMeanReversionStrategy
from engine.data_provider import CSVDataProvider


def load_vwap_config():
    """Load VWAP strategy configuration."""
    config_path = Path("configs/strategies.yaml")
    
    if not config_path.exists():
        print("⚠️ strategies.yaml not found, using defaults")
        return {
            'enabled': True,
            'name': 'VWAP_MEANREV',
            'band_atr_frac': 0.5,
            'max_session_range_atr_frac': 1.0,
            'max_open_to_high_atr_frac': 0.7,
            'max_open_to_low_atr_frac': 0.7,
            'min_entry_time': '10:00',
            'max_entry_time': '15:30',
            'trend_cutoff_time': '11:00',
            'max_trades_per_day': 1,
            'stop_band_multiplier': 2.0
        }
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config['strategies']['vwap_meanrev']


def run_vwap_backtest(symbol: str, start_date: str, end_date: str, min_rr: float = 1.5):
    """
    Run VWAP-only backtest on historical data.
    
    Args:
        symbol: Stock symbol (QQQ, SPY)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        min_rr: Minimum risk-reward ratio filter
    """
    print("=" * 70)
    print("🧪 VWAP MEAN-REVERSION STRATEGY BACKTEST")
    print("=" * 70)
    print(f"Symbol: {symbol}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Min R:R: {min_rr}")
    print("=" * 70)
    
    data_file = Path(f"data/{symbol}_1m_2024_2025.csv")
    if not data_file.exists():
        print(f"❌ Data file not found: {data_file}")
        print(f"\nAvailable data files:")
        data_dir = Path("data")
        if data_dir.exists():
            for f in data_dir.glob("*.csv"):
                print(f"  - {f.name}")
        return None
    
    print(f"\n📂 Loading data: {data_file}")
    data_provider = CSVDataProvider(str(data_file), symbol=symbol)
    df = data_provider.load_bars()
    
    if df is not None and len(df) > 0:
        df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]
    
    if df is None or len(df) == 0:
        print(f"❌ No data loaded for {symbol}")
        return None
    
    print(f"✅ Loaded {len(df):,} bars")
    print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    
    vwap_config = load_vwap_config()
    print(f"\n⚙️  VWAP Config:")
    print(f"   Band: {vwap_config['band_atr_frac']}x ATR")
    print(f"   Entry window: {vwap_config['min_entry_time']} - {vwap_config['max_entry_time']}")
    print(f"   Max trades/day: {vwap_config['max_trades_per_day']}")
    
    strategy = VWAPMeanReversionStrategy(vwap_config)
    
    print(f"\n🔍 Generating signals...")
    signals = strategy.generate_signals(df)
    
    if len(signals) == 0:
        print("❌ No signals generated - strategy criteria too strict or data insufficient")
        return None
    
    print(f"✅ Generated {len(signals)} signals")
    print(f"   Long: {sum(1 for s in signals if s.direction == 'long')}")
    print(f"   Short: {sum(1 for s in signals if s.direction == 'short')}")
    
    print(f"\n🎯 Running backtest (min R:R = {min_rr})...")
    backtester = Backtest(df, min_rr_ratio=min_rr)
    results = backtester.run(signals)
    
    print("\n" + "=" * 70)
    print("📊 VWAP STRATEGY RESULTS")
    print("=" * 70)
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']*100:.1f}%")
    print(f"Avg P&L: ${results['avg_pnl']:.2f}")
    print(f"Total P&L: ${results['total_pnl']:.2f}")
    print(f"Max Drawdown: ${results['max_drawdown']:.2f}")
    print("=" * 70)
    
    if results['total_trades'] == 0:
        print("\n❌ No trades executed - all signals filtered by R:R ratio")
        print("   Try lowering min_rr or adjusting VWAP target calculation")
        return results
    
    if results['total_trades'] < 30:
        print("\n⚠️  WARNING: Low sample size (<30 trades on ~3 months data)")
        print("   Need longer backtest period for statistical significance")
    
    win_rate_pct = results['win_rate'] * 100
    avg_win = results['avg_pnl'] if results['win_rate'] > 0 else 0
    
    print(f"\n💡 Analysis:")
    print(f"   Signals generated: {len(signals)}")
    print(f"   Trades executed: {results['total_trades']} ({results['total_trades']/len(signals)*100:.0f}% pass R:R filter)")
    print(f"   Performance: {win_rate_pct:.1f}% win rate, ${results['avg_pnl']:.2f} avg/trade")
    print(f"   Total P&L: ${results['total_pnl']:.2f} over {len(df['timestamp'].dt.date.unique())} trading days")
    
    if win_rate_pct >= 60 and results['total_pnl'] > 0 and results['total_trades'] >= 20:
        print(f"\n✅ Promising initial results - needs validation on longer period")
    else:
        print(f"\n⚠️  Needs optimization or longer backtest for validation")
    
    trades_df = pd.DataFrame(backtester.trades)
    if len(trades_df) > 0:
        output_file = f"reports/vwap_backtest_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        Path("reports").mkdir(exist_ok=True)
        trades_df.to_csv(output_file, index=False)
        print(f"\n💾 Trade log saved: {output_file}")
    
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VWAP Mean-Reversion Strategy Backtest")
    parser.add_argument("--symbol", type=str, default="QQQ", help="Symbol to backtest")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2025-10-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--min-rr", type=float, default=1.5, help="Minimum R:R ratio")
    
    args = parser.parse_args()
    
    run_vwap_backtest(args.symbol, args.start, args.end, args.min_rr)
