"""
Analyze missed P&L from system downtime using Polygon data
"""
import os
import sys
from datetime import datetime, timedelta
import pytz
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.ict_structures import ICTStructureDetector

def analyze_day(date_str, symbol='QQQ'):
    """Analyze what we would have made on a specific trading day"""
    print(f"\n{'='*80}")
    print(f"ANALYZING: {date_str} ({symbol})")
    print(f"{'='*80}\n")
    
    # Fetch data
    fetcher = PolygonDataFetcher()
    print(f"Fetching {symbol} bars for {date_str}...")
    df = fetcher.fetch_bars(symbol, date_str, date_str)
    
    if df is None or len(df) == 0:
        print(f"❌ No data available for {date_str}")
        return None
    
    print(f"✓ Got {len(df)} bars")
    
    # Detect signals
    detector = ICTStructureDetector()
    signals = detector.detect_structures(df)
    
    if not signals:
        print("📊 No ICT signals detected")
        return {
            'date': date_str,
            'bars': len(df),
            'signals': 0,
            'trades': [],
            'total_pl': 0
        }
    
    print(f"\n🎯 Found {len(signals)} ICT signals:")
    
    # Simulate trades
    trades = []
    total_pl = 0
    
    for i, sig in enumerate(signals, 1):
        direction = sig.get('direction', 'CALL')
        entry_price = sig.get('price', 0)
        target_price = sig.get('target', 0)
        entry_time = sig.get('timestamp', '')
        
        print(f"\n  Signal #{i}: {direction} @ ${entry_price:.2f}, target ${target_price:.2f}")
        print(f"    Time: {entry_time}")
        
        # Calculate ATR target distance
        target_distance = abs(target_price - entry_price)
        
        # Simulate option trade with 1-strike ITM
        account_balance = 25000
        risk_pct = 0.05
        risk_amount = account_balance * risk_pct
        
        # Find option strike (1-strike ITM)
        if direction == 'CALL':
            option_strike = entry_price - 1
        else:
            option_strike = entry_price + 1
        
        # Estimate option premium (simplified)
        intrinsic = abs(entry_price - option_strike)
        extrinsic = target_distance * 0.3  # Rough estimate
        option_price = intrinsic + extrinsic
        
        # Calculate contracts
        contracts = int(risk_amount / (option_price * 100))
        if contracts < 1:
            contracts = 1
        
        # Simulate exit
        target_hit = False
        exit_price = entry_price
        exit_time = entry_time
        
        # Check if target was reached in next bars
        entry_idx = df[df.index == entry_time].index[0] if entry_time in df.index else 0
        remaining_bars = df.iloc[entry_idx:]
        
        for idx, row in remaining_bars.iterrows():
            if direction == 'CALL':
                if row['high'] >= target_price:
                    target_hit = True
                    exit_price = target_price
                    exit_time = idx
                    break
            else:
                if row['low'] <= target_price:
                    target_hit = True
                    exit_price = target_price
                    exit_time = idx
                    break
        
        # Calculate P&L
        if target_hit:
            # Option increased in value
            exit_intrinsic = abs(exit_price - option_strike)
            exit_option_price = exit_intrinsic + (target_distance * 0.1)  # Less extrinsic at exit
            option_pl = (exit_option_price - option_price) * contracts * 100
            result = "✅ WIN"
        else:
            # No exit, assume small loss or breakeven
            option_pl = -risk_amount * 0.5  # Assume 50% loss if target not hit
            result = "❌ LOSS"
        
        total_pl += option_pl
        
        trade = {
            'signal_num': i,
            'direction': direction,
            'entry_price': entry_price,
            'target_price': target_price,
            'entry_time': str(entry_time),
            'exit_time': str(exit_time),
            'target_hit': target_hit,
            'contracts': contracts,
            'option_strike': option_strike,
            'entry_premium': option_price,
            'pl': option_pl,
            'result': result
        }
        trades.append(trade)
        
        print(f"    Strike: ${option_strike:.2f} {direction}")
        print(f"    Contracts: {contracts}")
        print(f"    Entry Premium: ${option_price:.2f}")
        print(f"    {result}: ${option_pl:+,.2f}")
    
    print(f"\n{'─'*80}")
    print(f"TOTAL P&L for {date_str}: ${total_pl:+,.2f}")
    print(f"{'─'*80}")
    
    return {
        'date': date_str,
        'bars': len(df),
        'signals': len(signals),
        'trades': trades,
        'total_pl': total_pl
    }

def main():
    et = pytz.timezone('America/New_York')
    now = datetime.now(et)
    
    # Yesterday and Today
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    today = now.strftime('%Y-%m-%d')
    
    results = []
    
    # Analyze yesterday
    result_yesterday = analyze_day(yesterday)
    if result_yesterday:
        results.append(result_yesterday)
    
    # Analyze today
    result_today = analyze_day(today)
    if result_today:
        results.append(result_today)
    
    # Summary
    print(f"\n\n{'='*80}")
    print("MISSED OPPORTUNITY SUMMARY")
    print(f"{'='*80}\n")
    
    total_missed_pl = 0
    for result in results:
        total_missed_pl += result['total_pl']
        print(f"{result['date']}:")
        print(f"  Signals: {result['signals']}")
        print(f"  P&L: ${result['total_pl']:+,.2f}")
        print()
    
    print(f"{'─'*80}")
    print(f"TOTAL MISSED P&L: ${total_missed_pl:+,.2f}")
    print(f"{'─'*80}\n")

if __name__ == '__main__':
    main()
