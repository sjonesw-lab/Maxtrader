"""
Walk-forward optimizer with regime-specific parameter tuning.
Continuously learns optimal parameters for each market regime.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple
import pandas as pd
import numpy as np
import json
from pathlib import Path
import itertools

from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import (
    detect_liquidity_sweeps,
    detect_displacement,
    detect_fvgs,
    detect_mss,
    detect_order_blocks
)
from engine.strategy import generate_signals
from engine.backtest import Backtest


@dataclass
class StrategyParams:
    """Strategy parameters to optimize."""
    renko_k: float = 1.0
    regime_lookback: int = 20
    atr_period: int = 14
    max_trades_per_day: int = 5
    max_net_debit: float = 500.0
    exit_minutes: int = 60
    structure_priority: str = "auto"
    enable_ob_filter: bool = False
    enable_regime_filter: bool = True


def get_param_grid(mode: str = "fast") -> List[StrategyParams]:
    """
    Generate parameter combinations for optimization.
    
    Args:
        mode: 'fast' (few combos), 'medium', 'full' (many combos)
    
    Returns:
        List of StrategyParams to test
    """
    if mode == "fast":
        renko_k_values = [0.8, 1.0, 1.2]
        regime_lookback_values = [15, 20]
        exit_minutes_values = [45, 60]
        enable_ob_values = [False, True]
    elif mode == "medium":
        renko_k_values = [0.5, 0.8, 1.0, 1.2, 1.5]
        regime_lookback_values = [10, 15, 20, 25]
        exit_minutes_values = [30, 45, 60, 90]
        enable_ob_values = [False, True]
    else:
        renko_k_values = [0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0]
        regime_lookback_values = [10, 15, 20, 25, 30]
        exit_minutes_values = [30, 45, 60, 90, 120]
        enable_ob_values = [False, True]
    
    param_combinations = []
    
    for renko_k, regime_lb, exit_min, enable_ob in itertools.product(
        renko_k_values,
        regime_lookback_values,
        exit_minutes_values,
        enable_ob_values
    ):
        param_combinations.append(StrategyParams(
            renko_k=renko_k,
            regime_lookback=regime_lb,
            exit_minutes=exit_min,
            enable_ob_filter=enable_ob
        ))
    
    return param_combinations


def apply_params_to_data(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """
    Apply parameter set to raw data, building all features.
    
    Args:
        df: Raw OHLCV data
        params: Strategy parameters
    
    Returns:
        DataFrame with all features computed
    """
    df = df.copy()
    
    renko_df = build_renko(df, mode="atr", k=params.renko_k)
    renko_direction = get_renko_direction_series(df, renko_df)
    df['renko_direction'] = renko_direction
    df['regime'] = detect_regime(df, renko_direction, lookback=params.regime_lookback)
    
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    
    df = detect_liquidity_sweeps(df)
    df = detect_displacement(df, atr_period=params.atr_period)
    df = detect_fvgs(df)
    df = detect_mss(df)
    df = detect_order_blocks(df)
    
    return df


def evaluate_params(params: StrategyParams, df: pd.DataFrame) -> Dict:
    """
    Evaluate strategy parameters on given data.
    
    Args:
        params: Strategy parameters to test
        df: OHLCV data
    
    Returns:
        Dict with metrics: score, win_rate, avg_r, max_dd, num_trades
    """
    try:
        df_featured = apply_params_to_data(df, params)
        
        signals = generate_signals(
            df_featured,
            enable_ob_filter=params.enable_ob_filter,
            enable_regime_filter=params.enable_regime_filter
        )
        
        if len(signals) == 0:
            return {
                'score': -1000.0,
                'win_rate': 0.0,
                'avg_r': 0.0,
                'max_drawdown': 0.0,
                'num_trades': 0,
                'total_pnl': 0.0,
                'params': asdict(params)
            }
        
        backtest = Backtest(df_featured, signals)
        results = backtest.run(max_bars_held=params.exit_minutes)
        
        win_rate = results['win_rate']
        avg_r = results['avg_r_multiple']
        max_dd = abs(results['max_drawdown'])
        num_trades = results['total_trades']
        total_pnl = results['total_pnl']
        
        if num_trades < 3:
            penalty = -500.0
        else:
            penalty = 0.0
        
        score = (
            (win_rate * 100) +
            (avg_r * 50) -
            (max_dd * 0.1) +
            (min(num_trades, 20) * 5) +
            penalty
        )
        
        return {
            'score': score,
            'win_rate': win_rate,
            'avg_r': avg_r,
            'max_drawdown': max_dd,
            'num_trades': num_trades,
            'total_pnl': total_pnl,
            'params': asdict(params)
        }
        
    except Exception as e:
        return {
            'score': -1000.0,
            'win_rate': 0.0,
            'avg_r': 0.0,
            'max_drawdown': 0.0,
            'num_trades': 0,
            'total_pnl': 0.0,
            'params': asdict(params),
            'error': str(e)
        }


def make_walkforward_splits(df: pd.DataFrame, n_splits: int = 4) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Create walk-forward train/test splits.
    
    Args:
        df: Full dataset
        n_splits: Number of splits (default: 4)
    
    Returns:
        List of (train_df, test_df) tuples
    """
    total_bars = len(df)
    bars_per_split = total_bars // (n_splits + 1)
    
    splits = []
    
    for i in range(n_splits):
        train_start = 0
        train_end = (i + 1) * bars_per_split
        test_start = train_end
        test_end = min(test_start + bars_per_split, total_bars)
        
        if test_end <= test_start:
            break
        
        train_df = df.iloc[train_start:train_end].copy().reset_index(drop=True)
        test_df = df.iloc[test_start:test_end].copy().reset_index(drop=True)
        
        splits.append((train_df, test_df))
    
    return splits


