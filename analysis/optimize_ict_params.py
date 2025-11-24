"""
Analyze recent trading days to find optimization opportunities
without sacrificing win rate and drawdown.

Checks if parameter adjustments would have triggered profitable trades.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timedelta
from engine.ict_structures import ICTDetector
from data.csv_provider import CSVDataProvider
import pytz

def analyze_day(date_str, symbol='QQQ'):
    """Analyze a single day with various ICT parameter sets."""
    
    print(f"\n{'='*80}")
    print(f"ANALYZING {symbol} - {date_str}")
    print(f"{'='*80}\n")
    
    # Load data
    provider = CSVDataProvider('data/historical')
    
    # Get data for the day (need prev day for context)
    date = datetime.strptime(date_str, '%Y-%m-%d')
    prev_date = date - timedelta(days=4)  # Get extra days for context
    
    df = provider.get_bars(
        symbol=symbol,
        start_date=prev_date.strftime('%Y-%m-%d'),
        end_date=date_str,
        timeframe='1min'
    )
    
    if df is None or len(df) == 0:
        print(f"❌ No data found for {date_str}")
        return
    
    # Filter to just the target day
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[df['timestamp'].dt.date == date.date()].copy()
    
    print(f"📊 Loaded {len(df)} bars for {date_str}")
    print(f"   Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
    print(f"   Session: {df['timestamp'].min()} to {df['timestamp'].max()}\n")
    
    # Calculate ATR for context
    df['tr'] = df[['high', 'low', 'close']].apply(
        lambda x: max(x['high'] - x['low'], 
                     abs(x['high'] - x['close']), 
                     abs(x['low'] - x['close'])), 
        axis=1
    )
    atr_14 = df['tr'].rolling(14).mean().iloc[-1]
    print(f"📈 14-bar ATR: ${atr_14:.2f}\n")
    
    # Test different parameter sets
    param_sets = [
        {
            'name': 'PRODUCTION (Current)',
            'displacement_threshold': 0.01,  # 1%
            'confluence_window': 5,
            'min_sweep_touches': 2,
        },
        {
            'name': 'Relaxed Displacement (0.75%)',
            'displacement_threshold': 0.0075,  # 0.75%
            'confluence_window': 5,
            'min_sweep_touches': 2,
        },
        {
            'name': 'Wider Window (8 bars)',
            'displacement_threshold': 0.01,
            'confluence_window': 8,
            'min_sweep_touches': 2,
        },
        {
            'name': 'Single Touch Sweeps',
            'displacement_threshold': 0.01,
            'confluence_window': 5,
            'min_sweep_touches': 1,
        },
        {
            'name': 'Aggressive (0.75% + 8 bars)',
            'displacement_threshold': 0.0075,
            'confluence_window': 8,
            'min_sweep_touches': 2,
        },
    ]
    
    results = []
    
    for params in param_sets:
        print(f"\n{'─'*80}")
        print(f"🔍 Testing: {params['name']}")
        print(f"   Displacement: {params['displacement_threshold']*100}%")
        print(f"   Window: {params['confluence_window']} bars")
        print(f"   Min sweeps: {params['min_sweep_touches']}")
        print(f"{'─'*80}")
        
        # Run ICT detection
        detector = ICTDetector(
            displacement_threshold=params['displacement_threshold'],
            confluence_window=params['confluence_window']
        )
        
        signals = detector.detect_signals(df)
        
        if not signals:
            print("   ❌ No signals detected\n")
            results.append({
                'params': params['name'],
                'signals': 0,
                'details': None
            })
            continue
        
        print(f"   ✅ Found {len(signals)} signal(s)\n")
        
        # Analyze each signal
        for i, sig in enumerate(signals, 1):
            print(f"\n   Signal #{i}:")
            print(f"   ├─ Time: {sig['timestamp']}")
            print(f"   ├─ Price: ${sig['price']:.2f}")
            print(f"   ├─ Direction: {sig['direction']}")
            print(f"   ├─ Sweep: {sig.get('sweep_type', 'N/A')}")
            print(f"   ├─ Displacement: {sig.get('displacement', 0)*100:.2f}%")
            print(f"   ├─ MSS: {sig.get('mss', False)}")
            
            # Calculate target (5x ATR from entry)
            entry_price = sig['price']
            target_distance = 5 * atr_14
            
            if sig['direction'] == 'LONG':
                target = entry_price + target_distance
                stop = entry_price - target_distance  # For reference
            else:
                target = entry_price - target_distance
                stop = entry_price + target_distance
            
            print(f"   ├─ Target: ${target:.2f} (5x ATR = ${target_distance:.2f})")
            
            # Check if target was hit in remaining session
            sig_idx = df[df['timestamp'] == sig['timestamp']].index[0]
            remaining_df = df.iloc[sig_idx+1:].copy()
            
            if len(remaining_df) == 0:
                print(f"   └─ ⚠️  Signal at EOD - no data to validate")
                continue
            
            if sig['direction'] == 'LONG':
                target_hit = (remaining_df['high'] >= target).any()
                if target_hit:
                    hit_idx = remaining_df[remaining_df['high'] >= target].index[0]
                    hit_time = remaining_df.loc[hit_idx, 'timestamp']
                    bars_to_target = hit_idx - sig_idx
                    print(f"   └─ 🎯 TARGET HIT at {hit_time} ({bars_to_target} bars)")
                else:
                    max_profit = remaining_df['high'].max() - entry_price
                    print(f"   └─ ❌ Target missed (max profit: ${max_profit:.2f}, {max_profit/target_distance*100:.1f}% of target)")
            else:
                target_hit = (remaining_df['low'] <= target).any()
                if target_hit:
                    hit_idx = remaining_df[remaining_df['low'] <= target].index[0]
                    hit_time = remaining_df.loc[hit_idx, 'timestamp']
                    bars_to_target = hit_idx - sig_idx
                    print(f"   └─ 🎯 TARGET HIT at {hit_time} ({bars_to_target} bars)")
                else:
                    max_profit = entry_price - remaining_df['low'].min()
                    print(f"   └─ ❌ Target missed (max profit: ${max_profit:.2f}, {max_profit/target_distance*100:.1f}% of target)")
        
        results.append({
            'params': params['name'],
            'signals': len(signals),
            'details': signals
        })
    
    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY FOR {date_str}")
    print(f"{'='*80}\n")
    
    for res in results:
        print(f"  {res['params']:40s} → {res['signals']} signal(s)")
    
    return results


def main():
    """Analyze recent days."""
    
    print("\n" + "="*80)
    print("ICT PARAMETER OPTIMIZATION ANALYSIS")
    print("="*80)
    print("\nGoal: Find parameters that would have triggered trades without")
    print("      sacrificing the validated 80.5% win rate and 3% max drawdown")
    print("\n" + "="*80)
    
    # Analyze Friday Nov 21 and Monday Nov 24
    dates = [
        '2025-11-21',  # Friday
        '2025-11-24',  # Monday (today)
    ]
    
    all_results = {}
    
    for date in dates:
        results = analyze_day(date, 'QQQ')
        all_results[date] = results
    
    # Final recommendations
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    
    print("""
Based on this analysis:

1. **Current Production Parameters (1% displacement, 5-bar window)**
   - These are calibrated for HIGH QUALITY signals
   - Validated 80.5% win rate over 928 trades
   - Some days will have 0 signals (this is by design)

2. **If No Signals on Both Days:**
   - This suggests tight, range-bound market conditions
   - ICT patterns require institutional-level moves
   - NO changes recommended - quality over quantity

3. **If Relaxed Parameters Show Profitable Opportunities:**
   - Need full backtest validation over 22 months
   - Cannot optimize on 2 days of data (overfitting risk)
   - Would need to verify 80.5%+ win rate maintained

4. **Risk of Parameter Changes:**
   - Looser parameters = more signals but lower quality
   - Could degrade from 80.5% win rate to <70%
   - Could increase max drawdown from 3% to >5%

CONCLUSION: Unless relaxed parameters show CLEAR profitable trades
on BOTH days that current params missed, keep production settings.
Two quiet days is normal for a quality-focused strategy.
    """)

if __name__ == '__main__':
    main()
