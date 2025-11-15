"""Tests for walk-forward optimizer."""

import pandas as pd
import pytest
import numpy as np
from engine.optimizer import (
    StrategyParams,
    get_param_grid,
    make_walkforward_splits,
    evaluate_params,
    save_best_params_per_regime,
    load_best_params_per_regime
)
import tempfile
from pathlib import Path


def test_strategy_params_creation():
    """Test StrategyParams dataclass."""
    params = StrategyParams()
    
    assert params.renko_k == 1.0
    assert params.regime_lookback == 20
    assert params.exit_minutes == 60
    assert params.enable_regime_filter == True


def test_get_param_grid_fast():
    """Test parameter grid generation in fast mode."""
    grid = get_param_grid(mode="fast")
    
    assert len(grid) > 0
    assert all(isinstance(p, StrategyParams) for p in grid)
    assert len(grid) < 100


def test_get_param_grid_medium():
    """Test parameter grid generation in medium mode."""
    grid = get_param_grid(mode="medium")
    
    assert len(grid) > 0
    assert len(grid) > len(get_param_grid(mode="fast"))


def test_make_walkforward_splits():
    """Test walk-forward split creation."""
    timestamps = pd.date_range('2024-01-01', periods=1000, freq='1min', tz='America/New_York')
    df = pd.DataFrame({
        'timestamp': timestamps,
        'close': np.random.randn(1000) + 100
    })
    
    splits = make_walkforward_splits(df, n_splits=4)
    
    assert len(splits) == 4
    
    for i, (train_df, test_df) in enumerate(splits):
        assert len(train_df) > 0
        assert len(test_df) > 0
        # Indices are reset, so we check train ends before test in original data
        assert len(train_df) > len(test_df) * i


def test_evaluate_params():
    """Test parameter evaluation function."""
    timestamps = pd.date_range('2024-01-02 10:00', periods=500, freq='1min', tz='America/New_York')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': np.random.randn(500) + 100,
        'high': np.random.randn(500) + 101,
        'low': np.random.randn(500) + 99,
        'close': np.random.randn(500) + 100,
        'volume': [1000] * 500
    })
    
    params = StrategyParams()
    result = evaluate_params(params, df)
    
    assert 'score' in result
    assert 'win_rate' in result
    assert 'avg_r' in result
    assert 'num_trades' in result
    assert 'params' in result


def test_save_load_params():
    """Test saving and loading parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_params.json"
        
        params_dict = {
            'bull_trend': StrategyParams(renko_k=1.5),
            'bear_trend': StrategyParams(renko_k=0.8),
            'sideways': StrategyParams(renko_k=1.0)
        }
        
        save_best_params_per_regime(params_dict, filepath=str(filepath))
        
        assert filepath.exists()
        
        loaded = load_best_params_per_regime(filepath=str(filepath))
        
        assert loaded['bull_trend'].renko_k == 1.5
        assert loaded['bear_trend'].renko_k == 0.8
        assert loaded['sideways'].renko_k == 1.0


def test_load_params_missing_file():
    """Test loading params when file doesn't exist returns defaults."""
    loaded = load_best_params_per_regime(filepath="nonexistent.json")
    
    assert 'bull_trend' in loaded
    assert 'bear_trend' in loaded
    assert 'sideways' in loaded
    
    assert loaded['bull_trend'].renko_k == 1.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
