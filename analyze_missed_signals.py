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
    # Setup dates - use Nov 18 (yesterday) since it's after midnight
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.now(et_tz)
    # Use Nov 18 for analysis
    analysis_date = datetime(2025, 11, 18, tzinfo=et_tz)
    today_str = '2025-11-18'
    
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
        
        # Define gap periods (when system was down) - Nov 18
        gap_start = analysis_date.replace(hour=9, minute=30, second=0, microsecond=0)
        gap_end = analysis_date.replace(hour=11, minute=44, second=0, microsecond=0)
        
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
            
            # Check if target was hit in next 60 minutes
            # Find the signal's index location
            sig_idx = idx  # Use the loop idx directly
            next_60_bars = df.iloc[sig_idx:sig_idx+61] if sig_idx < len(df) else df.iloc[sig_idx:]
            
            hit_target = False
            max_profit = 0.0
            if direction == 'long':
                max_high = next_60_bars['high'].max()
                max_profit = max_high - price
                hit_target = max_high >= target_price
            else:
                min_low = next_60_bars['low'].min()
                max_profit = price - min_low
                hit_target = min_low <= target_price
            
            profit_pct = (max_profit / price) * 100
            outcome = "✅ TARGET HIT" if hit_target else f"❌ MISSED (max: ${max_profit:.2f} / {profit_pct:.1f}%)"
            
            print(f"\n{i}. {status}")
            print(f"   Time: {sig_time.strftime('%I:%M %p ET')}")
            print(f"   Direction: {direction.upper()}")
            print(f"   Entry: ${price:.2f} → Target: ${target_price:.2f} (${target_move:.2f})")
            print(f"   OUTCOME: {outcome}")
        
        # Calculate actual performance
        print("\n" + "=" * 80)
        print("📊 ACTUAL PERFORMANCE")
        print("=" * 80)
        
        # Count winners from all signals
        total_winners = 0
        total_losers = 0
        missed_winners = 0
        missed_losers = 0
        
        for sig in signals:
            sig_time = sig['timestamp']
            price = sig['price']
            direction = sig['direction']
            atr = sig['atr']
            
            # Find this signal in dataframe
            sig_idx = None
            for idx_val in range(len(df)):
                if hasattr(df.index[idx_val], 'strftime'):
                    if df.index[idx_val] == sig_time:
                        sig_idx = idx_val
                        break
            
            if sig_idx is None:
                continue
            
            # Check outcome
            next_60_bars = df.iloc[sig_idx:sig_idx+61]
            target_move = atr * 5.0
            
            if direction == 'long':
                target_price = price + target_move
                hit_target = next_60_bars['high'].max() >= target_price
            else:
                target_price = price - target_move
                hit_target = next_60_bars['low'].min() <= target_price
            
            # Track in gap or not
            in_gap = gap_start <= sig_time <= gap_end
            
            if hit_target:
                total_winners += 1
                if in_gap:
                    missed_winners += 1
            else:
                total_losers += 1
                if in_gap:
                    missed_losers += 1
        
        win_rate = (total_winners / len(signals) * 100) if signals else 0
        
        print(f"Total Signals: {len(signals)}")
        print(f"Winners: {total_winners} ({win_rate:.1f}%)")
        print(f"Losers: {total_losers}")
        print(f"\nMISSED DURING SYSTEM DOWNTIME:")
        print(f"  Total Missed: {len(missed_signals)}")
        print(f"  Would-Be Winners: {missed_winners}")
        print(f"  Would-Be Losers: {missed_losers}")
        print(f"\nMONITORED PERIOD:")
        print(f"  Total Signals: {len(caught_signals)}")
        print(f"  Winners: {total_winners - missed_winners}")
        print(f"  Losers: {total_losers - missed_losers}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
