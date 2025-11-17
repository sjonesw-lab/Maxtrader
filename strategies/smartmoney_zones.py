"""
Smart Money Supply & Demand Zone Detection

Detects institutional footprints based on:
- DBR (Drop-Base-Rally) → Demand
- RBD (Rally-Base-Drop) → Supply  
- RBR (Rally-Base-Rally) → Demand continuation
- DBD (Drop-Base-Drop) → Supply continuation

Simplified 3-Pillar Validation:
1. Clear pattern structure (drop/base/rally with minimum moves)
2. Freshness (zone not revisited before entry)
3. Reward:Risk ≥ 2:1
"""

from dataclasses import dataclass
from typing import List, Literal, Optional
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
        min_impulse_pct: float = 0.003,
        min_reward_risk: float = 2.0,
        structure_lookback: int = 30
    ):
        self.base_candles_max = base_candles_max
        self.min_impulse_pct = min_impulse_pct
        self.min_reward_risk = min_reward_risk
        self.structure_lookback = structure_lookback
    
    def detect_zones(self, df: pd.DataFrame, debug: bool = False) -> List[SmartMoneyZone]:
        zones = []
        
        df = df.copy()
        df['body'] = abs(df['close'] - df['open'])
        
        i = self.structure_lookback
        while i < len(df) - 15:
            dbr_zone = self._detect_dbr(df, i)
            if dbr_zone:
                if debug:
                    print(f"Found DBR at {i}: {dbr_zone.pattern}, RR={dbr_zone.reward_risk:.2f}")
                zones.append(dbr_zone)
                i += 10
                continue
            
            rbd_zone = self._detect_rbd(df, i)
            if rbd_zone:
                if debug:
                    print(f"Found RBD at {i}: {rbd_zone.pattern}, RR={rbd_zone.reward_risk:.2f}")
                zones.append(rbd_zone)
                i += 10
                continue
            
            rbr_zone = self._detect_rbr(df, i)
            if rbr_zone:
                if debug:
                    print(f"Found RBR at {i}: {rbd_zone.pattern}, RR={rbr_zone.reward_risk:.2f}")
                zones.append(rbr_zone)
                i += 10
                continue
            
            dbd_zone = self._detect_dbd(df, i)
            if dbd_zone:
                if debug:
                    print(f"Found DBD at {i}: {dbd_zone.pattern}, RR={dbd_zone.reward_risk:.2f}")
                zones.append(dbd_zone)
                i += 10
                continue
            
            i += 1
        
        self._mark_touched_zones(df, zones)
        
        return [z for z in zones if not z.touched]
    
    def _detect_dbr(self, df: pd.DataFrame, i: int) -> Optional[SmartMoneyZone]:
        if i < 10 or i >= len(df) - 10:
            return None
        
        drop_start = i - 8
        base_start = i
        base_end = min(i + self.base_candles_max - 1, len(df) - 1)
        rally_start = base_end + 1
        rally_end = min(rally_start + 8, len(df) - 1)
        
        drop = df.iloc[drop_start:base_start]
        base = df.iloc[base_start:base_end+1]
        rally = df.iloc[rally_start:rally_end+1]
        
        if len(drop) < 3 or len(base) < 1 or len(rally) < 3:
            return None
        
        drop_move = (drop['close'].iloc[0] - drop['close'].iloc[-1]) / drop['close'].iloc[0]
        if drop_move < self.min_impulse_pct:
            return None
        
        base_high = base['high'].max()
        base_low = base['low'].min()
        base_mid = (base_high + base_low) / 2
        
        rally_move = (rally['close'].iloc[-1] - rally['close'].iloc[0]) / rally['close'].iloc[0]
        if rally_move < self.min_impulse_pct:
            return None
        
        entry = base_high
        stop = base_low - (base_high - base_low) * 0.2
        
        target = self._find_target(df, rally_end, 'bullish')
        if target is None:
            target = entry * 1.01
        
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
            impulse_strength=rally_move,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _detect_rbd(self, df: pd.DataFrame, i: int) -> Optional[SmartMoneyZone]:
        if i < 10 or i >= len(df) - 10:
            return None
        
        rally_start = i - 8
        base_start = i
        base_end = min(i + self.base_candles_max - 1, len(df) - 1)
        drop_start = base_end + 1
        drop_end = min(drop_start + 8, len(df) - 1)
        
        rally = df.iloc[rally_start:base_start]
        base = df.iloc[base_start:base_end+1]
        drop = df.iloc[drop_start:drop_end+1]
        
        if len(rally) < 3 or len(base) < 1 or len(drop) < 3:
            return None
        
        rally_move = (rally['close'].iloc[-1] - rally['close'].iloc[0]) / rally['close'].iloc[0]
        if rally_move < self.min_impulse_pct:
            return None
        
        base_high = base['high'].max()
        base_low = base['low'].min()
        
        drop_move = (drop['close'].iloc[0] - drop['close'].iloc[-1]) / drop['close'].iloc[0]
        if drop_move < self.min_impulse_pct:
            return None
        
        entry = base_low
        stop = base_high + (base_high - base_low) * 0.2
        
        target = self._find_target(df, drop_end, 'bearish')
        if target is None:
            target = entry * 0.99
        
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
            impulse_strength=drop_move,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _detect_rbr(self, df: pd.DataFrame, i: int) -> Optional[SmartMoneyZone]:
        if i < 10 or i >= len(df) - 10:
            return None
        
        rally1_start = i - 8
        base_start = i
        base_end = min(i + self.base_candles_max - 1, len(df) - 1)
        rally2_start = base_end + 1
        rally2_end = min(rally2_start + 8, len(df) - 1)
        
        rally1 = df.iloc[rally1_start:base_start]
        base = df.iloc[base_start:base_end+1]
        rally2 = df.iloc[rally2_start:rally2_end+1]
        
        if len(rally1) < 3 or len(base) < 1 or len(rally2) < 3:
            return None
        
        rally1_move = (rally1['close'].iloc[-1] - rally1['close'].iloc[0]) / rally1['close'].iloc[0]
        if rally1_move < self.min_impulse_pct:
            return None
        
        base_high = base['high'].max()
        base_low = base['low'].min()
        
        rally2_move = (rally2['close'].iloc[-1] - rally2['close'].iloc[0]) / rally2['close'].iloc[0]
        if rally2_move < self.min_impulse_pct:
            return None
        
        entry = base_high
        stop = base_low - (base_high - base_low) * 0.2
        
        target = self._find_target(df, rally2_end, 'bullish')
        if target is None:
            target = entry * 1.01
        
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
            impulse_strength=rally2_move,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _detect_dbd(self, df: pd.DataFrame, i: int) -> Optional[SmartMoneyZone]:
        if i < 10 or i >= len(df) - 10:
            return None
        
        drop1_start = i - 8
        base_start = i
        base_end = min(i + self.base_candles_max - 1, len(df) - 1)
        drop2_start = base_end + 1
        drop2_end = min(drop2_start + 8, len(df) - 1)
        
        drop1 = df.iloc[drop1_start:base_start]
        base = df.iloc[base_start:base_end+1]
        drop2 = df.iloc[drop2_start:drop2_end+1]
        
        if len(drop1) < 3 or len(base) < 1 or len(drop2) < 3:
            return None
        
        drop1_move = (drop1['close'].iloc[0] - drop1['close'].iloc[-1]) / drop1['close'].iloc[0]
        if drop1_move < self.min_impulse_pct:
            return None
        
        base_high = base['high'].max()
        base_low = base['low'].min()
        
        drop2_move = (drop2['close'].iloc[0] - drop2['close'].iloc[-1]) / drop2['close'].iloc[0]
        if drop2_move < self.min_impulse_pct:
            return None
        
        entry = base_low
        stop = base_high + (base_high - base_low) * 0.2
        
        target = self._find_target(df, drop2_end, 'bearish')
        if target is None:
            target = entry * 0.99
        
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
            impulse_strength=drop2_move,
            timestamp=df.iloc[base_start]['timestamp']
        )
    
    def _find_target(self, df: pd.DataFrame, impulse_end: int, direction: str) -> Optional[float]:
        future = df.iloc[impulse_end:min(impulse_end + self.structure_lookback, len(df))]
        
        if len(future) < 5:
            return None
        
        if direction == 'bullish':
            swing_highs = []
            for i in range(2, len(future) - 2):
                if future.iloc[i]['high'] > future.iloc[i-2:i]['high'].max() and \
                   future.iloc[i]['high'] > future.iloc[i+1:min(i+3, len(future))]['high'].max():
                    swing_highs.append(future.iloc[i]['high'])
            
            if swing_highs:
                return swing_highs[0]
            else:
                return future['high'].max()
        
        else:
            swing_lows = []
            for i in range(2, len(future) - 2):
                if future.iloc[i]['low'] < future.iloc[i-2:i]['low'].min() and \
                   future.iloc[i]['low'] < future.iloc[i+1:min(i+3, len(future))]['low'].min():
                    swing_lows.append(future.iloc[i]['low'])
            
            if swing_lows:
                return swing_lows[0]
            else:
                return future['low'].min()
    
    def _mark_touched_zones(self, df: pd.DataFrame, zones: List[SmartMoneyZone]):
        for zone in zones:
            future = df.iloc[zone.index + 15:]
            
            for idx, row in future.iterrows():
                if row['low'] <= zone.zone_high and row['high'] >= zone.zone_low:
                    zone.touched = True
                    break
