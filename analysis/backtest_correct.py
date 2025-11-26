"""
CORRECT 22-Month Backtest: Using ORIGINAL P&L Calculation
Simple dollar-based P&L (exit - entry), NOT ITM delta multiplier
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
import glob
from datetime import datetime
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

def run_backtest(displacement: float, name: str):
    """Run backtest using ORIGINAL P&L (simple dollars, no multiplier)."""
    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"{'='*70}")
    
    files = sorted(glob.glob('data/polygon_downloads/QQQ_2024_*.csv'))
    files += sorted(glob.glob('data/polygon_downloads/QQQ_2025_*.csv'))
    print(f"Loading {len(files)} files...\n")
    
    all_trades = []
    
    for fnum, file in enumerate(files, 1):
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
            
            day_df = label_sessions(day_df)
            day_df = add_session_highs_lows(day_df)
            day_df = detect_all_structures(day_df, displacement_threshold=displacement)
            
            for i in range(len(day_df) - 7):
                if pd.isna(day_df.iloc[i]['atr']) or day_df.iloc[i]['atr'] == 0:
                    continue
                
                # BULLISH SIGNAL
                if day_df.iloc[i]['sweep_bullish']:
                    window = day_df.iloc[i:i+7]
                    if window['displacement_bullish'].any() and window['mss_bullish'].any():
                        entry = day_df.iloc[i]['close']
                        atr = day_df.iloc[i]['atr']
                        target = entry + (5.0 * atr)
                        
                        future = day_df.iloc[i+1:i+61]
                        hit = (future['high'] >= target).any() if len(future) > 0 else False
                        exit_price = target if hit else (future.iloc[-1]['close'] if len(future) > 0 else entry)
                        
                        # ORIGINAL P&L: Simple dollars, no multiplier
                        pnl = exit_price - entry
                        
                        all_trades.append({'hit': hit, 'pnl': pnl, 'entry': entry, 'exit': exit_price})
                        month_signals += 1
                
                # BEARISH SIGNAL
                if day_df.iloc[i]['sweep_bearish']:
                    window = day_df.iloc[i:i+7]
                    if window['displacement_bearish'].any() and window['mss_bearish'].any():
                        entry = day_df.iloc[i]['close']
                        atr = day_df.iloc[i]['atr']
                        target = entry - (5.0 * atr)
                        
                        future = day_df.iloc[i+1:i+61]
                        hit = (future['low'] <= target).any() if len(future) > 0 else False
                        exit_price = target if hit else (future.iloc[-1]['close'] if len(future) > 0 else entry)
                        
                        # ORIGINAL P&L: Simple dollars, no multiplier
                        pnl = entry - exit_price
                        
                        all_trades.append({'hit': hit, 'pnl': pnl, 'entry': entry, 'exit': exit_price})
                        month_signals += 1
        
        print(f"[{fnum:2d}/{len(files)}] {file.split('/')[-1]}: {month_signals:4d} signals")
    
    if not all_trades:
        print("❌ No trades")
        return None
    
    wins = [t for t in all_trades if t['hit']]
    losses = [t for t in all_trades if not t['hit']]
    total_pnl = sum(t['pnl'] for t in all_trades)
    
    # Calculate equity curve and drawdown
    balance = 25000
    equity = [balance]
    peak = balance
    max_dd = 0
    
    for t in all_trades:
        balance += t['pnl']
        equity.append(balance)
        peak = max(peak, balance)
        dd = (peak - balance) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    
    print(f"\n📊 RESULTS:")
    print(f"   Trades:     {len(all_trades):,}")
    print(f"   Win Rate:   {len(wins)/len(all_trades)*100:.1f}%")
    print(f"   Winners:    {len(wins):,}")
    print(f"   Losers:     {len(losses):,}")
    print(f"   Avg Win:    ${np.mean([t['pnl'] for t in wins]):.2f}" if wins else "")
    print(f"   Avg Loss:   ${np.mean([t['pnl'] for t in losses]):.2f}" if losses else "")
    print(f"   Total P&L:  ${total_pnl:,.2f}")
    print(f"   Max DD:     {max_dd*100:.2f}%")
    print(f"   Final:      ${balance:,.2f}")
    
    return {
        'trades': len(all_trades),
        'wins': len(wins),
        'win_rate': len(wins)/len(all_trades)*100,
        'pnl': total_pnl,
        'max_dd': max_dd * 100,
        'final': balance,
        'equity': equity
    }

print("\n" + "="*70)
print("CORRECT 22-MONTH BACKTEST (Original Simple Dollar P&L)")
print("="*70)

prod = run_backtest(1.0, "PRODUCTION (1.0x ATR displacement)")
relax = run_backtest(0.75, "RELAXED (0.75x ATR displacement)")

if prod and relax:
    print(f"\n{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}")
    print(f"{'':20s} {'PRODUCTION':>15s} {'RELAXED':>15s}")
    print(f"{'-'*70}")
    print(f"{'Trades':20s} {prod['trades']:>15,d} {relax['trades']:>15,d}")
    print(f"{'Win Rate':20s} {prod['win_rate']:>14.1f}% {relax['win_rate']:>14.1f}%")
    print(f"{'Max Drawdown':20s} {prod['max_dd']:>14.2f}% {relax['max_dd']:>14.2f}%")
    print(f"{'Total P&L':20s} ${prod['pnl']:>13,.2f} ${relax['pnl']:>13,.2f}")
    print(f"{'Final Balance':20s} ${prod['final']:>13,.2f} ${relax['final']:>13,.2f}")
