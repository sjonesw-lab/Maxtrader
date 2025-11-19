#!/usr/bin/env python3
"""
Quick SPY Backtest - Test ICT strategy on SPY using available data
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
from pathlib import Path

# Import backtest functions from comprehensive backtest
from backtests.comprehensive_2024_2025 import (
    calculate_atr,
    detect_sweeps_strict,
    find_signals,
    backtest_with_strike_offset,
    analyze_performance
)
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_displacement, detect_mss

def run_spy_backtest():
    """Run ICT backtest on SPY data"""
    
    # Load SPY data
    spy_file = Path('data/SPY_1m_2024_2025.csv')
    if not spy_file.exists():
        print(f"❌ SPY data not found at {spy_file}")
        return
    
    print("="*70)
    print("SPY ICT STRATEGY BACKTEST")
    print("="*70)
    
    df_spy = pd.read_csv(spy_file)
    df_spy['timestamp'] = pd.to_datetime(df_spy['timestamp'])
    
    print(f"Data: {len(df_spy):,} bars from {df_spy['timestamp'].min()} to {df_spy['timestamp'].max()}")
    
    # Apply ICT detection
    df_spy = calculate_atr(df_spy)
    df_spy = label_sessions(df_spy)
    df_spy = add_session_highs_lows(df_spy)
    df_spy = detect_sweeps_strict(df_spy)
    df_spy = detect_displacement(df_spy)
    df_spy = detect_mss(df_spy)
    
    # Find signals
    signals_spy = find_signals(df_spy)
    print(f"\n📊 ICT Signals Found: {len(signals_spy)}")
    
    if len(signals_spy) == 0:
        print("⚠️  No signals found - data period may be too short or low volatility")
        return
    
    # Backtest with 1-strike ITM options (champion strategy)
    print("\n" + "="*70)
    print("TESTING: 1-Strike ITM Options (Validated Champion)")
    print("="*70)
    
    trades_itm, final_itm = backtest_with_strike_offset(
        df_spy, signals_spy, 
        strike_offset=-1,  # 1 strike ITM
        starting_capital=25000,
        risk_pct=5.0
    )
    
    if len(trades_itm) > 0:
        metrics_itm = analyze_performance(trades_itm)
        
        print(f"\n{'='*70}")
        print(f"SPY RESULTS (1-Strike ITM)")
        print(f"{'='*70}")
        print(f"Total Trades:     {metrics_itm['total_trades']}")
        print(f"Win Rate:         {metrics_itm['win_rate']:.1f}%")
        print(f"Starting Capital: ${25000:,.2f}")
        print(f"Final Balance:    ${final_itm:,.2f}")
        print(f"Total Return:     {((final_itm - 25000) / 25000 * 100):.2f}%")
        print(f"Avg Win:          ${metrics_itm['avg_win']:.2f}")
        print(f"Avg Loss:         ${metrics_itm['avg_loss']:.2f}")
        print(f"Max Drawdown:     {metrics_itm['max_drawdown']:.2f}%")
        print(f"Largest Win:      ${metrics_itm['largest_win']:.2f}")
        print(f"Largest Loss:     ${metrics_itm['largest_loss']:.2f}")
        print(f"{'='*70}\n")
        
        # Compare to QQQ (reference)
        print(f"📌 NOTE: This is {(df_spy['timestamp'].max() - df_spy['timestamp'].min()).days} days of SPY data")
        print(f"   Full year comparison coming after complete data download")
    
    # Test ATM for comparison
    print("\n" + "="*70)
    print("COMPARISON: ATM Options")
    print("="*70)
    
    trades_atm, final_atm = backtest_with_strike_offset(
        df_spy, signals_spy,
        strike_offset=0,  # ATM
        starting_capital=25000,
        risk_pct=5.0
    )
    
    if len(trades_atm) > 0:
        metrics_atm = analyze_performance(trades_atm)
        print(f"ATM Final Balance: ${final_atm:,.2f}")
        print(f"ATM Return:        {((final_atm - 25000) / 25000 * 100):.2f}%")
        print(f"ATM Win Rate:      {metrics_atm['win_rate']:.1f}%")
        
        # Show advantage
        itm_advantage = ((final_itm - final_atm) / final_atm * 100) if final_atm > 0 else 0
        print(f"\n💡 ITM vs ATM: {itm_advantage:+.1f}% better performance")

if __name__ == '__main__':
    run_spy_backtest()
