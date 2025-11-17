#!/usr/bin/env python3
"""
Download random months of QQQ data from Polygon and backtest.

This script:
1. Selects 3 random months from the last 6 years  
2. Downloads 1-minute OHLCV data from Polygon
3. Runs the MaxTrader wave-based backtest on each month
4. Generates comparison reports
"""

import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from polygon import RESTClient
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy_wave_renko import generate_wave_signals
from engine.strategy import Signal
from engine.backtest import Backtest
from engine.timeframes import resample_to_timeframe
from engine.ict_structures import detect_all_structures


def select_random_months(num_months: int = 3, years_back: int = 6) -> list:
    """
    Select random months from the last N years.
    
    Returns list of tuples: (year, month, month_name)
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years_back * 365)
    
    all_months = []
    current = start_date.replace(day=1)
    
    while current <= end_date:
        # Skip current month (incomplete data)
        if not (current.year == end_date.year and current.month == end_date.month):
            all_months.append((current.year, current.month, current.strftime('%B')))
        
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    selected = random.sample(all_months, min(num_months, len(all_months)))
    selected.sort()
    
    return selected


def download_month_data(
    symbol: str,
    year: int,
    month: int,
    api_key: str,
    output_dir: Path
) -> Path:
    """
    Download 1-minute data for a specific month from Polygon.
    
    Returns path to saved CSV file.
    """
    print(f"\n{'='*60}")
    print(f"📥 Downloading {symbol} data for {year}-{month:02d}")
    print(f"{'='*60}")
    
    client = RESTClient(api_key)
    
    # Calculate date range (first day to last day of month)
    from_date = datetime(year, month, 1)
    if month == 12:
        to_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        to_date = datetime(year, month + 1, 1) - timedelta(days=1)
    
    from_str = from_date.strftime('%Y-%m-%d')
    to_str = to_date.strftime('%Y-%m-%d')
    
    print(f"Date range: {from_str} to {to_str}")
    
    # Fetch data from Polygon
    all_bars = []
    
    try:
        print(f"Fetching 1-minute bars from Polygon API...")
        
        # Polygon API for aggregate bars
        for bar in client.list_aggs(
            ticker=symbol,
            multiplier=1,
            timespan="minute",
            from_=from_str,
            to=to_str,
            limit=50000
        ):
            all_bars.append({
                'timestamp': datetime.fromtimestamp(bar.timestamp / 1000).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            })
            
            if len(all_bars) % 10000 == 0:
                print(f"  Downloaded {len(all_bars):,} bars...")
        
        print(f"✅ Downloaded {len(all_bars):,} total bars")
        
    except Exception as e:
        print(f"❌ Error downloading data: {e}")
        raise
    
    if not all_bars:
        raise ValueError(f"No data returned for {symbol} in {year}-{month:02d}")
    
    # Convert to DataFrame and save
    df = pd.DataFrame(all_bars)
    
    # Save to CSV
    output_file = output_dir / f"{symbol}_{year}_{month:02d}_1min.csv"
    df.to_csv(output_file, index=False)
    
    print(f"💾 Saved to: {output_file}")
    print(f"   Size: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"   Bars: {len(df):,}")
    
    return output_file


def run_backtest_on_month(data_path: Path) -> dict:
    """
    Run MaxTrader wave-based backtest on a single month of data.
    
    Returns performance metrics.
    """
    print(f"\n{'='*60}")
    print(f"🧪 Running backtest on: {data_path.name}")
    print(f"{'='*60}")
    
    # Load data
    provider = CSVDataProvider(str(data_path))
    df_1min = provider.load_bars()
    
    print(f"Loaded {len(df_1min):,} bars")
    print(f"Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")
    
    # Resample to 4H and Daily
    df_4h = resample_to_timeframe(df_1min, '4h')
    df_daily = resample_to_timeframe(df_1min, '1D')
    
    # Label sessions
    df_1min = label_sessions(df_1min)
    df_1min = add_session_highs_lows(df_1min)
    
    # Detect ICT structures
    df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
    
    # Build Renko
    k_value = 4.0
    renko_df = build_renko(df_1min, mode="atr", k=k_value, atr_period=14)
    brick_size = renko_df['brick_size'].iloc[0]
    
    # Detect regime
    df_30min = resample_to_timeframe(df_1min, '30min')
    renko_30min = build_renko(df_30min, mode="atr", k=1.0)
    renko_direction_30min = get_renko_direction_series(df_30min, renko_30min)
    regime_30min = detect_regime(df_30min, renko_direction_30min, lookback=20)
    
    # Align regime to 1-min data
    df_1min['regime'] = 'sideways'
    for idx in range(len(df_1min)):
        ts = df_1min['timestamp'].iloc[idx]
        mask = df_30min['timestamp'] <= ts
        if mask.any():
            regime_idx = mask.sum() - 1
            if regime_idx < len(regime_30min):
                df_1min.loc[df_1min.index[idx], 'regime'] = regime_30min.iloc[regime_idx]
    
    # Generate signals
    wave_signals = generate_wave_signals(
        df_1min=df_1min,
        df_4h=df_4h,
        df_daily=df_daily,
        renko_df=renko_df,
        regime_series=df_1min['regime'],
        brick_size=brick_size,
        min_bricks=3,
        max_entry_distance=1.5,
        min_confidence=0.40,
        use_ict_boost=False,
        target_mode='swing_75',
        require_sweep=False,
        use_volume_filter=False,
        avoid_lunch_chop=False,
        use_dynamic_targets=False,
        min_rr_ratio=2.0
    )
    
    print(f"Generated {len(wave_signals)} signals")
    
    # Convert to standard Signal format
    signals = []
    for ws in wave_signals:
        matching = df_1min[df_1min['timestamp'] == ws.timestamp]
        if not matching.empty:
            sig = Signal(
                index=matching.index[0],
                timestamp=ws.timestamp,
                direction=ws.direction,
                entry_price=ws.entry_price,
                target_price=ws.target_price,
                stop_loss=ws.stop_loss,
                confidence=ws.confidence,
                reason=ws.reason
            )
            signals.append(sig)
    
    # Run backtest
    backtest = Backtest(df_1min, min_rr_ratio=1.6, use_scaling_exit=False)
    results = backtest.run(signals, max_bars_held=120)
    
    # Extract metrics
    metrics = {
        'data_file': data_path.name,
        'month': data_path.stem.split('_')[1] + '-' + data_path.stem.split('_')[2],
        'start_date': str(df_1min['timestamp'].min()),
        'end_date': str(df_1min['timestamp'].max()),
        'total_bars': len(df_1min),
        'total_signals': len(signals),
        'total_trades': results.get('total_trades', 0),
        'winning_trades': results.get('winning_trades', 0),
        'losing_trades': results.get('losing_trades', 0),
        'win_rate': results.get('win_rate', 0.0),
        'profit_factor': results.get('profit_factor', 0.0),
        'total_pnl': results.get('total_pnl', 0.0),
        'avg_win': results.get('avg_win', 0.0),
        'avg_loss': results.get('avg_loss', 0.0),
        'sharpe_ratio': results.get('sharpe_ratio', 0.0),
        'max_drawdown': results.get('max_drawdown', 0.0)
    }
    
    print(f"\n📊 Backtest Results:")
    print(f"   Signals: {metrics['total_signals']}")
    print(f"   Trades: {metrics['total_trades']}")
    print(f"   Win Rate: {metrics['win_rate']:.1f}%")
    print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"   Total P&L: ${metrics['total_pnl']:,.2f}")
    
    return metrics


def generate_comparison_report(all_metrics: list, output_dir: Path):
    """Generate comparison report across all months."""
    print(f"\n{'='*60}")
    print(f"📊 MULTI-MONTH BACKTEST COMPARISON")
    print(f"{'='*60}\n")
    
    df = pd.DataFrame(all_metrics)
    
    # Save to CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = output_dir / f"multi_month_backtest_{timestamp}.csv"
    df.to_csv(report_path, index=False)
    
    print(f"Summary Statistics:")
    print(f"{'='*60}")
    
    summary_stats = {
        'Total Months Tested': len(all_metrics),
        'Total Signals': int(df['total_signals'].sum()),
        'Total Trades': int(df['total_trades'].sum()),
        'Avg Win Rate': f"{df['win_rate'].mean():.1f}%",
        'Avg Profit Factor': f"{df['profit_factor'].mean():.2f}",
        'Total P&L (All Months)': f"${df['total_pnl'].sum():,.2f}",
        'Avg P&L Per Month': f"${df['total_pnl'].mean():,.2f}",
        'Best Month': df.loc[df['total_pnl'].idxmax(), 'month'],
        'Best Month P&L': f"${df['total_pnl'].max():,.2f}",
        'Worst Month': df.loc[df['total_pnl'].idxmin(), 'month'],
        'Worst Month P&L': f"${df['total_pnl'].min():,.2f}"
    }
    
    for key, value in summary_stats.items():
        print(f"{key:.<40} {value}")
    
    print(f"\n{'='*60}")
    print(f"📄 Detailed report saved: {report_path}")
    print(f"{'='*60}")
    
    return report_path


def main():
    """Main execution."""
    print("\n" + "="*60)
    print("🎲 RANDOM MONTH BACKTEST SYSTEM")
    print("="*60)
    
    # Setup
    api_key = os.getenv('POLYGON_API_KEY')
    if not api_key:
        print("❌ Error: POLYGON_API_KEY not found in environment")
        sys.exit(1)
    
    # Create directories
    data_dir = Path('data/polygon_downloads')
    data_dir.mkdir(parents=True, exist_ok=True)
    
    reports_dir = Path('reports/multi_month_backtests')
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Select random months
    print("\n🎲 Selecting 3 random months from last 6 years...")
    selected_months = select_random_months(num_months=3, years_back=6)
    
    print(f"\n✅ Selected months:")
    for year, month, month_name in selected_months:
        print(f"   - {month_name} {year}")
    
    # Step 2: Download data
    downloaded_files = []
    
    for year, month, month_name in selected_months:
        try:
            file_path = download_month_data(
                symbol='QQQ',
                year=year,
                month=month,
                api_key=api_key,
                output_dir=data_dir
            )
            downloaded_files.append(file_path)
            
            # Rate limiting
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Failed to download {month_name} {year}: {e}")
            continue
    
    if not downloaded_files:
        print("\n❌ No data downloaded successfully")
        sys.exit(1)
    
    # Step 3: Run backtests
    all_metrics = []
    
    for data_file in downloaded_files:
        try:
            metrics = run_backtest_on_month(data_file)
            all_metrics.append(metrics)
            
        except Exception as e:
            print(f"❌ Backtest failed for {data_file.name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    if not all_metrics:
        print("\n❌ No backtests completed successfully")
        sys.exit(1)
    
    # Step 4: Generate comparison report
    report_path = generate_comparison_report(all_metrics, reports_dir)
    
    print(f"\n{'='*60}")
    print(f"✅ COMPLETED SUCCESSFULLY")
    print(f"{'='*60}")
    print(f"Downloaded: {len(downloaded_files)} months")
    print(f"Backtested: {len(all_metrics)} months")
    print(f"Report: {report_path}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
