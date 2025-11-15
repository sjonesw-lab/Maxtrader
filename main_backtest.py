"""
MaxTrader Liquidity Options Engine v4 - Main Backtest Script

Runs full backtest pipeline:
1. Load data
2. Apply ICT transformations
3. Generate signals
4. Execute options trades
5. Calculate and display performance
"""

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import (
    detect_liquidity_sweeps,
    detect_displacement,
    detect_fvgs,
    detect_mss,
    detect_order_blocks
)
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime, get_regime_stats
from engine.strategy import generate_signals_relaxed
from engine.backtest import Backtest


def main():
    """Run complete backtest pipeline."""
    
    print("=" * 70)
    print("MaxTrader Liquidity Options Engine v4")
    print("Intraday NASDAQ Trading Research Engine")
    print("=" * 70)
    print()
    
    print("Step 1: Loading QQQ data...")
    data_path = "data/QQQ_1m_real.csv"
    
    if not Path(data_path).exists():
        print(f"ERROR: Data file not found: {data_path}")
        print("Please ensure sample_QQQ_1m.csv exists in the data/ directory")
        return
    
    provider = CSVDataProvider(path=data_path, symbol="QQQ")
    df = provider.load_bars()
    
    print(f"  ✓ Loaded {len(df)} bars")
    print(f"  ✓ Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print()
    
    print("Step 2: Building Renko chart...")
    renko_df = build_renko(df, mode="atr", k=1.0)
    renko_direction = get_renko_direction_series(df, renko_df)
    print(f"  ✓ Built {len(renko_df)} Renko bricks")
    print()
    
    print("Step 3: Detecting market regime...")
    df['renko_direction'] = renko_direction
    df['regime'] = detect_regime(df, renko_direction, lookback=20)
    regime_stats = get_regime_stats(df)
    print(f"  ✓ Regime detection complete")
    for regime, pct in regime_stats['regime_percentages'].items():
        print(f"    - {regime}: {pct:.1f}%")
    print()
    
    print("Step 4: Labeling sessions (Asia/London/NY)...")
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    print(f"  ✓ Session labels added")
    print()
    
    print("Step 5: Detecting ICT structures...")
    print("  - Liquidity sweeps...")
    df = detect_liquidity_sweeps(df)
    
    print("  - Displacement candles (ATR-based, 1.0x threshold for Config D)...")
    df = detect_displacement(df, atr_period=14, threshold=1.0)
    
    print("  - Fair Value Gaps (FVG)...")
    df = detect_fvgs(df)
    
    print("  - Market Structure Shifts (MSS)...")
    df = detect_mss(df)
    
    print("  - Order Blocks (OB)...")
    df = detect_order_blocks(df)
    
    print(f"  ✓ All ICT structures detected")
    print()
    
    print("Step 6: Generating signals (Config D: relaxed, NY window: 09:30-12:00)...")
    signals = generate_signals_relaxed(
        df,
        require_fvg=False,
        displacement_threshold=1.0,
        extended_window=True,
        enable_regime_filter=True
    )
    
    print(f"  ✓ Generated {len(signals)} signals")
    
    if signals:
        long_signals = [s for s in signals if s.direction == 'long']
        short_signals = [s for s in signals if s.direction == 'short']
        print(f"    - Long signals: {len(long_signals)}")
        print(f"    - Short signals: {len(short_signals)}")
        
        signals_by_regime = {}
        for signal in signals:
            regime = signal.meta.get('regime', 'unknown')
            signals_by_regime[regime] = signals_by_regime.get(regime, 0) + 1
        
        print(f"  Signals by regime:")
        for regime, count in signals_by_regime.items():
            print(f"    - {regime}: {count}")
    print()
    
    if len(signals) == 0:
        print("No signals generated. Try different data or parameters.")
        return
    
    print("Step 7: Running options backtest...")
    backtest = Backtest(df, signals)
    results = backtest.run(max_bars_held=60)
    
    print(f"  ✓ Backtest complete")
    print()
    
    print("=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    print()
    print(f"Total Trades:        {results['total_trades']}")
    print(f"Win Rate:            {results['win_rate']*100:.1f}%")
    print(f"Average PnL:         ${results['avg_pnl']:.2f}")
    print(f"Average R-Multiple:  {results['avg_r_multiple']:.2f}R")
    print(f"Total PnL:           ${results['total_pnl']:.2f}")
    print(f"Max Drawdown:        ${results['max_drawdown']:.2f}")
    print()
    
    if results['total_trades'] > 0:
        print("Trade Details:")
        print("-" * 70)
        for i, trade in enumerate(results['trades'][:10], 1):
            print(f"\nTrade {i}:")
            print(f"  Direction:   {trade.signal.direction.upper()}")
            print(f"  Entry:       {trade.signal.timestamp} @ ${trade.signal.spot:.2f}")
            print(f"  Target:      ${trade.signal.target:.2f}")
            print(f"  Entry Cost:  ${trade.entry_cost:.2f}")
            print(f"  PnL:         ${trade.pnl:.2f} ({trade.r_multiple:.2f}R)")
            print(f"  Exit:        {trade.exit_time}")
        
        if results['total_trades'] > 10:
            print(f"\n... and {results['total_trades'] - 10} more trades")
    
    print()
    print("=" * 70)
    
    print("\nGenerating equity curve chart...")
    plot_equity_curve(results['equity_curve'])
    print("  ✓ Chart saved to: equity_curve.png")
    
    print("\n" + "=" * 70)
    print("Backtest complete!")
    print("=" * 70)


def plot_equity_curve(equity_curve):
    """
    Plot and save equity curve.
    
    Args:
        equity_curve: List of cumulative PnL values
    """
    plt.figure(figsize=(12, 6))
    plt.plot(equity_curve, linewidth=2, color='#2E86AB')
    plt.axhline(y=0, color='red', linestyle='--', linewidth=1, alpha=0.5)
    plt.title('Equity Curve', fontsize=16, fontweight='bold')
    plt.xlabel('Trade Number', fontsize=12)
    plt.ylabel('Cumulative PnL ($)', fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('equity_curve.png', dpi=150, bbox_inches='tight')
    plt.close()


if __name__ == "__main__":
    main()
