"""
VWAP Mean-Reversion Strategy Module.

This strategy identifies intraday mean-reversion opportunities based on 
price deviation from VWAP on non-trend days. Uses ATR-based bands and
session filtering for entry signals.

Signal Logic:
- LONG: Price trades below VWAP - band, then closes back toward VWAP
- SHORT: Price trades above VWAP + band, then closes back toward VWAP
- Target: VWAP
- Stop: Recent swing or 2x band extension
"""

import pandas as pd
import numpy as np
from typing import List, Optional
from datetime import time
from engine.base_strategy import BaseStrategy
from engine.strategy import Signal
from engine.vwap_calculator import (
    calculate_session_vwap, 
    calculate_daily_atr,
    calculate_session_range,
    is_non_trend_day
)


class VWAPMeanReversionStrategy(BaseStrategy):
    """
    VWAP-based intraday mean-reversion strategy.
    
    Generates signals when price deviates from VWAP by a configurable ATR
    multiple and shows signs of reverting back.
    """
    
    def __init__(self, config: dict, logger=None):
        super().__init__(config, logger)
        
        self.band_atr_frac = config.get('band_atr_frac', 0.5)
        self.max_session_range_atr_frac = config.get('max_session_range_atr_frac', 1.0)
        self.max_open_ext_atr_frac = config.get('max_open_to_high_atr_frac', 0.7)
        self.min_entry_time = self._parse_time(config.get('min_entry_time', '10:00'))
        self.max_entry_time = self._parse_time(config.get('max_entry_time', '15:30'))
        self.trend_cutoff_time = self._parse_time(config.get('trend_cutoff_time', '11:00'))
        self.max_trades_per_day = config.get('max_trades_per_day', 1)
        self.stop_band_multiplier = config.get('stop_band_multiplier', 2.0)
        
    def _parse_time(self, time_str: str) -> time:
        """Parse time string like '10:00' into datetime.time object."""
        hour, minute = map(int, time_str.split(':'))
        return time(hour, minute)
    
    def generate_signals(self, df: pd.DataFrame) -> List[Signal]:
        """
        Generate VWAP mean-reversion signals.
        
        Args:
            df: DataFrame with timestamp, open, high, low, close, volume columns
            
        Returns:
            List of Signal objects
        """
        if len(df) < 50:
            self.log("Insufficient data for VWAP strategy (need >50 bars)", "warning")
            return []
        
        df = df.copy()
        
        df['vwap'] = calculate_session_vwap(df)
        
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df['intraday_atr'] = df['tr'].rolling(window=14).mean()
        
        df['band'] = self.band_atr_frac * df['intraday_atr']
        df['vwap_upper'] = df['vwap'] + df['band']
        df['vwap_lower'] = df['vwap'] - df['band']
        
        signals = []
        trades_per_day = {}
        
        for i in range(1, len(df)):
            idx = df.index[i]
            prev_idx = df.index[i-1]
            row = df.loc[idx]
            prev_row = df.loc[prev_idx]
            
            if pd.isna(row['vwap']) or pd.isna(row['intraday_atr']):
                continue
            
            timestamp = pd.to_datetime(row['timestamp'])
            current_time = timestamp.time()
            current_date = timestamp.date()
            
            if current_time < self.min_entry_time or current_time > self.max_entry_time:
                continue
            
            if current_date in trades_per_day:
                if trades_per_day[current_date] >= self.max_trades_per_day:
                    continue
            
            long_signal = self._check_long_setup(df, i, row, prev_row)
            if long_signal:
                signals.append(long_signal)
                trades_per_day[current_date] = trades_per_day.get(current_date, 0) + 1
                continue
            
            short_signal = self._check_short_setup(df, i, row, prev_row)
            if short_signal:
                signals.append(short_signal)
                trades_per_day[current_date] = trades_per_day.get(current_date, 0) + 1
        
        self.log(f"Generated {len(signals)} VWAP mean-reversion signals")
        return signals
    
    def _check_long_setup(self, df: pd.DataFrame, i: int, row: pd.Series, 
                          prev_row: pd.Series) -> Optional[Signal]:
        """
        Check for LONG mean-reversion setup.
        
        Conditions:
        - Previous bar traded below VWAP - band
        - Current bar closes back up toward VWAP
        """
        idx = df.index[i]
        
        if prev_row['low'] < prev_row['vwap_lower']:
            if row['close'] > prev_row['close'] and row['close'] > row['vwap_lower']:
                
                swing_low = self._find_recent_swing_low(df, i, lookback=10)
                stop_level = min(
                    swing_low,
                    row['vwap'] - (self.stop_band_multiplier * row['band'])
                )
                
                return Signal(
                    index=idx,
                    timestamp=pd.to_datetime(row['timestamp']),
                    direction='long',
                    spot=row['close'],
                    target=row['vwap'],
                    source_session='vwap_meanrev',
                    meta={
                        'strategy': 'VWAP_MEANREV',
                        'vwap': row['vwap'],
                        'band': row['band'],
                        'deviation': row['close'] - row['vwap'],
                        'stop': stop_level,
                        'intraday_atr': row['intraday_atr']
                    }
                )
        return None
    
    def _check_short_setup(self, df: pd.DataFrame, i: int, row: pd.Series,
                           prev_row: pd.Series) -> Optional[Signal]:
        """
        Check for SHORT mean-reversion setup.
        
        Conditions:
        - Previous bar traded above VWAP + band
        - Current bar closes back down toward VWAP
        """
        idx = df.index[i]
        
        if prev_row['high'] > prev_row['vwap_upper']:
            if row['close'] < prev_row['close'] and row['close'] < row['vwap_upper']:
                
                swing_high = self._find_recent_swing_high(df, i, lookback=10)
                stop_level = max(
                    swing_high,
                    row['vwap'] + (self.stop_band_multiplier * row['band'])
                )
                
                return Signal(
                    index=idx,
                    timestamp=pd.to_datetime(row['timestamp']),
                    direction='short',
                    spot=row['close'],
                    target=row['vwap'],
                    source_session='vwap_meanrev',
                    meta={
                        'strategy': 'VWAP_MEANREV',
                        'vwap': row['vwap'],
                        'band': row['band'],
                        'deviation': row['close'] - row['vwap'],
                        'stop': stop_level,
                        'intraday_atr': row['intraday_atr']
                    }
                )
        return None
    
    def _find_recent_swing_low(self, df: pd.DataFrame, current_i: int, 
                               lookback: int = 10) -> float:
        """Find the lowest low in the recent swing leg."""
        start_i = max(0, current_i - lookback)
        window = df.iloc[start_i:current_i]
        return window['low'].min() if len(window) > 0 else df.iloc[current_i]['low']
    
    def _find_recent_swing_high(self, df: pd.DataFrame, current_i: int,
                                lookback: int = 10) -> float:
        """Find the highest high in the recent swing leg."""
        start_i = max(0, current_i - lookback)
        window = df.iloc[start_i:current_i]
        return window['high'].max() if len(window) > 0 else df.iloc[current_i]['high']
