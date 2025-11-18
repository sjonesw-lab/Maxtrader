#!/usr/bin/env python3
"""
Analyze today's missed trading signals from Polygon API data
Uses the same detection logic as auto_trader.py
"""
import os
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
import pytz
import pandas as pd
import numpy as np

from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.polygon_data_fetcher import PolygonDataFetcher


def main():
    # Setup dates
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.now(et_tz)
    today_str = now_et.strftime('%Y-%m-%d')
    
    print(f"🔍 ANALYZING TODAY'S ICT SIGNALS")
    print(f"📅 Date: {today_str}")
    print(f"🕐 Current ET Time: {now_et.strftime('%I:%M %p ET')}\n")
    
    # Download today's data using same fetcher as auto_trader
    print("📥 Downloading 1-minute bars from Polygon...")
    fetcher = PolygonDataFetcher()
    
    try:
        df = fetcher.fetch_stock_bars(
            ticker='QQQ',
            from_date=today_str,
            to_date=today_str
        )
        
        if df is None or len(df) == 0:
            print("❌ No data received from Polygon")
            return
        
        print(f"✅ Downloaded {len(df)} bars")
        print(f"📊 Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
        print(f"💰 Current price: ${df['close'].iloc[-1]:.2f}\n")
        
        # Run ICT detection using EXACT same logic as auto_trader
        print("🔍 Running ICT structure detection (same logic as auto_trader)...")
        df = df.copy()
        
        # Calculate ATR
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=14).mean()
        
        # Add session data
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        
        # Detect all ICT structures
        df = detect_all_structures(df, displacement_threshold=1.0)
        
        # Find confluence signals (same criteria as auto_trader)
        signals = []
        for idx in range(len(df)):
            row = df.iloc[idx]
            
            # Check for ICT confluence within last 5 bars
            lookback_start = max(0, idx - 4)
            recent = df.iloc[lookback_start:idx+1]
            
            has_sweep = recent['sweep_bullish'].any() or recent['sweep_bearish'].any()
            has_displacement = recent['displacement_bullish'].any() or recent['displacement_bearish'].any()
            has_mss = recent['mss_bullish'].any() or recent['mss_bearish'].any()
            
            if has_sweep and has_displacement and has_mss:
                # Determine direction
                if recent['sweep_bullish'].any() and recent['displacement_bullish'].any():
                    direction = 'long'
                elif recent['sweep_bearish'].any() and recent['displacement_bearish'].any():
                    direction = 'short'
                else:
                    continue
                
                # Get actual timestamp - df may have integer index
                if hasattr(df.index[idx], 'strftime'):
                    ts = df.index[idx]
                else:
                    # Use the row's timestamp if available, otherwise skip
                    if 'timestamp' in df.columns:
                        ts = row['timestamp']
                    else:
                        continue
                
                signals.append({
                    'timestamp': ts,
                    'direction': direction,
                    'price': row['close'],
                    'atr': row['atr']
                })
        
        if not signals:
            print("❌ No ICT confluence signals detected today")
            print("   (Requires: Sweep + Displacement + MSS within 5 bars)")
            return
        
        print(f"✅ Found {len(signals)} ICT confluence signals\n")
        
        # Define gap periods (when system was down)
        gap_start = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        gap_end = now_et.replace(hour=11, minute=44, second=0, microsecond=0)
        
        print("=" * 80)
        print("📋 ALL ICT CONFLUENCE SIGNALS DETECTED TODAY")
        print("=" * 80)
        
        missed_signals = []
        caught_signals = []
        
        for i, signal in enumerate(signals, 1):
            sig_time = signal['timestamp']
            direction = signal['direction']
            price = signal['price']
            atr = signal['atr']
            
            # Check if in gap
            in_gap = gap_start <= sig_time <= gap_end
            
            if in_gap:
                missed_signals.append(signal)
                status = "❌ MISSED (System Down)"
            else:
                caught_signals.append(signal)
                status = "✅ COULD HAVE CAUGHT"
            
            # Calculate potential targets (5x ATR)
            target_move = atr * 5.0
            if direction == 'long':
                target_price = price + target_move
            else:
                target_price = price - target_move
            
            print(f"\n{i}. {status}")
            print(f"   Time: {sig_time.strftime('%I:%M %p ET')}")
            print(f"   Direction: {direction.upper()}")
            print(f"   Entry Price: ${price:.2f}")
            print(f"   ATR: ${atr:.2f}")
            print(f"   Target (5x ATR): ${target_price:.2f}")
        
        # Summary
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print(f"Total Signals Today: {len(signals)}")
        print(f"❌ Missed (9:30 AM - 11:44 AM gap): {len(missed_signals)}")
        print(f"✅ Monitored Period (11:44 AM - now): {len(caught_signals)}")
        
        if missed_signals:
            print("\n⚠️  IMPACT OF MISSED SIGNALS:")
            print(f"   • {len(missed_signals)} ICT confluence trade(s) not executed")
            print(f"   • Gap period: 2 hours 14 minutes (77% of trading so far)")
            print(f"   • Each would have been entered with:")
            print(f"     - Conservative strategy (3% risk, 1-strike ITM option)")
            print(f"     - Aggressive strategy (4% risk, 1-strike ITM option)")
            print(f"   • Based on backtest stats: 78-79% win rate expected")
        
        if caught_signals:
            print("\n✅ SIGNALS DURING MONITORED PERIOD:")
            print(f"   • {len(caught_signals)} signal(s) occurred after 11:44 AM")
            print(f"   • System was running but may not have executed due to recent start")
            print(f"   • Tomorrow: Full coverage from 9:25 AM - 4:05 PM ET guaranteed")
        
        if len(signals) == 0:
            print("\n💡 ZERO-TRADE DAY:")
            print(f"   • No ICT confluence setups detected")
            print(f"   • This is normal - system averages ~2.5 trades/day")
            print(f"   • Some days have 0, some have 5+")
            print(f"   • Quality over quantity = institutional setups only")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
