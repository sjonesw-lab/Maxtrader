"""
Base Strategy Interface for Pluggable Trading Strategies.

This module defines the abstract base class that all trading strategies must implement,
enabling clean separation of signal generation logic.
"""

from abc import ABC, abstractmethod
from typing import List
import pandas as pd
from engine.strategy import Signal


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    All strategies must implement generate_signals() which takes market data
    and returns a list of Signal objects.
    """
    
    def __init__(self, config: dict, logger=None):
        """
        Initialize strategy with configuration.
        
        Args:
            config: Strategy-specific configuration dictionary
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger
        self.name = self.__class__.__name__
    
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate trading signals from market data.
        
        Args:
            df: DataFrame with OHLCV data and any pre-computed features
            
        Returns:
            List of Signal objects
        """
        pass
    
    def log(self, message: str, level: str = "info"):
        """Helper for logging."""
        if self.logger:
            getattr(self.logger, level)(f"[{self.name}] {message}")
        else:
            print(f"[{self.name}] {message}")
