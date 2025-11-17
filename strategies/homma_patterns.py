"""
Homma Candlestick Pattern Recognition

Detects Japanese candlestick reversal patterns:
- Hammer / Tonkachi (bullish)
- Shooting Star (bearish)
- Bullish / Bearish Engulfing
- Harami + breakout
- Doji + follow-through
"""

from dataclasses import dataclass
from typing import List, Literal, Optional
import pandas as pd
import numpy as np


@dataclass
class HommaPattern:
    index: int
    pattern_type: Literal['hammer', 'shooting_star', 'bullish_engulfing', 'bearish_engulfing', 
                           'bullish_harami', 'bearish_harami', 'doji_bullish', 'doji_bearish']
    direction: Literal['bullish', 'bearish']
    timestamp: pd.Timestamp
    price: float
    strength: float


class HommaPatternDetector:
    def __init__(
        self,
        doji_body_ratio: float = 0.1,
        hammer_wick_ratio: float = 2.0,
        engulfing_min_ratio: float = 1.0,
        follow_through_min_body: float = 1.5
    ):
        self.doji_body_ratio = doji_body_ratio
        self.hammer_wick_ratio = hammer_wick_ratio
        self.engulfing_min_ratio = engulfing_min_ratio
        self.follow_through_min_body = follow_through_min_body
    
    def detect_patterns(self, df: pd.DataFrame, start_idx: int = 0) -> List[HommaPattern]:
        patterns = []
        
        df = df.copy()
        df['body'] = abs(df['close'] - df['open'])
        df['upper_wick'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_wick'] = df[['close', 'open']].min(axis=1) - df['low']
        df['range'] = df['high'] - df['low']
        df['avg_body'] = df['body'].rolling(20, min_periods=1).mean()
        
        for i in range(max(start_idx, 2), len(df) - 1):
            hammer = self._detect_hammer(df, i)
            if hammer:
                patterns.append(hammer)
                continue
            
            shooting_star = self._detect_shooting_star(df, i)
            if shooting_star:
                patterns.append(shooting_star)
                continue
            
            if i >= 1:
                engulf_bull = self._detect_bullish_engulfing(df, i)
                if engulf_bull:
                    patterns.append(engulf_bull)
                    continue
                
                engulf_bear = self._detect_bearish_engulfing(df, i)
                if engulf_bear:
                    patterns.append(engulf_bear)
                    continue
                
                harami_bull = self._detect_bullish_harami(df, i)
                if harami_bull:
                    patterns.append(harami_bull)
                    continue
                
                harami_bear = self._detect_bearish_harami(df, i)
                if harami_bear:
                    patterns.append(harami_bear)
                    continue
            
            doji_bull = self._detect_doji_bullish(df, i)
            if doji_bull:
                patterns.append(doji_bull)
                continue
            
            doji_bear = self._detect_doji_bearish(df, i)
            if doji_bear:
                patterns.append(doji_bear)
        
        return patterns
    
    def _detect_hammer(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        row = df.iloc[i]
        
        if row['range'] == 0:
            return None
        
        body_position = (min(row['open'], row['close']) - row['low']) / row['range']
        
        if body_position < 0.7:
            return None
        
        if row['lower_wick'] < self.hammer_wick_ratio * row['body']:
            return None
        
        if row['upper_wick'] > row['body'] * 0.3:
            return None
        
        next_row = df.iloc[i + 1]
        if next_row['close'] <= row['close']:
            return None
        
        strength = row['lower_wick'] / row['body'] if row['body'] > 0 else 0
        
        return HommaPattern(
            index=i,
            pattern_type='hammer',
            direction='bullish',
            timestamp=row['timestamp'],
            price=row['close'],
            strength=strength
        )
    
    def _detect_shooting_star(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        row = df.iloc[i]
        
        if row['range'] == 0:
            return None
        
        body_position = (row['high'] - max(row['open'], row['close'])) / row['range']
        
        if body_position < 0.7:
            return None
        
        if row['upper_wick'] < self.hammer_wick_ratio * row['body']:
            return None
        
        if row['lower_wick'] > row['body'] * 0.3:
            return None
        
        next_row = df.iloc[i + 1]
        if next_row['close'] >= row['close']:
            return None
        
        strength = row['upper_wick'] / row['body'] if row['body'] > 0 else 0
        
        return HommaPattern(
            index=i,
            pattern_type='shooting_star',
            direction='bearish',
            timestamp=row['timestamp'],
            price=row['close'],
            strength=strength
        )
    
    def _detect_bullish_engulfing(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        
        if prev['close'] >= prev['open']:
            return None
        
        if curr['close'] <= curr['open']:
            return None
        
        if curr['open'] >= prev['close']:
            return None
        
        if curr['close'] <= prev['open']:
            return None
        
        ratio = curr['body'] / prev['body'] if prev['body'] > 0 else 0
        
        if ratio < self.engulfing_min_ratio:
            return None
        
        return HommaPattern(
            index=i,
            pattern_type='bullish_engulfing',
            direction='bullish',
            timestamp=curr['timestamp'],
            price=curr['close'],
            strength=ratio
        )
    
    def _detect_bearish_engulfing(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        
        if prev['close'] <= prev['open']:
            return None
        
        if curr['close'] >= curr['open']:
            return None
        
        if curr['open'] <= prev['close']:
            return None
        
        if curr['close'] >= prev['open']:
            return None
        
        ratio = curr['body'] / prev['body'] if prev['body'] > 0 else 0
        
        if ratio < self.engulfing_min_ratio:
            return None
        
        return HommaPattern(
            index=i,
            pattern_type='bearish_engulfing',
            direction='bearish',
            timestamp=curr['timestamp'],
            price=curr['close'],
            strength=ratio
        )
    
    def _detect_bullish_harami(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        if i < 1 or i >= len(df) - 1:
            return None
        
        mother = df.iloc[i - 1]
        inside = df.iloc[i]
        breakout = df.iloc[i + 1]
        
        if mother['close'] >= mother['open']:
            return None
        
        if inside['high'] > mother['high'] or inside['low'] < mother['low']:
            return None
        
        if breakout['close'] <= mother['high']:
            return None
        
        return HommaPattern(
            index=i,
            pattern_type='bullish_harami',
            direction='bullish',
            timestamp=inside['timestamp'],
            price=inside['close'],
            strength=1.0
        )
    
    def _detect_bearish_harami(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        if i < 1 or i >= len(df) - 1:
            return None
        
        mother = df.iloc[i - 1]
        inside = df.iloc[i]
        breakout = df.iloc[i + 1]
        
        if mother['close'] <= mother['open']:
            return None
        
        if inside['high'] > mother['high'] or inside['low'] < mother['low']:
            return None
        
        if breakout['close'] >= mother['low']:
            return None
        
        return HommaPattern(
            index=i,
            pattern_type='bearish_harami',
            direction='bearish',
            timestamp=inside['timestamp'],
            price=inside['close'],
            strength=1.0
        )
    
    def _detect_doji_bullish(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        if i >= len(df) - 1:
            return None
        
        doji = df.iloc[i]
        follow = df.iloc[i + 1]
        
        if doji['range'] == 0:
            return None
        
        if doji['body'] / doji['range'] > self.doji_body_ratio:
            return None
        
        if follow['close'] <= follow['open']:
            return None
        
        if follow['body'] < self.follow_through_min_body * doji['avg_body']:
            return None
        
        return HommaPattern(
            index=i,
            pattern_type='doji_bullish',
            direction='bullish',
            timestamp=doji['timestamp'],
            price=doji['close'],
            strength=follow['body'] / doji['avg_body']
        )
    
    def _detect_doji_bearish(self, df: pd.DataFrame, i: int) -> Optional[HommaPattern]:
        if i >= len(df) - 1:
            return None
        
        doji = df.iloc[i]
        follow = df.iloc[i + 1]
        
        if doji['range'] == 0:
            return None
        
        if doji['body'] / doji['range'] > self.doji_body_ratio:
            return None
        
        if follow['close'] >= follow['open']:
            return None
        
        if follow['body'] < self.follow_through_min_body * doji['avg_body']:
            return None
        
        return HommaPattern(
            index=i,
            pattern_type='doji_bearish',
            direction='bearish',
            timestamp=doji['timestamp'],
            price=doji['close'],
            strength=follow['body'] / doji['avg_body']
        )
