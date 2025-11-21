"""
Strategy Registry for Managing Multiple Trading Strategies.

Provides centralized registration, loading, and execution of trading strategies
based on configuration flags.
"""

import yaml
from typing import List, Dict
import pandas as pd
from pathlib import Path

from engine.base_strategy import BaseStrategy
from engine.strategy import Signal, generate_signals as ict_generate_signals
from engine.vwap_meanrev_strategy import VWAPMeanReversionStrategy


class ICTConfluenceStrategy(BaseStrategy):
    """Wrapper for existing ICT confluence signal generation."""
    
    def __init__(self, config: dict, logger=None):
        super().__init__(config, logger)
        self.enable_ob_filter = config.get('enable_ob_filter', False)
        self.enable_regime_filter = config.get('enable_regime_filter', True)
    
    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """Generate ICT confluence signals using existing logic."""
        return ict_generate_signals(
            df, 
            enable_ob_filter=self.enable_ob_filter,
            enable_regime_filter=self.enable_regime_filter
        )


class StrategyRegistry:
    """
    Registry for managing multiple trading strategies.
    
    Loads strategies from config, instantiates enabled ones, and
    provides unified signal generation across all active strategies.
    """
    
    STRATEGY_CLASSES = {
        'ict_confluence': ICTConfluenceStrategy,
        'vwap_meanrev': VWAPMeanReversionStrategy
    }
    
    def __init__(self, config_path: str = "configs/strategies.yaml", logger=None):
        """
        Initialize strategy registry from config.
        
        Args:
            config_path: Path to strategies configuration file
            logger: Optional logger instance
        """
        self.logger = logger
        self.strategies: Dict[str, BaseStrategy] = {}
        
        self.load_config(config_path)
    
    def load_config(self, config_path: str):
        """Load strategy configuration and instantiate enabled strategies."""
        config_file = Path(config_path)
        
        if not config_file.exists():
            self.log(f"Strategy config not found: {config_path}, using defaults", "warning")
            self._load_default_ict_only()
            return
        
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        strategy_configs = config.get('strategies', {})
        
        for strategy_id, strategy_config in strategy_configs.items():
            if not strategy_config.get('enabled', False):
                self.log(f"Strategy '{strategy_id}' is disabled, skipping")
                continue
            
            if strategy_id not in self.STRATEGY_CLASSES:
                self.log(f"Unknown strategy '{strategy_id}', skipping", "warning")
                continue
            
            strategy_class = self.STRATEGY_CLASSES[strategy_id]
            strategy_instance = strategy_class(strategy_config, logger=self.logger)
            
            self.strategies[strategy_id] = strategy_instance
            self.log(f"Loaded strategy: {strategy_id} ({strategy_config.get('name', strategy_id)})")
        
        if len(self.strategies) == 0:
            self.log("No strategies enabled, falling back to ICT confluence only", "warning")
            self._load_default_ict_only()
    
    def _load_default_ict_only(self):
        """Fallback: Load only ICT confluence strategy with defaults."""
        default_config = {
            'enabled': True,
            'name': 'ICT_CONFLUENCE',
            'enable_ob_filter': False,
            'enable_regime_filter': True
        }
        self.strategies['ict_confluence'] = ICTConfluenceStrategy(default_config, self.logger)
        self.log("Loaded default ICT confluence strategy")
    
    def generate_all_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate signals from all enabled strategies.
        
        Args:
            df: DataFrame with market data
            
        Returns:
            Combined list of signals from all strategies
        """
        all_signals = []
        
        for strategy_id, strategy in self.strategies.items():
            try:
                signals = strategy.generate_signals(df)
                
                for signal in signals:
                    if 'strategy' not in signal.meta:
                        signal.meta['strategy'] = strategy_id
                
                all_signals.extend(signals)
                
                self.log(f"{strategy_id}: Generated {len(signals)} signals")
                
            except Exception as e:
                self.log(f"Error in {strategy_id}: {str(e)}", "error")
                continue
        
        return all_signals
    
    def get_enabled_strategies(self) -> List[str]:
        """Get list of enabled strategy IDs."""
        return list(self.strategies.keys())
    
    def log(self, message: str, level: str = "info"):
        """Helper for logging."""
        if self.logger:
            getattr(self.logger, level)(f"[StrategyRegistry] {message}")
        else:
            print(f"[StrategyRegistry] {message}")
