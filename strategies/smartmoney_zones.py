"""
Smart Money Supply & Demand Zone Detection

Detects institutional footprints based on:
- DBR (Drop-Base-Rally) → Demand
- RBD (Rally-Base-Drop) → Supply
- RBR (Rally-Base-Rally) → Demand continuation
- DBD (Drop-Base-Drop) → Supply continuation

4-Pillar Validation:
1. Impulse strength (large clean candles leaving zone)
2. Freshness (zone not revisited)
3. Break of structure (BoS)
4. Reward:Risk ≥ 2:1
"""

from dataclasses import dataclass
from typing import List, Literal
import pandas as pd
import numpy as np


@dataclass
class SmartMoneyZone:
    index: int
    zone_type: Literal['demand', 'supply']
    pattern: Literal['DBR', 'RBD', 'RBR', 'DBD']
    zone_high: float
    zone_low: float
    entry_price: float
    stop_loss: float
    target: float
    reward_risk: float
    impulse_strength: float
    timestamp: pd.Timestamp
    touched: bool = False


class SmartMoneyZoneDetector:
    def __init__(
        self,
        base_candles_max: int = 3,
        impulse_body_multiplier: float = 1.5,
        wick_body_ratio_max: float = 0.5,
        lookback_avg: int = 20,
        min_reward_risk: float = 2.0,
        structure_lookback: int = 50
    ):
        self.base_candles_max = base_candles_max
        self.impulse_body_multiplier = impulse_body_multiplier
        self.wick_body_ratio_max = wick_body_ratio_max
        self.lookback_avg = lookback_avg
        self.min_reward_risk = min_reward_risk
        self.structure_lookback = structure_lookback
    
    def detect_zones(self, df: pd.DataFrame) -> List[SmartMoneyZone]:
        zones = []
        
        df['body'] = abs(df['close'] - df['open'])
        df['upper_wick'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_wick'] = df[['close', 'open']].min(axis=1) - df['low']
        df['total_wick'] = df['upper_wick'] + df['lower_wick']
        df['avg_body'] = df['body'].rolling(self.lookback_avg, min_periods=1).mean()
        
        i = self.structure_lookback
        while i < len(df) - 10:
            dbr_zone = self._detect_dbr(df, i)
            if dbr_zone:
                zones.append(dbr_zone)
                i += 5
                continue
            
            rbd_zone = self._detect_rbd(df, i)
            if rbd_zone:
                zones.append(rbd_zone)
                i += 5
                continue
            
            rbr_zone = self._detect_rbr(df, i)
            if rbr_zone:
                zones.append(rbr_zone)
                i += 5
                continue
            
            dbd_zone = self._detect_dbd(df, i)
            if dbd_zone:
                zones.append(dbd_zone)
                i += 5
                continue
            
            i += 1
        
        self._mark_touched_zones(df, zones)
        
        return [z for z in zones if not z.touched]
    
    def _detect_dbr(self, df: pd.DataFrame, i: int):
        if i < 10 or i >= len(df) - 5:
            return None
        
        drop_start = i - 5
        base_start = i
        base_end = min(i + self.base_candles_max, len(df) - 1)
        rally_start = base_end + 1
        rally_end = min(rally_start + 5, len(df) - 1)
        
        drop = df.iloc[drop_start:base_start]
        if len(drop) == 0 or drop['close'].iloc[-1] >= drop['close'].iloc[0]:
            return None
        
        base = df.iloc[base_start:base_end+1]
        if len(base) == 0:
            return None
        base_range = base['high'].max() - base['low'].min()
        base_high = base['high'].max()
        base_low = base['low'].min()
        
        rally = df.iloc[rally_start:rally_end+1]
        if len(rally) == 0 or rally['close'].iloc[-1] <= rally['close'].iloc[0]:
            return None
        
        if not self._check_impulse_strength(rally, 'bullish'):
            return None
        
        impulse_strength = self._calculate_impulse_strength(rally, 'bullish')
        
        if not self._check_break_of_structure(df, i, 'bullish'):
            return None
        
        entry = base_high
        stop = base_low - base_range * 0.1
        target = self._find_target(df, rally_end, 'bullish')
        
        if target is None:
            return None
        
        risk = entry - stop
        reward = target - entry
        
        if risk <= 0:
            return None
        
        rr = reward / risk
        
        if rr < self.min_reward_risk:
            return None
        
        return SmartMoneyZone(
            index=base_start,
            zone_type='demand',
            pattern='DBR',
            zone_high=base_high,
            zone_low=base_low,
            entry_price=entry,
            stop_loss=stop,
            target=target,
            reward_risk=rr,
            impulse_strength=impulse_strength,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _detect_rbd(self, df: pd.DataFrame, i: int):
        if i < 10 or i >= len(df) - 5:
            return None
        
        rally_start = i - 5
        base_start = i
        base_end = min(i + self.base_candles_max, len(df) - 1)
        drop_start = base_end + 1
        drop_end = min(drop_start + 5, len(df) - 1)
        
        rally = df.iloc[rally_start:base_start]
        if len(rally) == 0 or rally['close'].iloc[-1] <= rally['close'].iloc[0]:
            return None
        
        base = df.iloc[base_start:base_end+1]
        if len(base) == 0:
            return None
        base_range = base['high'].max() - base['low'].min()
        base_high = base['high'].max()
        base_low = base['low'].min()
        
        drop = df.iloc[drop_start:drop_end+1]
        if len(drop) == 0 or drop['close'].iloc[-1] >= drop['close'].iloc[0]:
            return None
        
        if not self._check_impulse_strength(drop, 'bearish'):
            return None
        
        impulse_strength = self._calculate_impulse_strength(drop, 'bearish')
        
        if not self._check_break_of_structure(df, i, 'bearish'):
            return None
        
        entry = base_low
        stop = base_high + base_range * 0.1
        target = self._find_target(df, drop_end, 'bearish')
        
        if target is None:
            return None
        
        risk = stop - entry
        reward = entry - target
        
        if risk <= 0:
            return None
        
        rr = reward / risk
        
        if rr < self.min_reward_risk:
            return None
        
        return SmartMoneyZone(
            index=base_start,
            zone_type='supply',
            pattern='RBD',
            zone_high=base_high,
            zone_low=base_low,
            entry_price=entry,
            stop_loss=stop,
            target=target,
            reward_risk=rr,
            impulse_strength=impulse_strength,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _detect_rbr(self, df: pd.DataFrame, i: int):
        if i < 10 or i >= len(df) - 5:
            return None
        
        rally1_start = i - 5
        base_start = i
        base_end = min(i + self.base_candles_max, len(df) - 1)
        rally2_start = base_end + 1
        rally2_end = min(rally2_start + 5, len(df) - 1)
        
        rally1 = df.iloc[rally1_start:base_start]
        if len(rally1) == 0 or rally1['close'].iloc[-1] <= rally1['close'].iloc[0]:
            return None
        
        base = df.iloc[base_start:base_end+1]
        if len(base) == 0:
            return None
        base_high = base['high'].max()
        base_low = base['low'].min()
        base_range = base_high - base_low
        
        rally2 = df.iloc[rally2_start:rally2_end+1]
        if len(rally2) == 0 or rally2['close'].iloc[-1] <= rally2['close'].iloc[0]:
            return None
        
        if not self._check_impulse_strength(rally2, 'bullish'):
            return None
        
        impulse_strength = self._calculate_impulse_strength(rally2, 'bullish')
        
        entry = base_high
        stop = base_low - base_range * 0.1
        target = self._find_target(df, rally2_end, 'bullish')
        
        if target is None:
            return None
        
        risk = entry - stop
        reward = target - entry
        
        if risk <= 0:
            return None
        
        rr = reward / risk
        
        if rr < self.min_reward_risk:
            return None
        
        return SmartMoneyZone(
            index=base_start,
            zone_type='demand',
            pattern='RBR',
            zone_high=base_high,
            zone_low=base_low,
            entry_price=entry,
            stop_loss=stop,
            target=target,
            reward_risk=rr,
            impulse_strength=impulse_strength,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _detect_dbd(self, df: pd.DataFrame, i: int):
        if i < 10 or i >= len(df) - 5:
            return None
        
        drop1_start = i - 5
        base_start = i
        base_end = min(i + self.base_candles_max, len(df) - 1)
        drop2_start = base_end + 1
        drop2_end = min(drop2_start + 5, len(df) - 1)
        
        drop1 = df.iloc[drop1_start:base_start]
        if len(drop1) == 0 or drop1['close'].iloc[-1] >= drop1['close'].iloc[0]:
            return None
        
        base = df.iloc[base_start:base_end+1]
        if len(base) == 0:
            return None
        base_high = base['high'].max()
        base_low = base['low'].min()
        base_range = base_high - base_low
        
        drop2 = df.iloc[drop2_start:drop2_end+1]
        if len(drop2) == 0 or drop2['close'].iloc[-1] >= drop2['close'].iloc[0]:
            return None
        
        if not self._check_impulse_strength(drop2, 'bearish'):
            return None
        
        impulse_strength = self._calculate_impulse_strength(drop2, 'bearish')
        
        entry = base_low
        stop = base_high + base_range * 0.1
        target = self._find_target(df, drop2_end, 'bearish')
        
        if target is None:
            return None
        
        risk = stop - entry
        reward = entry - target
        
        if risk <= 0:
            return None
        
        rr = reward / risk
        
        if rr < self.min_reward_risk:
            return None
        
        return SmartMoneyZone(
            index=base_start,
            zone_type='supply',
            pattern='DBD',
            zone_high=base_high,
            zone_low=base_low,
            entry_price=entry,
            stop_loss=stop,
            target=target,
            reward_risk=rr,
            impulse_strength=impulse_strength,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _check_impulse_strength(self, impulse_bars: pd.DataFrame, direction: str) -> bool:
        if len(impulse_bars) == 0:
            return False
        
        for idx, row in impulse_bars.iterrows():
            body = row['body']
            avg_body = row['avg_body']
            total_wick = row['total_wick']
            
            if body < self.impulse_body_multiplier * avg_body:
                return False
            
            if body == 0:
                return False
            
            if total_wick / body > self.wick_body_ratio_max:
                return False
            
            if direction == 'bullish' and row['close'] < row['open']:
                return False
            if direction == 'bearish' and row['close'] > row['open']:
                return False
        
        return True
    
    def _calculate_impulse_strength(self, impulse_bars: pd.DataFrame, direction: str) -> float:
        if len(impulse_bars) == 0:
            return 0.0
        
        avg_body_ratio = (impulse_bars['body'] / impulse_bars['avg_body']).mean()
        avg_wick_ratio = (impulse_bars['total_wick'] / impulse_bars['body']).mean()
        
        strength = avg_body_ratio * (1 - avg_wick_ratio)
        return strength
    
    def _check_break_of_structure(self, df: pd.DataFrame, base_idx: int, direction: str) -> bool:
        lookback = df.iloc[max(0, base_idx - self.structure_lookback):base_idx]
        
        if len(lookback) < 10:
            return False
        
        if direction == 'bullish':
            recent_high = lookback['high'].max()
            impulse_high = df.iloc[base_idx:min(base_idx + 10, len(df))]['high'].max()
            return impulse_high > recent_high
        else:
            recent_low = lookback['low'].min()
            impulse_low = df.iloc[base_idx:min(base_idx + 10, len(df))]['low'].min()
            return impulse_low < recent_low
    
    def _find_target(self, df: pd.DataFrame, impulse_end: int, direction: str):
        future = df.iloc[impulse_end:min(impulse_end + self.structure_lookback, len(df))]
        
        if len(future) < 10:
            return None
        
        if direction == 'bullish':
            swing_highs = []
            for i in range(5, len(future) - 5):
                if future.iloc[i]['high'] > future.iloc[i-5:i]['high'].max() and \
                   future.iloc[i]['high'] > future.iloc[i+1:i+6]['high'].max():
                    swing_highs.append(future.iloc[i]['high'])
            
            if swing_highs:
                return min(swing_highs)
            else:
                return future['high'].max()
        
        else:
            swing_lows = []
            for i in range(5, len(future) - 5):
                if future.iloc[i]['low'] < future.iloc[i-5:i]['low'].min() and \
                   future.iloc[i]['low'] < future.iloc[i+1:i+6]['low'].min():
                    swing_lows.append(future.iloc[i]['low'])
            
            if swing_lows:
                return max(swing_lows)
            else:
                return future['low'].min()
    
    def _mark_touched_zones(self, df: pd.DataFrame, zones: List[SmartMoneyZone]):
        for zone in zones:
            future = df.iloc[zone.index + 10:]
            
            for idx, row in future.iterrows():
                if row['low'] <= zone.zone_high and row['high'] >= zone.zone_low:
                    zone.touched = True
                    break
