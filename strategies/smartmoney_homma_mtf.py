"""
Smart Money + Homma Multi-Timeframe Strategy

HTF (30m/1h/2h/4h): Detects Smart Money zones (DBR, RBD, etc.)
LTF (3m/5m): Confirms entries with Homma patterns + false break reclaim

Entry Requirements:
1. Price returns to fresh HTF zone
2. LTF Homma pattern fires inside zone
3. False break + reclaim (price trades beyond zone, closes back inside)
"""

from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple
import pandas as pd
import numpy as np

from strategies.smartmoney_zones import SmartMoneyZoneDetector, SmartMoneyZone
from strategies.homma_patterns import HommaPatternDetector, HommaPattern


@dataclass
class MTFSignal:
    index: int
    timestamp: pd.Timestamp
    direction: Literal['long', 'short']
    entry_price: float
    stop_loss: float
    target: float
    reward_risk: float
    zone_pattern: str
    homma_pattern: str
    htf: str
    ltf: str
    spot: float


class SmartMoneyHommaMTF:
    def __init__(
        self,
        htf: str = '1h',
        ltf: str = '5m',
        min_reward_risk: float = 2.0
    ):
        self.htf = htf
        self.ltf = ltf
        self.min_reward_risk = min_reward_risk
        
        self.zone_detector = SmartMoneyZoneDetector(
            min_reward_risk=min_reward_risk
        )
        self.pattern_detector = HommaPatternDetector()
    
    def generate_signals(
        self,
        df_htf: pd.DataFrame,
        df_ltf: pd.DataFrame
    ) -> List[MTFSignal]:
        zones = self.zone_detector.detect_zones(df_htf)
        
        print(f"Detected {len(zones)} fresh {self.htf} zones")
        
        signals = []
        
        for zone in zones:
            zone_signals = self._check_zone_for_entries(zone, df_htf, df_ltf)
            signals.extend(zone_signals)
        
        return signals
    
    def _check_zone_for_entries(
        self,
        zone: SmartMoneyZone,
        df_htf: pd.DataFrame,
        df_ltf: pd.DataFrame
    ) -> List[MTFSignal]:
        zone_time = zone.timestamp
        
        ltf_after_zone = df_ltf[df_ltf['timestamp'] > zone_time].copy()
        
        if len(ltf_after_zone) == 0:
            return []
        
        signals = []
        
        in_zone = False
        false_break_occurred = False
        
        for i in range(len(ltf_after_zone)):
            row = ltf_after_zone.iloc[i]
            
            price_in_zone = (row['low'] <= zone.zone_high and row['high'] >= zone.zone_low)
            
            if not in_zone and price_in_zone:
                in_zone = True
                false_break_occurred = False
            
            if in_zone:
                if zone.zone_type == 'demand':
                    if row['low'] < zone.zone_low and row['close'] >= zone.zone_low:
                        false_break_occurred = True
                else:
                    if row['high'] > zone.zone_high and row['close'] <= zone.zone_high:
                        false_break_occurred = True
                
                if false_break_occurred:
                    patterns = self.pattern_detector.detect_patterns(
                        ltf_after_zone.iloc[:i+2],
                        start_idx=max(0, i - 5)
                    )
                    
                    for pattern in patterns:
                        if abs(pattern.index - i) > 2:
                            continue
                        
                        if zone.zone_type == 'demand' and pattern.direction == 'bullish':
                            signal = MTFSignal(
                                index=i,
                                timestamp=row['timestamp'],
                                direction='long',
                                entry_price=row['close'],
                                stop_loss=zone.stop_loss,
                                target=zone.target,
                                reward_risk=zone.reward_risk,
                                zone_pattern=zone.pattern,
                                homma_pattern=pattern.pattern_type,
                                htf=self.htf,
                                ltf=self.ltf,
                                spot=row['close']
                            )
                            signals.append(signal)
                            return signals
                        
                        elif zone.zone_type == 'supply' and pattern.direction == 'bearish':
                            signal = MTFSignal(
                                index=i,
                                timestamp=row['timestamp'],
                                direction='short',
                                entry_price=row['close'],
                                stop_loss=zone.stop_loss,
                                target=zone.target,
                                reward_risk=zone.reward_risk,
                                zone_pattern=zone.pattern,
                                homma_pattern=pattern.pattern_type,
                                htf=self.htf,
                                ltf=self.ltf,
                                spot=row['close']
                            )
                            signals.append(signal)
                            return signals
                
                if not price_in_zone:
                    in_zone = False
                    false_break_occurred = False
        
        return signals


def resample_to_timeframe(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    df = df.copy()
    df = df.set_index('timestamp')
    
    resampled = df.resample(timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    resampled = resampled.reset_index()
    
    return resampled
