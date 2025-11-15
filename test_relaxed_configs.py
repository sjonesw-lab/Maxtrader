"""
Test relaxed signal configurations to increase frequency.
Compares different confluence requirements.
"""

import warnings
warnings.filterwarnings('ignore')

from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_liquidity_sweeps, detect_displacement, detect_fvgs, detect_mss
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy import Signal, in_ny_open_window, find_target
from engine.backtest import Backtest
import pandas as pd


def generate_signals_config_A(df: pd.DataFrame) -> list:
    """
    Config A: Lower displacement threshold to 1.0x ATR (from 1.2x)
    Keep all other filters the same
    """
    signals = []
    
    for idx in df.index:
        row = df.loc[idx]
        
        if not in_ny_open_window(row['timestamp']):
            continue
        
        # Use 1.0x ATR threshold instead of 1.2x
        displacement_bullish = (row['atr'] > 0) and (abs(row['close'] - row['open']) > 1.0 * row['atr'])
        displacement_bearish = displacement_bullish  # Same threshold
        
        bullish_setup = (
            row['sweep_bullish'] and
            displacement_bullish and
            row['fvg_bullish'] and
            row['mss_bullish'] and
            row['regime'] in ['bull_trend', 'sideways']
        )
        
        if bullish_setup:
            target = find_target(df, idx, 'long')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'long', row['close'], target, row['sweep_source'],
                                     {'config': 'A'}))
        
        bearish_setup = (
            row['sweep_bearish'] and
            displacement_bearish and
            row['fvg_bearish'] and
            row['mss_bearish'] and
            row['regime'] in ['bear_trend', 'sideways']
        )
        
        if bearish_setup:
            target = find_target(df, idx, 'short')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'short', row['close'], target, row['sweep_source'],
                                     {'config': 'A'}))
    
    return signals


def generate_signals_config_B(df: pd.DataFrame) -> list:
    """
    Config B: Make FVG optional (sweep + displacement + MSS only)
    """
    signals = []
    
    for idx in df.index:
        row = df.loc[idx]
        
        if not in_ny_open_window(row['timestamp']):
            continue
        
        bullish_setup = (
            row['sweep_bullish'] and
            row['displacement_bullish'] and
            row['mss_bullish'] and
            row['regime'] in ['bull_trend', 'sideways']
        )
        
        if bullish_setup:
            target = find_target(df, idx, 'long')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'long', row['close'], target, row['sweep_source'],
                                     {'config': 'B'}))
        
        bearish_setup = (
            row['sweep_bearish'] and
            row['displacement_bearish'] and
            row['mss_bearish'] and
            row['regime'] in ['bear_trend', 'sideways']
        )
        
        if bearish_setup:
            target = find_target(df, idx, 'short')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'short', row['close'], target, row['sweep_source'],
                                     {'config': 'B'}))
    
    return signals


def generate_signals_config_C(df: pd.DataFrame) -> list:
    """
    Config C: Extend NY window to 12:00 (from 11:00)
    """
    signals = []
    
    for idx in df.index:
        row = df.loc[idx]
        
        # Extended window check
        ts = row['timestamp']
        hour = ts.hour
        minute = ts.minute
        in_window = (hour == 9 and minute >= 30) or (hour >= 10 and hour < 12)
        
        if not in_window:
            continue
        
        bullish_setup = (
            row['sweep_bullish'] and
            row['displacement_bullish'] and
            row['fvg_bullish'] and
            row['mss_bullish'] and
            row['regime'] in ['bull_trend', 'sideways']
        )
        
        if bullish_setup:
            target = find_target(df, idx, 'long')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'long', row['close'], target, row['sweep_source'],
                                     {'config': 'C'}))
        
        bearish_setup = (
            row['sweep_bearish'] and
            row['displacement_bearish'] and
            row['fvg_bearish'] and
            row['mss_bearish'] and
            row['regime'] in ['bear_trend', 'sideways']
        )
        
        if bearish_setup:
            target = find_target(df, idx, 'short')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'short', row['close'], target, row['sweep_source'],
                                     {'config': 'C'}))
    
    return signals


