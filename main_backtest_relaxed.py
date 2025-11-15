"""
Relaxed backtest for testing with sample data.
Reduces confluence requirements to generate signals.
"""

import warnings
warnings.filterwarnings('ignore')

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
from engine.strategy import Signal, in_ny_open_window, find_target
from engine.backtest import Backtest
import pandas as pd


def generate_signals_relaxed(df: pd.DataFrame, enable_regime_filter: bool = False) -> list:
    """
    RELAXED signal generation for testing.
    Only requires: sweep + FVG (no displacement or MSS required)
    """
    signals = []
    
    for idx in df.index:
        row = df.loc[idx]
        
        if not in_ny_open_window(row['timestamp']):
            continue
        
        # RELAXED: Only sweep + FVG
        bullish_setup = row['sweep_bullish'] and row['fvg_bullish']
        
        if enable_regime_filter and 'regime' in df.columns:
            regime = row['regime']
            bullish_setup = bullish_setup and regime in ['bull_trend', 'sideways']
        
        if bullish_setup:
            target = find_target(df, idx, 'long')
            
            if target is not None:
                signal = Signal(
                    index=idx,
                    timestamp=row['timestamp'],
                    direction='long',
                    spot=row['close'],
                    target=target,
                    source_session=row['sweep_source'],
                    meta={
                        'sweep': 'bullish',
                        'fvg': 'bullish',
                        'regime': row.get('regime', 'unknown'),
                        'relaxed_mode': True
                    }
                )
                signals.append(signal)
        
        # RELAXED: Only sweep + FVG
        bearish_setup = row['sweep_bearish'] and row['fvg_bearish']
        
        if enable_regime_filter and 'regime' in df.columns:
            regime = row['regime']
            bearish_setup = bearish_setup and regime in ['bear_trend', 'sideways']
        
        if bearish_setup:
            target = find_target(df, idx, 'short')
            
            if target is not None:
                signal = Signal(
                    index=idx,
                    timestamp=row['timestamp'],
                    direction='short',
                    spot=row['close'],
                    target=target,
                    source_session=row['sweep_source'],
                    meta={
                        'sweep': 'bearish',
                        'fvg': 'bearish',
                        'regime': row.get('regime', 'unknown'),
                        'relaxed_mode': True
                    }
                )
                signals.append(signal)
    
    return signals


def main():
    """Run backtest with relaxed signal requirements."""
    
    print("=" * 70)
    print("MaxTrader Liquidity Options Engine v4 - RELAXED MODE")
    print("Testing with reduced confluence requirements")
    print("=" * 70)
    print()
    
    print("Step 1: Loading QQQ data...")
    data_path = "data/sample_QQQ_1m.csv"
    
    if not Path(data_path).exists():
        print(f"ERROR: Data file not found: {data_path}")
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
    
    print("  - Fair Value Gaps (FVG)...")
    df = detect_fvgs(df)
    
    print(f"  ✓ ICT structures detected")
    print()
    
    print("Step 6: Generating RELAXED signals (sweep + FVG only)...")
    signals = generate_signals_relaxed(df, enable_regime_filter=False)
    
    print(f"  ✓ Generated {len(signals)} signals")
    
    if signals:
        long_signals = [s for s in signals if s.direction == 'long']
        short_signals = [s for s in signals if s.direction == 'short']
        print(f"    - Long signals: {len(long_signals)}")
        print(f"    - Short signals: {len(short_signals)}")
    print()
    
    if len(signals) == 0:
        print("Still no signals. Sample data may not have sweep+FVG confluence.")
        return
    
    print("Step 7: Running options backtest...")
    backtest = Backtest(df, signals)
    results = backtest.run(max_bars_held=60)
    
    print(f"  ✓ Backtest complete")
    print()
    
    print("=" * 70)
    print("PERFORMANCE SUMMARY (RELAXED MODE)")
    print("=" * 70)
    print()
    print(f"Total Trades:        {results['total_trades']}")
    print(f"Win Rate:            {results['win_rate']*100:.1f}%")
    print(f"Average PnL:         ${results['avg_pnl']:.2f}")
    print(f"Average R-Multiple:  {results['avg_r_multiple']:.2f}R")
    print(f"Total PnL:           ${results['total_pnl']:.2f}")
    print()
    
    if results['total_trades'] > 0:
        print("Sample Trades:")
        print("-" * 70)
        for i, trade in enumerate(results['trades'][:5], 1):
            print(f"\nTrade {i}:")
            print(f"  Direction:   {trade.signal.direction.upper()}")
            print(f"  Entry:       {trade.signal.timestamp} @ ${trade.signal.spot:.2f}")
            print(f"  Structure:   {trade.signal.meta.get('sweep')} sweep + {trade.signal.meta.get('fvg')} FVG")
            print(f"  PnL:         ${trade.pnl:.2f} ({trade.r_multiple:.2f}R)")
    
    print()
    print("=" * 70)
    print("NOTE: This is RELAXED mode for testing only.")
    print("Production system requires full confluence:")
    print("  sweep + displacement + FVG + MSS + regime filter")
    print("=" * 70)


if __name__ == '__main__':
    main()
