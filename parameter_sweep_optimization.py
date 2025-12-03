#!/usr/bin/env python3
"""
Parameter sweep to find optimal ICT confluence settings that generate tradable signals.
Tests different displacement thresholds and confluence requirements.
"""

import sys, pandas as pd, glob, numpy as np
from collections import defaultdict

sys.path.insert(0, '.')
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

# Get data files
files = sorted(glob.glob('data/polygon_downloads/QQQ_2024_*.csv') + glob.glob('data/polygon_downloads/QQQ_2025_*.csv'))[:15]

print("="*80)
print("PARAMETER SWEEP: Finding optimal ICT confluence settings")
print("="*80)

# Test configurations
configs = [
    {'disp': 0.3, 'req': 'all3', 'name': '0.3x ATR + Sweep+Disp+MSS'},
    {'disp': 0.5, 'req': 'all3', 'name': '0.5x ATR + Sweep+Disp+MSS'},
    {'disp': 0.75, 'req': 'all3', 'name': '0.75x ATR + Sweep+Disp+MSS (CURRENT)'},
    {'disp': 1.0, 'req': 'all3', 'name': '1.0x ATR + Sweep+Disp+MSS'},
    {'disp': 0.3, 'req': 'sweep_disp', 'name': '0.3x ATR + Sweep+Disp only'},
    {'disp': 0.5, 'req': 'sweep_disp', 'name': '0.5x ATR + Sweep+Disp only'},
    {'disp': 0.75, 'req': 'sweep_disp', 'name': '0.75x ATR + Sweep+Disp only'},
    {'disp': 1.0, 'req': 'sweep_disp', 'name': '1.0x ATR + Sweep+Disp only'},
    {'disp': 0.3, 'req': 'sweep_only', 'name': '0.3x ATR + Sweep only'},
    {'disp': 0.5, 'req': 'sweep_only', 'name': '0.5x ATR + Sweep only'},
]

results = []

for config in configs:
    disp_thresh = config['disp']
    req_type = config['req']
    name = config['name']
    
    signal_count = 0
    last_exit = None
    
    for file in files:
        try:
            df = pd.read_csv(file)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.tz_convert('America/New_York')
            df['date'] = df['timestamp'].dt.date
            
            for date in sorted(df['date'].unique()):
                day_df = df[df['date'] == date].copy().reset_index(drop=True)
                if len(day_df) < 50:
                    continue
                
                day_df['h-l'] = day_df['high'] - day_df['low']
                day_df['h-pc'] = abs(day_df['high'] - day_df['close'].shift(1))
                day_df['l-pc'] = abs(day_df['low'] - day_df['close'].shift(1))
                day_df['tr'] = day_df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
                day_df['atr'] = day_df['tr'].rolling(window=14).mean()
                
                day_df = label_sessions(day_df)
                day_df = add_session_highs_lows(day_df)
                day_df = detect_all_structures(day_df, displacement_threshold=disp_thresh)
                
                for i in range(len(day_df) - 7):
                    if pd.isna(day_df.iloc[i]['atr']) or day_df.iloc[i]['atr'] == 0:
                        continue
                    
                    sig_time = day_df.iloc[i]['timestamp']
                    if last_exit is not None and sig_time <= last_exit:
                        continue
                    
                    window = day_df.iloc[i:i+7]
                    
                    bullish_sweep = day_df.iloc[i]['sweep_bullish']
                    bearish_sweep = day_df.iloc[i]['sweep_bearish']
                    disp_bull = window['displacement_bullish'].any()
                    disp_bear = window['displacement_bearish'].any()
                    mss_bull = window['mss_bullish'].any()
                    mss_bear = window['mss_bearish'].any()
                    
                    # Evaluate requirements
                    if req_type == 'all3':
                        bull_ok = bullish_sweep and disp_bull and mss_bull
                        bear_ok = bearish_sweep and disp_bear and mss_bear
                    elif req_type == 'sweep_disp':
                        bull_ok = bullish_sweep and disp_bull
                        bear_ok = bearish_sweep and disp_bear
                    elif req_type == 'sweep_only':
                        bull_ok = bullish_sweep
                        bear_ok = bearish_sweep
                    else:
                        bull_ok = bear_ok = False
                    
                    if bull_ok or bear_ok:
                        signal_count += 1
                        future = day_df.iloc[i+1:i+61]
                        if len(future) > 0:
                            last_exit = future.iloc[-1]['timestamp']
        except Exception as e:
            continue
    
    results.append({
        'config': name,
        'signals': signal_count,
        'signals_per_day': signal_count / (len(files) * 21) if len(files) > 0 else 0
    })
    
    print(f"{name:50} | Signals: {signal_count:4d} | Per Day: {signal_count / (len(files) * 21):.2f}")

print("\n" + "="*80)
print("SUMMARY - Top 5 Configurations by Signal Generation:")
print("="*80)

for i, r in enumerate(sorted(results, key=lambda x: x['signals'], reverse=True)[:5]):
    print(f"{i+1}. {r['config']:50} | {r['signals']:4d} signals ({r['signals_per_day']:.2f}/day)")

print("\nRECOMMENDATION: Use the top configuration that generates ~2-3 signals/day")
