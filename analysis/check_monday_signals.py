"""
Quick analysis: What signals were available on Monday, Nov 25, 2025
Compare production (1.0%) vs relaxed (0.75%) parameters
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
from datetime import datetime
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

def analyze_day(df: pd.DataFrame, displacement_threshold: float, config_name: str):
    """Analyze signals for one configuration."""
    if len(df) < 50:
        print(f"  {config_name}: Not enough data")
        return []
    
    df = df.copy()
    df['atr'] = calculate_atr(df)
    
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_all_structures(df, displacement_threshold=displacement_threshold)
    
    signals = []
    confluence_window = 6
    
    for i in range(len(df) - confluence_window):
        # Bullish confluence
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+confluence_window+1]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                atr = df.iloc[i].get('atr', 0.5)
                price = df.iloc[i]['close']
                target = price + (5.0 * atr)
                
                # Check if target hit
                future = df.iloc[i+1:i+61]
                hit_target = (future['high'] >= target).any() if len(future) > 0 else False
                
                signals.append({
                    'time': df.iloc[i]['timestamp'],
                    'direction': 'LONG',
                    'price': price,
                    'target': target,
                    'atr': atr,
                    'hit_target': hit_target
                })
        
        # Bearish confluence
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+confluence_window+1]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                atr = df.iloc[i].get('atr', 0.5)
                price = df.iloc[i]['close']
                target = price - (5.0 * atr)
                
                # Check if target hit
                future = df.iloc[i+1:i+61]
                hit_target = (future['low'] <= target).any() if len(future) > 0 else False
                
                signals.append({
                    'time': df.iloc[i]['timestamp'],
                    'direction': 'SHORT',
                    'price': price,
                    'target': target,
                    'atr': atr,
                    'hit_target': hit_target
                })
    
    return signals

def main():
    print("\n" + "="*80)
    print("MONDAY, NOVEMBER 25, 2025 - MISSED OPPORTUNITIES ANALYSIS")
    print("="*80 + "\n")
    
    # Fetch Monday's data
    fetcher = PolygonDataFetcher()
    df = fetcher.fetch_stock_bars(
        ticker='QQQ',
        from_date='2025-11-25',
        to_date='2025-11-25'
    )
    
    if df is None or len(df) == 0:
        print("❌ No data available for Monday, Nov 25, 2025")
        print("   (Market may have been closed or data not yet available)")
        return
    
    print(f"📊 QQQ Data: {len(df)} bars")
    print(f"   Time Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    print(f"   Price Range: ${df['low'].min():.2f} - ${df['high'].max():.2f}\n")
    
    # Analyze both configurations
    print("="*80)
    print("PRODUCTION PARAMETERS (1.0% displacement)")
    print("="*80)
    prod_signals = analyze_day(df, 1.0, "Production")
    
    if not prod_signals:
        print("  ❌ NO SIGNALS DETECTED\n")
    else:
        for sig in prod_signals:
            status = "✅ HIT TARGET" if sig['hit_target'] else "❌ MISSED"
            print(f"  {sig['time']} | {sig['direction']:5s} @ ${sig['price']:.2f} → ${sig['target']:.2f} | {status}")
        wins = sum(1 for s in prod_signals if s['hit_target'])
        print(f"\n  Total Signals: {len(prod_signals)}")
        print(f"  Winners: {wins} ({wins/len(prod_signals)*100:.0f}%)\n")
    
    print("="*80)
    print("RELAXED PARAMETERS (0.75% displacement)")
    print("="*80)
    relax_signals = analyze_day(df, 0.75, "Relaxed")
    
    if not relax_signals:
        print("  ❌ NO SIGNALS DETECTED\n")
    else:
        for sig in relax_signals:
            status = "✅ HIT TARGET" if sig['hit_target'] else "❌ MISSED"
            print(f"  {sig['time']} | {sig['direction']:5s} @ ${sig['price']:.2f} → ${sig['target']:.2f} | {status}")
        wins = sum(1 for s in relax_signals if s['hit_target'])
        print(f"\n  Total Signals: {len(relax_signals)}")
        print(f"  Winners: {wins} ({wins/len(relax_signals)*100:.0f}%)\n")
    
    # Summary
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Production (1.0%): {len(prod_signals)} signals")
    print(f"Relaxed (0.75%):   {len(relax_signals)} signals")
    
    if len(relax_signals) > len(prod_signals):
        additional = len(relax_signals) - len(prod_signals)
        print(f"\n⚠️  Relaxed parameters caught {additional} additional signal(s)")
    elif len(prod_signals) == len(relax_signals) == 0:
        print(f"\n✅ Both configurations correctly identified Monday as a NO-TRADE day")
        print("   This is expected behavior for a quality-focused strategy")
    else:
        print(f"\n✅ Both configurations performed similarly")

if __name__ == '__main__':
    main()
