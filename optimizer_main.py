"""
Walk-Forward Optimizer Runner

Run this script weekly/monthly to:
- Load historical data
- Run walk-forward optimization by regime
- Save best parameters per regime
- Generate optimization report

Usage:
    python optimizer_main.py
    python optimizer_main.py --mode medium
    python optimizer_main.py --splits 6
"""

import argparse
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

from engine.data_provider import CSVDataProvider
from engine.optimizer import (
    get_param_grid,
    walkforward_optimize_by_regime,
    save_best_params_per_regime,
    save_walkforward_results
)


def main():
    parser = argparse.ArgumentParser(description='Walk-forward parameter optimization')
    parser.add_argument('--data', type=str, default='data/sample_QQQ_1m.csv',
                       help='Path to OHLCV data CSV')
    parser.add_argument('--mode', type=str, default='fast',
                       choices=['fast', 'medium', 'full'],
                       help='Optimization mode (fast=fewer params, full=more params)')
    parser.add_argument('--splits', type=int, default=4,
                       help='Number of walk-forward splits')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("MaxTrader Walk-Forward Optimizer")
    print("Regime-Adaptive Parameter Learning")
    print("=" * 70)
    print()
    
    print(f"Configuration:")
    print(f"  Data: {args.data}")
    print(f"  Mode: {args.mode}")
    print(f"  Walk-forward splits: {args.splits}")
    print()
    
    if not Path(args.data).exists():
        print(f"ERROR: Data file not found: {args.data}")
        print("Please provide valid OHLCV data file.")
        return
    
    print("Step 1: Loading data...")
    provider = CSVDataProvider(path=args.data, symbol="QQQ")
    df = provider.load_bars()
    print(f"  ✓ Loaded {len(df)} bars")
    print(f"  ✓ Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print()
    
    print("Step 2: Generating parameter grid...")
    param_grid = get_param_grid(mode=args.mode)
    print(f"  ✓ Generated {len(param_grid)} parameter combinations")
    print()
    
    print("Step 3: Running walk-forward optimization by regime...")
    print(f"  This will train on N segments, test on N+1")
    print(f"  Optimizing separately for bull/bear/sideways regimes")
    print()
    
    results = walkforward_optimize_by_regime(
        df,
        param_grid=param_grid,
        n_splits=args.splits
    )
    
    print()
    print("=" * 70)
    print("OPTIMIZATION RESULTS")
    print("=" * 70)
    print()
    
    print("Best Parameters Per Regime:")
    print("-" * 70)
    
    for regime, params in results['best_params_per_regime'].items():
        print(f"\n{regime.upper()}:")
        print(f"  Renko k: {params.renko_k}")
        print(f"  Regime lookback: {params.regime_lookback}")
        print(f"  Exit minutes: {params.exit_minutes}")
        print(f"  Enable OB filter: {params.enable_ob_filter}")
        print(f"  Enable regime filter: {params.enable_regime_filter}")
    
    print()
    print("Test Performance Summary:")
    print("-" * 70)
    
    test_results = results['test_results']
    
    if test_results:
        for regime in ['bull_trend', 'bear_trend', 'sideways']:
            regime_results = [r for r in test_results if r.get('regime') == regime]
            
            if not regime_results:
                continue
            
            avg_score = sum(r['score'] for r in regime_results) / len(regime_results)
            avg_wr = sum(r['win_rate'] for r in regime_results) / len(regime_results)
            avg_r = sum(r['avg_r'] for r in regime_results) / len(regime_results)
            total_trades = sum(r['num_trades'] for r in regime_results)
            
            print(f"\n{regime.upper()}:")
            print(f"  Avg Score: {avg_score:.2f}")
            print(f"  Avg Win Rate: {avg_wr*100:.1f}%")
            print(f"  Avg R-Multiple: {avg_r:.2f}R")
            print(f"  Total Trades: {total_trades}")
    else:
        print("  No test results (insufficient data or signals)")
    
    print()
    print("=" * 70)
    print()
    
    print("Step 4: Saving results...")
    save_best_params_per_regime(
        results['best_params_per_regime'],
        filepath='configs/strategy_params.json'
    )
    print("  ✓ Saved best params to configs/strategy_params.json")
    
    save_walkforward_results(
        results,
        filepath='configs/walkforward_results.json'
    )
    print("  ✓ Saved full results to configs/walkforward_results.json")
    print()
    
    print("=" * 70)
    print("OPTIMIZATION COMPLETE")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Review configs/strategy_params.json")
    print("  2. Run main_backtest.py to test optimized params")
    print("  3. Re-run this optimizer weekly/monthly with new data")
    print()
    print("The strategy will now use regime-specific parameters:")
    print("  - Bull regime → bull_trend params")
    print("  - Bear regime → bear_trend params")
    print("  - Sideways → sideways params")
    print()


if __name__ == '__main__':
    main()