def optimize_for_regime(df: pd.DataFrame, regime: str, param_grid: List[StrategyParams]) -> StrategyParams:
    """
    Optimize parameters for specific regime.
    
    Args:
        df: Data (should be filtered to single regime)
        regime: Regime name
        param_grid: Parameter combinations to test
    
    Returns:
        Best StrategyParams for this regime
    """
    best_score = -float('inf')
    best_params = param_grid[0]
    
    for params in param_grid:
        result = evaluate_params(params, df)
        
        if result['score'] > best_score:
            best_score = result['score']
            best_params = params
    
    return best_params


def walkforward_optimize_by_regime(
    df: pd.DataFrame,
    param_grid: List[StrategyParams],
    n_splits: int = 4
) -> Dict:
    """
    Walk-forward optimization with regime-specific parameters.
    
    For each split:
      - Train on segment N
      - Optimize per regime (bull, bear, sideways)
      - Test on segment N+1
    
    Args:
        df: Full historical data
        param_grid: Parameter combinations to test
        n_splits: Number of walk-forward splits
    
    Returns:
        Dict with best params per regime and test results
    """
    splits = make_walkforward_splits(df, n_splits)
    
    regime_best_params = {
        'bull_trend': [],
        'bear_trend': [],
        'sideways': []
    }
    
    test_results = []
    
    for split_idx, (train_df, test_df) in enumerate(splits):
        print(f"\n  Walk-forward split {split_idx + 1}/{len(splits)}")
        print(f"    Train: {len(train_df)} bars, Test: {len(test_df)} bars")
        
        train_df_featured = apply_params_to_data(train_df, param_grid[0])
        
        for regime in ['bull_trend', 'bear_trend', 'sideways']:
            regime_train = train_df_featured[train_df_featured['regime'] == regime].copy()
            regime_train = regime_train.reset_index(drop=True)
            
            if len(regime_train) < 100:
                print(f"      {regime}: insufficient data ({len(regime_train)} bars)")
                continue
            
            print(f"      Optimizing {regime} ({len(regime_train)} bars)...")
            best_params = optimize_for_regime(regime_train, regime, param_grid)
            regime_best_params[regime].append(best_params)
        
        test_df_featured = apply_params_to_data(test_df, param_grid[0])
        
        for regime in ['bull_trend', 'bear_trend', 'sideways']:
            if len(regime_best_params[regime]) == 0:
                continue
            
            regime_test = test_df_featured[test_df_featured['regime'] == regime].copy()
            regime_test = regime_test.reset_index(drop=True)
            
            if len(regime_test) < 50:
                continue
            
            best_params = regime_best_params[regime][-1]
            result = evaluate_params(best_params, regime_test)
            result['regime'] = regime
            result['split'] = split_idx
            test_results.append(result)
    
    final_best_params = {}
    for regime in ['bull_trend', 'bear_trend', 'sideways']:
        if regime_best_params[regime]:
            final_best_params[regime] = regime_best_params[regime][-1]
        else:
            final_best_params[regime] = param_grid[0]
    
    return {
        'best_params_per_regime': final_best_params,
        'test_results': test_results,
        'n_splits': len(splits)
    }


def save_best_params_per_regime(params_dict: Dict[str, StrategyParams], filepath: str = "configs/strategy_params.json"):
    """Save best parameters per regime to JSON."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    serializable = {}
    for regime, params in params_dict.items():
        serializable[regime] = asdict(params)
    
    with open(filepath, 'w') as f:
        json.dump(serializable, f, indent=2)


def load_best_params_per_regime(filepath: str = "configs/strategy_params.json") -> Dict[str, StrategyParams]:
    """Load best parameters per regime from JSON."""
    if not Path(filepath).exists():
        default = StrategyParams()
        return {
            'bull_trend': default,
            'bear_trend': default,
            'sideways': default
        }
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    return {
        regime: StrategyParams(**params)
        for regime, params in data.items()
    }


def save_walkforward_results(results: Dict, filepath: str = "configs/walkforward_results.json"):
    """Save full walk-forward optimization results."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    serializable = results.copy()
    serializable['best_params_per_regime'] = {
        regime: asdict(params)
        for regime, params in results['best_params_per_regime'].items()
    }
    
    with open(filepath, 'w') as f:
        json.dump(serializable, f, indent=2)
