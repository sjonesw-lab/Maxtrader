"""
ACCURATE 22-Month Backtest using Original ICT Detection
Uses actual engine/ict_structures.py and engine/sessions_liquidity.py
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
import glob
from datetime import datetime

# Import original functions
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

def run_backtest(displacement: float, name: str):
    """Run backtest using original ICT detection."""
    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"{'='*70}")
    
    # Load 2024-2025 files only (22 months)
    files = sorted(glob.glob('data/polygon_downloads/QQQ_2024_*.csv'))
    files += sorted(glob.glob('data/polygon_downloads/QQQ_2025_*.csv'))
    print(f"Loading {len(files)} files...")
    
    all_trades = []
    
    for fnum, file in enumerate(files, 1):
        # Load month data
        df = pd.read_csv(file)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York')
        df['date'] = df['timestamp'].dt.date
        
        month_signals = 0
        days = sorted(df['date'].unique())
        
        for date in days:
            day_df = df[df['date'] == date].copy().reset_index(drop=True)
            if len(day_df) < 50:
                continue
            
            # Apply original ICT detection
            day_df = label_sessions(day_df)
            day_df = add_session_highs_lows(day_df)
            day_df = detect_all_structures(day_df, displacement_threshold=displacement)
            
            # Find confluence signals (sweep + displacement + MSS within 7 bars)
            for i in range(len(day_df) - 7):
                if pd.isna(day_df.iloc[i]['atr']) or day_df.iloc[i]['atr'] == 0:
                    continue
                
                # Check for bullish sweep
                if day_df.iloc[i]['sweep_bullish']:
                    window = day_df.iloc[i:i+7]
                    if window['displacement_bullish'].any() and window['mss_bullish'].any():
                        # LONG signal
                        entry = day_df.iloc[i]['close']
                        atr = day_df.iloc[i]['atr']
                        target = entry + (5.0 * atr)
                        
                        # Check next 60 bars for target
                        future = day_df.iloc[i+1:i+61]
                        hit = (future['high'] >= target).any() if len(future) > 0 else False
                        exit_price = target if hit else (future.iloc[-1]['close'] if len(future) > 0 else entry)
                        
                        # Calculate P&L
                        move_atr = (exit_price - entry) / atr
                        pnl_mult = min(move_atr * 1.2, 6.0)  # Cap at 6x (5x ATR * 1.2 delta)
                        if pnl_mult < -1.0:
                            pnl_mult = -1.0
                        pnl = 1250 * pnl_mult
                        
                        all_trades.append({'hit': hit, 'pnl': pnl})
                        month_signals += 1
                
                # Check for bearish sweep
                if day_df.iloc[i]['sweep_bearish']:
                    window = day_df.iloc[i:i+7]
                    if window['displacement_bearish'].any() and window['mss_bearish'].any():
                        # SHORT signal
                        entry = day_df.iloc[i]['close']
                        atr = day_df.iloc[i]['atr']
                        target = entry - (5.0 * atr)
                        
                        # Check next 60 bars for target
                        future = day_df.iloc[i+1:i+61]
                        hit = (future['low'] <= target).any() if len(future) > 0 else False
                        exit_price = target if hit else (future.iloc[-1]['close'] if len(future) > 0 else entry)
                        
                        # Calculate P&L
                        move_atr = (entry - exit_price) / atr
                        pnl_mult = min(move_atr * 1.2, 6.0)
                        if pnl_mult < -1.0:
                            pnl_mult = -1.0
                        pnl = 1250 * pnl_mult
                        
                        all_trades.append({'hit': hit, 'pnl': pnl})
                        month_signals += 1
        
        print(f"  [{fnum:2d}/{len(files)}] {file.split('/')[-1]}: {month_signals:4d} signals")
    
    if not all_trades:
        print("❌ No trades")
        return None
    
    # Calculate results
    wins = [t for t in all_trades if t['hit']]
    losses = [t for t in all_trades if not t['hit']]
    total_pnl = sum(t['pnl'] for t in all_trades)
    
    # Calculate drawdown
    balance = 25000
    peak = balance
    max_dd = 0
    for t in all_trades:
        balance += t['pnl']
        peak = max(peak, balance)
        dd = (peak - balance) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    
    print(f"\n📊 RESULTS:")
    print(f"   Trades:     {len(all_trades):,}")
    print(f"   Win Rate:   {len(wins)/len(all_trades)*100:.1f}% ({len(wins):,} wins)")
    print(f"   Total P&L:  ${total_pnl:,.0f}")
    if wins:
        print(f"   Avg Win:    ${np.mean([t['pnl'] for t in wins]):,.0f}")
    if losses:
        print(f"   Avg Loss:   ${np.mean([t['pnl'] for t in losses]):,.0f}")
    print(f"   Max DD:     {max_dd*100:.2f}%")
    print(f"   Final:      ${balance:,.0f} ({(balance-25000)/25000*100:+.1f}%)")
    
    return {
        'trades': len(all_trades),
        'wins': len(wins),
        'win_rate': len(wins)/len(all_trades)*100,
        'pnl': total_pnl,
        'max_dd': max_dd * 100,
        'final': balance
    }

def main():
    print("\n" + "="*70)
    print("ACCURATE 22-MONTH BACKTEST (Original ICT Detection)")
    print("="*70)
    print("QQQ | $25K | $1,250/trade | 5x ATR | 60-min max hold")
    print("Using: engine/ict_structures.py + engine/sessions_liquidity.py")
    
    start = datetime.now()
    
    prod = run_backtest(1.0, "PRODUCTION (1.0x ATR displacement)")
    relax = run_backtest(0.75, "RELAXED (0.75x ATR displacement)")
    
    elapsed = (datetime.now() - start).total_seconds()
    
    if prod and relax:
        print(f"\n{'='*70}")
        print("COMPARISON")
        print(f"{'='*70}")
        print(f"{'':20s} {'PRODUCTION':>15s} {'RELAXED':>15s}")
        print(f"{'-'*70}")
        print(f"{'Trades':20s} {prod['trades']:>15,d} {relax['trades']:>15,d}")
        print(f"{'Win Rate':20s} {prod['win_rate']:>14.1f}% {relax['win_rate']:>14.1f}%")
        print(f"{'Max Drawdown':20s} {prod['max_dd']:>14.2f}% {relax['max_dd']:>14.2f}%")
        print(f"{'Final Balance':20s} ${prod['final']:>13,.0f} ${relax['final']:>13,.0f}")
        
        # Recommendation
        print(f"\n{'='*70}")
        print("RECOMMENDATION")
        print(f"{'='*70}")
        if relax['win_rate'] > prod['win_rate']:
            print(f"✅ RELAXED is better: {relax['win_rate']:.1f}% vs {prod['win_rate']:.1f}% win rate")
        else:
            print(f"✅ PRODUCTION is better: {prod['win_rate']:.1f}% vs {relax['win_rate']:.1f}% win rate")
    
    print(f"\n⏱️  Completed in {elapsed:.0f} seconds")

if __name__ == '__main__':
    main()
