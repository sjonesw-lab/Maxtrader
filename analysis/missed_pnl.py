"""
Analyze missed P&L from system downtime - uses exact same signal logic as auto_trader
"""
import os
import sys
from datetime import datetime, timedelta
import pytz
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.ict_structures import detect_all_structures
from engine.sessions_liquidity import label_sessions, add_session_highs_lows

def detect_signals(df: pd.DataFrame, symbol: str, atr_multiple: float = 5.0):
    """Exact same signal detection as auto_trader"""
    if len(df) == 0:
        return []
    
    df = df.copy()
    
    # Calculate ATR
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()
    
    # Add sessions and detect structures
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_all_structures(df, displacement_threshold=1.0)
    
    signals = []
    
    # Check all bars for signals (need 5 bars lookahead for confluence)
    for i in range(max(0, len(df) - 10), len(df) - 5):
        timestamp = df.iloc[i]['timestamp']
        
        # Bullish signal
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                atr = df.iloc[i].get('atr', 0.5)
                price = df.iloc[i]['close']
                
                signals.append({
                    'symbol': symbol,
                    'timestamp': timestamp,
                    'direction': 'LONG',
                    'price': price,
                    'atr': atr,
                    'target': price + (atr_multiple * atr)
                })
        
        # Bearish signal
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                atr = df.iloc[i].get('atr', 0.5)
                price = df.iloc[i]['close']
                
                signals.append({
                    'symbol': symbol,
                    'timestamp': timestamp,
                    'direction': 'SHORT',
                    'price': price,
                    'atr': atr,
                    'target': price - (atr_multiple * atr)
                })
    
    return signals

def check_target_hit(df: pd.DataFrame, entry_time, entry_price, target_price, direction):
    """Check if target was hit after entry"""
    try:
        entry_idx = df[df['timestamp'] == entry_time].index[0]
    except:
        return False, entry_time
    
    remaining_bars = df.iloc[entry_idx+1:]
    
    for idx, row in remaining_bars.iterrows():
        if direction == 'LONG':
            if row['high'] >= target_price:
                return True, row['timestamp']
        else:  # SHORT
            if row['low'] <= target_price:
                return True, row['timestamp']
    
    return False, entry_time

def analyze_day(date_str, symbol='QQQ'):
    """Analyze what signals would have been generated on a specific day"""
    print(f"\n{'='*80}")
    print(f"ANALYZING: {date_str} ({symbol})")
    print(f"{'='*80}\n")
    
    # Fetch data
    fetcher = PolygonDataFetcher()
    df = fetcher.fetch_stock_bars(symbol, date_str, date_str)
    
    if df is None or len(df) == 0:
        print(f"❌ No data available for {date_str}")
        return None
    
    print(f"✓ Got {len(df)} bars")
    
    # Detect signals
    signals = detect_signals(df, symbol)
    
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
    account_balance = 25000
    risk_pct = 0.05
    risk_amount = account_balance * risk_pct  # $1,250 per trade
    
    trades = []
    total_pl = 0
    
    for i, sig in enumerate(signals, 1):
        direction = sig['direction']
        entry_price = sig['price']
        target_price = sig['target']
        entry_time = sig['timestamp']
        atr = sig['atr']
        
        print(f"\n  Signal #{i}: {direction} @ ${entry_price:.2f}, target ${target_price:.2f}")
        print(f"    Time: {entry_time}")
        print(f"    ATR: ${atr:.2f}, Target: {5.0}x ATR = ${abs(target_price - entry_price):.2f}")
        
        # 1-strike ITM option
        if direction == 'LONG':
            option_type = 'CALL'
            option_strike = entry_price - 1
        else:
            option_type = 'PUT'
            option_strike = entry_price + 1
        
        # Simplified option pricing (intrinsic + rough extrinsic)
        intrinsic = abs(entry_price - option_strike)
        extrinsic = atr * 0.2  # Rough estimate
        option_price = intrinsic + extrinsic
        
        contracts = max(1, int(risk_amount / (option_price * 100)))
        
        # Check if target hit
        target_hit, exit_time = check_target_hit(df, entry_time, entry_price, target_price, direction)
        
        if target_hit:
            # Calculate option profit at target
            exit_intrinsic = abs(target_price - option_strike)
            exit_option_price = exit_intrinsic  # Conservative: assume extrinsic decayed
            option_pl = (exit_option_price - option_price) * contracts * 100
            result = "✅ WIN"
        else:
            # No target hit = assume 50% loss
            option_pl = -risk_amount * 0.5
            result = "❌ NO TARGET"
        
        total_pl += option_pl
        
        trade = {
            'signal_num': i,
            'direction': direction,
            'entry_price': entry_price,
            'target_price': target_price,
            'entry_time': str(entry_time),
            'exit_time': str(exit_time),
            'target_hit': target_hit,
            'option_type': option_type,
            'option_strike': option_strike,
            'contracts': contracts,
            'entry_premium': option_price,
            'pl': option_pl,
            'result': result
        }
        trades.append(trade)
        
        print(f"    Option: {option_type} ${option_strike:.2f}")
        print(f"    Contracts: {contracts}, Entry Premium: ${option_price:.2f}")
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
    print("\n📅 Analyzing YESTERDAY (Thursday)")
    result_yesterday = analyze_day(yesterday)
    if result_yesterday:
        results.append(result_yesterday)
    
    # Analyze today
    print("\n📅 Analyzing TODAY (Friday)")
    result_today = analyze_day(today)
    if result_today:
        results.append(result_today)
    
    # Summary
    print(f"\n\n{'='*80}")
    print("MISSED OPPORTUNITY SUMMARY")
    print(f"{'='*80}\n")
    
    total_missed_pl = 0
    for result in results:
        day_name = "Thursday" if result['date'] == yesterday else "Friday"
        total_missed_pl += result['total_pl']
        print(f"{result['date']} ({day_name}):")
        print(f"  Bars: {result['bars']}")
        print(f"  Signals: {result['signals']}")
        print(f"  P&L: ${result['total_pl']:+,.2f}")
        print()
    
    print(f"{'─'*80}")
    print(f"TOTAL MISSED P&L (2 days): ${total_missed_pl:+,.2f}")
    print(f"{'─'*80}\n")

if __name__ == '__main__':
    main()
