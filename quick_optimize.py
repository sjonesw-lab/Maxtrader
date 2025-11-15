"""
Quick optimizer for real data - tests fewer parameters faster.
"""

import warnings
warnings.filterwarnings('ignore')

from engine.data_provider import CSVDataProvider
from engine.optimizer import (
    StrategyParams,
    walkforward_optimize_by_regime,
    save_best_params_per_regime
)

def main():
    print("=" * 70)
    print("Quick Optimizer - Real QQQ Data")
    print("=" * 70)
    print()
    
    print("Loading real market data...")
    provider = CSVDataProvider(path='data/QQQ_1m_real.csv', symbol='QQQ')
    df = provider.load_bars()
    print(f"  ✓ {len(df)} bars loaded")
    print()
    
    print("Creating lightweight parameter grid...")
    param_grid = [
        StrategyParams(renko_k=0.8, regime_lookback=15, exit_minutes=45, enable_ob_filter=False),
        StrategyParams(renko_k=1.0, regime_lookback=20, exit_minutes=60, enable_ob_filter=False),
        StrategyParams(renko_k=1.2, regime_lookback=20, exit_minutes=60, enable_ob_filter=True),
    ]
    print(f"  ✓ {len(param_grid)} parameter sets to test")
    print()
    
    print("Running walk-forward optimization (1 split)...")
    results = walkforward_optimize_by_regime(
        df,
        param_grid=param_grid,
        n_splits=1
    )
    
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print()
    
    for regime, params in results['best_params_per_regime'].items():
        print(f"{regime.upper()}:")
        print(f"  renko_k: {params.renko_k}")
        print(f"  regime_lookback: {params.regime_lookback}")
        print(f"  exit_minutes: {params.exit_minutes}")
        print(f"  enable_ob_filter: {params.enable_ob_filter}")
        print()
    
    print("Saving optimized parameters...")
    save_best_params_per_regime(
        results['best_params_per_regime'],
        filepath='configs/strategy_params.json'
    )
    print("  ✓ Saved to configs/strategy_params.json")
    print()
    
    print("=" * 70)
    print("DONE - Parameters optimized on REAL market data!")
    print("=" * 70)
    print()
    print("Next: python main_backtest_adaptive.py")

if __name__ == '__main__':
    main()
