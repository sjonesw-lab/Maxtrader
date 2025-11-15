"""
Regime-Adaptive Backtest Runner

Loads optimized parameters per regime and applies them dynamically.
Uses different parameters for bull/bear/sideways market conditions.

Usage:
    python main_backtest_adaptive.py
"""

import warnings
warnings.filterwarnings('ignore')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

from engine.data_provider import CSVDataProvider
from engine.optimizer import load_best_params_per_regime, apply_params_to_data
from engine.strategy import generate_signals
from engine.backtest import Backtest


def main():
    """Run backtest with regime-adaptive parameters."""
    
    print("=" * 70)
    print("MaxTrader Liquidity Options Engine v4")
    print("Regime-Adaptive Backtest Mode")
    print("=" * 70)
    print()
    
    print("Step 1: Loading optimized parameters...")
    params_per_regime = load_best_params_per_regime('configs/strategy_params.json')
    
    print("  Loaded parameters for:")
    for regime in ['bull_trend', 'bear_trend', 'sideways']:
        params = params_per_regime[regime]
        print(f"    {regime}: renko_k={params.renko_k}, exit_min={params.exit_minutes}")
    print()
    
    print("Step 2: Loading QQQ data...")
    data_path = "data/sample_QQQ_1m.csv"
    
    if not Path(data_path).exists():
        print(f"ERROR: Data file not found: {data_path}")
        return
    
    provider = CSVDataProvider(path=data_path, symbol="QQQ")
    df = provider.load_bars()
    
    print(f"  ✓ Loaded {len(df)} bars")
    print(f"  ✓ Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print()
    
    print("Step 3: Applying regime-specific parameters...")
    print("  Note: Using bull_trend params as baseline for feature generation")
    
    baseline_params = params_per_regime['bull_trend']
    df = apply_params_to_data(df, baseline_params)
    
    print(f"  ✓ Features generated")
    print()
    
    regime_counts = df['regime'].value_counts()
    print("  Regime distribution:")
    for regime, count in regime_counts.items():
        pct = (count / len(df)) * 100
        print(f"    {regime}: {count} bars ({pct:.1f}%)")
    print()
    
    print("Step 4: Generating regime-adaptive signals...")
    
    signals_by_regime = {
        'bull_trend': [],
        'bear_trend': [],
        'sideways': []
    }
    
    for regime in ['bull_trend', 'bear_trend', 'sideways']:
        regime_df = df[df['regime'] == regime].copy()
        
        if len(regime_df) == 0:
            continue
        
        regime_params = params_per_regime[regime]
        
        regime_signals = generate_signals(
            regime_df,
            enable_ob_filter=regime_params.enable_ob_filter,
            enable_regime_filter=regime_params.enable_regime_filter
        )
        
        signals_by_regime[regime] = regime_signals
    
    all_signals = []
    for regime_signals in signals_by_regime.values():
        all_signals.extend(regime_signals)
    
    all_signals.sort(key=lambda s: s.timestamp)
    
    print(f"  ✓ Generated {len(all_signals)} total signals")
    
    for regime, signals in signals_by_regime.items():
        if signals:
            long_sigs = [s for s in signals if s.direction == 'long']
            short_sigs = [s for s in signals if s.direction == 'short']
            print(f"    {regime}: {len(signals)} signals ({len(long_sigs)}L / {len(short_sigs)}S)")
    print()
    
    if len(all_signals) == 0:
        print("No signals generated.")
        print("This is expected with sample data - ICT confluence is rare.")
        print("Run optimizer_main.py with real data to find optimal params.")
        return
    
    print("Step 5: Running options backtest...")
    backtest = Backtest(df, all_signals)
    results = backtest.run(max_bars_held=baseline_params.exit_minutes)
    
    print(f"  ✓ Backtest complete")
    print()
    
    print("=" * 70)
    print("PERFORMANCE SUMMARY (REGIME-ADAPTIVE)")
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
            print(f"  Regime:      {trade.signal.meta.get('regime', 'unknown')}")
            print(f"  PnL:         ${trade.pnl:.2f} ({trade.r_multiple:.2f}R)")
    
    print()
    print("=" * 70)


if __name__ == '__main__':
    main()
