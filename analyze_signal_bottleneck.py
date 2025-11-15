"""
Analyze where signal candidates fail in the pipeline.
Shows stage-by-stage attrition to identify bottlenecks.
"""

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import (
    detect_liquidity_sweeps,
    detect_displacement,
    detect_fvgs,
    detect_mss,
    detect_order_blocks
)
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy import in_ny_open_window


def analyze_pipeline(df: pd.DataFrame):
    """Analyze signal pipeline stage by stage."""
    
    print("=" * 70)
    print("Signal Pipeline Bottleneck Analysis")
    print("=" * 70)
    print()
    
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
    df = detect_order_blocks(df)
    
    # Filter to NY open window
    df['in_ny_window'] = df['timestamp'].apply(in_ny_open_window)
    ny_df = df[df['in_ny_window']].copy()
    
    print(f"Total bars: {len(df):,}")
    print(f"NY window bars (09:30-11:00): {len(ny_df):,}")
    print()
    
    print("STAGE-BY-STAGE ANALYSIS")
    print("-" * 70)
    print()
    
    # Stage 1: Sweeps
    bullish_sweep = ny_df['sweep_bullish'].sum()
    bearish_sweep = ny_df['sweep_bearish'].sum()
    print(f"Stage 1 - Liquidity Sweeps:")
    print(f"  Bullish sweeps: {bullish_sweep}")
    print(f"  Bearish sweeps: {bearish_sweep}")
    print()
    
    # Stage 2: Sweeps + Displacement
    bull_sweep_disp = (ny_df['sweep_bullish'] & ny_df['displacement_bullish']).sum()
    bear_sweep_disp = (ny_df['sweep_bearish'] & ny_df['displacement_bearish']).sum()
    print(f"Stage 2 - Sweep + Displacement:")
    print(f"  Bullish: {bull_sweep_disp} (kept {bull_sweep_disp/max(bullish_sweep,1)*100:.1f}%)")
    print(f"  Bearish: {bear_sweep_disp} (kept {bear_sweep_disp/max(bearish_sweep,1)*100:.1f}%)")
    print()
    
    # Stage 3: + FVG
    bull_sweep_disp_fvg = (ny_df['sweep_bullish'] & ny_df['displacement_bullish'] & ny_df['fvg_bullish']).sum()
    bear_sweep_disp_fvg = (ny_df['sweep_bearish'] & ny_df['displacement_bearish'] & ny_df['fvg_bearish']).sum()
    print(f"Stage 3 - Sweep + Displacement + FVG:")
    print(f"  Bullish: {bull_sweep_disp_fvg} (kept {bull_sweep_disp_fvg/max(bull_sweep_disp,1)*100:.1f}%)")
    print(f"  Bearish: {bear_sweep_disp_fvg} (kept {bear_sweep_disp_fvg/max(bear_sweep_disp,1)*100:.1f}%)")
    print()
    
    # Stage 4: + MSS
    bull_full = (ny_df['sweep_bullish'] & ny_df['displacement_bullish'] & 
                 ny_df['fvg_bullish'] & ny_df['mss_bullish']).sum()
    bear_full = (ny_df['sweep_bearish'] & ny_df['displacement_bearish'] & 
                 ny_df['fvg_bearish'] & ny_df['mss_bearish']).sum()
    print(f"Stage 4 - Full Confluence (+ MSS):")
    print(f"  Bullish: {bull_full} (kept {bull_full/max(bull_sweep_disp_fvg,1)*100:.1f}%)")
    print(f"  Bearish: {bear_full} (kept {bear_full/max(bear_sweep_disp_fvg,1)*100:.1f}%)")
    print()
    
    # Stage 5: + Regime filter
    bull_regime = (ny_df['sweep_bullish'] & ny_df['displacement_bullish'] & 
                   ny_df['fvg_bullish'] & ny_df['mss_bullish'] & 
                   ny_df['regime'].isin(['bull_trend', 'sideways'])).sum()
    bear_regime = (ny_df['sweep_bearish'] & ny_df['displacement_bearish'] & 
                   ny_df['fvg_bearish'] & ny_df['mss_bearish'] & 
                   ny_df['regime'].isin(['bear_trend', 'sideways'])).sum()
    print(f"Stage 5 - + Regime Filter:")
    print(f"  Bullish: {bull_regime} (kept {bull_regime/max(bull_full,1)*100:.1f}%)")
    print(f"  Bearish: {bear_regime} (kept {bear_regime/max(bear_full,1)*100:.1f}%)")
    print()
    
    print("=" * 70)
    print("BOTTLENECK SUMMARY")
    print("=" * 70)
    print()
    print(f"Biggest attrition points:")
    if bullish_sweep > 0:
        disp_loss = (1 - bull_sweep_disp/bullish_sweep) * 100
        fvg_loss = (1 - bull_sweep_disp_fvg/max(bull_sweep_disp,1)) * 100
        print(f"  - Displacement filter: -{disp_loss:.0f}% of sweeps lost")
        print(f"  - FVG filter: -{fvg_loss:.0f}% of remaining lost")
    print()
    
    print("RECOMMENDATIONS:")
    print("-" * 70)
    print("1. Lower displacement threshold: 1.2x ATR → 1.0x ATR")
    print("2. Make FVG optional or use 2-candle gap instead of 3")
    print("3. Extend NY window: 11:00 → 12:00")
    print("4. Add prior-day highs/lows as sweep sources")
    print()


def main():
    provider = CSVDataProvider(path='data/QQQ_1m_real.csv', symbol='QQQ')
    df = provider.load_bars()
    
    print(f"Loaded {len(df):,} bars of real QQQ data")
    print()
    
    analyze_pipeline(df)


if __name__ == '__main__':
    main()
