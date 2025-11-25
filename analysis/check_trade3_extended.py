"""
Check if Trade #3 (LONG @ 3:44 PM) would have hit target without timeout
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

def calculate_atr(df: pd.DataFrame, period=14) -> pd.Series:
    """Calculate ATR."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    return df['tr'].rolling(window=period).mean()

def main():
    print("\n" + "="*80)
    print("TRADE #3 EXTENDED ANALYSIS")
    print("="*80 + "\n")
    
    # Fetch data
    fetcher = PolygonDataFetcher()
    df = fetcher.fetch_stock_bars('QQQ', '2025-11-25', '2025-11-25')
    
    if df is None or len(df) == 0:
        print("❌ No data")
        return
    
    # Detect signals
    df = df.copy()
    df['atr'] = calculate_atr(df)
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_all_structures(df, displacement_threshold=1.0)
    
    # Find Trade #3 (LONG at 3:44 PM ET)
    target_time = pd.to_datetime('2025-11-25 15:44:00-05:00').tz_convert('UTC')
    
    signal_idx = None
    for i in range(len(df)):
        if df.iloc[i]['sweep_bullish']:
            timestamp = pd.to_datetime(df.iloc[i]['timestamp'])
            if abs((timestamp - target_time).total_seconds()) < 120:  # Within 2 minutes
                signal_idx = i
                break
    
    if signal_idx is None:
        print("❌ Could not find Trade #3 signal")
        return
    
    sig = df.iloc[signal_idx]
    entry_price = sig['close']
    atr = sig['atr']
    target = entry_price + (5.0 * atr)
    
    print(f"📍 SIGNAL DETAILS:")
    print(f"   Time:   {sig['timestamp']}")
    print(f"   Entry:  ${entry_price:.2f}")
    print(f"   Target: ${target:.2f}")
    print(f"   ATR:    ${atr:.2f}\n")
    
    # Check what happens after signal
    remaining = df.iloc[signal_idx+1:]
    
    print("="*80)
    print("PRICE ACTION AFTER ENTRY")
    print("="*80 + "\n")
    
    # Check within 60-minute timeout
    timeout_bars = remaining.head(60)
    hit_within_timeout = (timeout_bars['high'] >= target).any()
    
    print(f"⏱️  WITHIN 60-MINUTE TIMEOUT:")
    if hit_within_timeout:
        hit_bar = timeout_bars[timeout_bars['high'] >= target].iloc[0]
        minutes_to_hit = timeout_bars.index.get_loc(hit_bar.name) + 1
        print(f"   ✅ Target HIT at {hit_bar['timestamp']}")
        print(f"   Time to target: {minutes_to_hit} minutes")
        print(f"   High: ${hit_bar['high']:.2f}")
    else:
        exit_bar = timeout_bars.iloc[-1] if len(timeout_bars) > 0 else sig
        print(f"   ❌ Target NOT hit")
        print(f"   Exit time: {exit_bar['timestamp']}")
        print(f"   Exit price: ${exit_bar['close']:.2f}")
        print(f"   Highest reached: ${timeout_bars['high'].max():.2f}")
        print(f"   Distance from target: ${target - timeout_bars['high'].max():.2f}")
    
    # Check rest of day (after timeout)
    print(f"\n📊 AFTER 60-MINUTE TIMEOUT (rest of trading day):")
    after_timeout = remaining.iloc[60:]
    
    if len(after_timeout) > 0:
        hit_after_timeout = (after_timeout['high'] >= target).any()
        
        if hit_after_timeout:
            hit_bar = after_timeout[after_timeout['high'] >= target].iloc[0]
            total_minutes = 60 + (after_timeout.index.get_loc(hit_bar.name) + 1)
            print(f"   ✅ Target WOULD HAVE HIT at {hit_bar['timestamp']}")
            print(f"   Total time from entry: {total_minutes} minutes")
            print(f"   High: ${hit_bar['high']:.2f}")
            print(f"\n   💡 If no timeout, this would have been a WINNER")
        else:
            print(f"   ❌ Target never hit for rest of day")
            print(f"   Highest reached: ${after_timeout['high'].max():.2f}")
            print(f"   Day closed at: ${after_timeout.iloc[-1]['close']:.2f}")
            print(f"\n   ✅ Timeout exit was correct decision")
    else:
        print(f"   No more bars after timeout (end of day)")
    
    # Summary
    print("\n" + "="*80)
    print("CONCLUSION")
    print("="*80)
    
    if hit_within_timeout:
        print("\n✅ Trade #3 DID hit target within the 60-minute window")
        print("   The analysis shows it as a WINNER")
    elif len(after_timeout) > 0 and (after_timeout['high'] >= target).any():
        print("\n⚠️  Trade #3 WOULD HAVE hit target, but AFTER the 60-minute timeout")
        print("   The 60-minute rule protected against holding too long")
        print("   This is why the timeout exists - to limit exposure")
    else:
        print("\n✅ Trade #3 never hit target - timeout prevented bigger loss")
        print("   Exiting at timeout was the right decision")

if __name__ == '__main__':
    main()