def generate_signals_config_D(df: pd.DataFrame) -> list:
    """
    Config D: Relaxed combo (no FVG required + extended window + lower displacement)
    """
    signals = []
    
    for idx in df.index:
        row = df.loc[idx]
        
        # Extended window
        ts = row['timestamp']
        hour = ts.hour
        minute = ts.minute
        in_window = (hour == 9 and minute >= 30) or (hour >= 10 and hour < 12)
        
        if not in_window:
            continue
        
        # Lower displacement threshold
        displacement_bullish = (row['atr'] > 0) and (abs(row['close'] - row['open']) > 1.0 * row['atr'])
        displacement_bearish = displacement_bullish
        
        bullish_setup = (
            row['sweep_bullish'] and
            displacement_bullish and
            row['mss_bullish'] and
            row['regime'] in ['bull_trend', 'sideways']
        )
        
        if bullish_setup:
            target = find_target(df, idx, 'long')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'long', row['close'], target, row['sweep_source'],
                                     {'config': 'D'}))
        
        bearish_setup = (
            row['sweep_bearish'] and
            displacement_bearish and
            row['mss_bearish'] and
            row['regime'] in ['bear_trend', 'sideways']
        )
        
        if bearish_setup:
            target = find_target(df, idx, 'short')
            if target:
                signals.append(Signal(idx, row['timestamp'], 'short', row['close'], target, row['sweep_source'],
                                     {'config': 'D'}))
    
    return signals


def test_config(name, signals, df):
    """Test a configuration and print results."""
    print(f"\n{name}:")
    print(f"  Signals: {len(signals)}")
    
    if len(signals) == 0:
        print(f"  Win Rate: N/A")
        print(f"  Avg R: N/A")
        return
    
    backtest = Backtest(df, signals)
    results = backtest.run(max_bars_held=60)
    
    print(f"  Win Rate: {results['win_rate']*100:.1f}%")
    print(f"  Avg R: {results['avg_r_multiple']:.2f}R")
    print(f"  Total PnL: ${results['total_pnl']:.2f}")
    print(f"  Signals/month: {len(signals)/3:.1f}")


def main():
    print("=" * 70)
    print("Testing Relaxed Signal Configurations")
    print("=" * 70)
    print()
    
    provider = CSVDataProvider(path='data/QQQ_1m_real.csv', symbol='QQQ')
    df = provider.load_bars()
    
    # Build features
    renko_df = build_renko(df, mode="atr", k=1.0)
    renko_direction = get_renko_direction_series(df, renko_df)
    df['renko_direction'] = renko_direction
    df['regime'] = detect_regime(df, renko_direction, lookback=20)
    
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_liquidity_sweeps(df)
    df = detect_displacement(df, atr_period=14)
    df = detect_fvgs(df)
    df = detect_mss(df)
    
    print("Testing configurations on 90 days of real QQQ data...")
    
    # Test each config
    signals_a = generate_signals_config_A(df)
    signals_b = generate_signals_config_B(df)
    signals_c = generate_signals_config_C(df)
    signals_d = generate_signals_config_D(df)
    
    print("\nRESULTS:")
    print("-" * 70)
    
    test_config("CURRENT (Strict: Sweep+Disp+FVG+MSS, 09:30-11:00)", [], df)
    test_config("CONFIG A (Lower displacement: 1.0x ATR)", signals_a, df)
    test_config("CONFIG B (No FVG required)", signals_b, df)
    test_config("CONFIG C (Extended window to 12:00)", signals_c, df)
    test_config("CONFIG D (Relaxed combo: no FVG + extended + 1.0x)", signals_d, df)
    
    print()
    print("=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    print()
    print("Choose config with best balance of:")
    print("  - Signal frequency (target: 8-10/month)")
    print("  - Win rate (target: >60%)")
    print("  - Avg R-multiple (target: >1.5R)")


if __name__ == '__main__':
    main()
