"""
OPTIMIZED 22-Month Backtest: Production vs Relaxed
Vectorized operations, minimal overhead
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
import glob
from datetime import datetime

def calculate_atr_fast(high, low, close, period=14):
    """Vectorized ATR calculation."""
    tr1 = high - low
    tr2 = np.abs(high - close.shift(1))
    tr3 = np.abs(low - close.shift(1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return tr.rolling(window=period).mean()

def detect_signals_vectorized(df, displacement_threshold):
    """Fast vectorized signal detection."""
    n = len(df)
    if n < 20:
        return []
    
    # Pre-calculate arrays
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    atr = df['atr'].values
    
    # Session highs/lows (use rolling 60-bar for simplicity)
    session_high = pd.Series(high).rolling(60, min_periods=1).max().values
    session_low = pd.Series(low).rolling(60, min_periods=1).min().values
    
    # Displacement detection
    pct_moves = np.abs(close[1:] - close[:-1]) / close[:-1] * 100
    pct_moves = np.insert(pct_moves, 0, 0)
    
    signals = []
    
    for i in range(14, n - 61):  # Need ATR and future bars
        if np.isnan(atr[i]) or atr[i] == 0:
            continue
        
        # Check 7-bar window for confluence
        window_end = min(i + 7, n)
        
        # Sweep: price below session low or above session high
        sweep_bear = low[i] < session_low[i-1]
        sweep_bull = high[i] > session_high[i-1]
        
        if not (sweep_bear or sweep_bull):
            continue
        
        # Displacement in window: >threshold% move
        window_pcts = pct_moves[i:window_end]
        has_disp = np.any(window_pcts >= displacement_threshold)
        
        if not has_disp:
            continue
        
        # MSS: close above/below prior bar's high/low
        has_mss_bull = False
        has_mss_bear = False
        for j in range(i, min(i+7, n-1)):
            if close[j] > high[j-1]:
                has_mss_bull = True
            if close[j] < low[j-1]:
                has_mss_bear = True
        
        # Generate signal if confluence
        if sweep_bull and has_disp and has_mss_bull:
            signals.append({
                'idx': i,
                'direction': 'LONG',
                'entry': close[i],
                'atr': atr[i]
            })
        elif sweep_bear and has_disp and has_mss_bear:
            signals.append({
                'idx': i,
                'direction': 'SHORT',
                'entry': close[i],
                'atr': atr[i]
            })
    
    return signals

def simulate_trades(df, signals):
    """Simulate trades from signals."""
    trades = []
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    
    for sig in signals:
        idx = sig['idx']
        entry = sig['entry']
        atr = sig['atr']
        direction = sig['direction']
        
        # Target at 5x ATR
        if direction == 'LONG':
            target = entry + (5.0 * atr)
        else:
            target = entry - (5.0 * atr)
        
        # Check next 60 bars for target hit
        hit = False
        exit_price = entry
        
        for j in range(idx + 1, min(idx + 61, len(df))):
            if direction == 'LONG' and high[j] >= target:
                exit_price = target
                hit = True
                break
            elif direction == 'SHORT' and low[j] <= target:
                exit_price = target
                hit = True
                break
            exit_price = close[j]
        
        # Calculate P&L
        if direction == 'LONG':
            move_atr = (exit_price - entry) / atr
        else:
            move_atr = (entry - exit_price) / atr
        
        pnl_mult = move_atr * 1.2  # ITM options
        if pnl_mult < -1.0:
            pnl_mult = -1.0
        
        pnl = 1250 * pnl_mult  # Fixed $1,250 risk
        
        trades.append({
            'direction': direction,
            'entry': entry,
            'exit': exit_price,
            'hit': hit,
            'pnl': pnl
        })
    
    return trades

def run_backtest(displacement: float, name: str):
    """Run optimized backtest."""
    print(f"\n{'='*70}")
    print(f"{name}")
    print(f"{'='*70}")
    
    # Load ALL files at once
    files = sorted(glob.glob('data/polygon_downloads/QQQ_202*.csv'))
    print(f"Loading {len(files)} files...")
    
    all_trades = []
    total_signals = 0
    
    for fnum, file in enumerate(files, 1):
        df = pd.read_csv(file, usecols=['timestamp', 'open', 'high', 'low', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['date'] = df['timestamp'].dt.date
        
        month_signals = 0
        days = df['date'].unique()
        
        for date in days:
            day_df = df[df['date'] == date].reset_index(drop=True)
            if len(day_df) < 50:
                continue
            
            day_df['atr'] = calculate_atr_fast(day_df['high'], day_df['low'], day_df['close'])
            
            signals = detect_signals_vectorized(day_df, displacement)
            if signals:
                trades = simulate_trades(day_df, signals)
                all_trades.extend(trades)
                month_signals += len(signals)
        
        total_signals += month_signals
        print(f"  [{fnum:2d}/{len(files)}] {file.split('/')[-1]}: {month_signals:3d} signals")
    
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
        dd = (peak - balance) / peak
        max_dd = max(max_dd, dd)
    
    print(f"\n📊 RESULTS:")
    print(f"   Trades:     {len(all_trades):,}")
    print(f"   Win Rate:   {len(wins)/len(all_trades)*100:.1f}% ({len(wins)} wins)")
    print(f"   Total P&L:  ${total_pnl:,.0f}")
    print(f"   Avg Win:    ${np.mean([t['pnl'] for t in wins]):,.0f}" if wins else "")
    print(f"   Avg Loss:   ${np.mean([t['pnl'] for t in losses]):,.0f}" if losses else "")
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
    print("OPTIMIZED 22-MONTH BACKTEST")
    print("="*70)
    print("QQQ | $25K | $1,250/trade | 5x ATR | 60-min max hold")
    
    start = datetime.now()
    
    prod = run_backtest(1.0, "PRODUCTION (1.0% displacement)")
    relax = run_backtest(0.75, "RELAXED (0.75% displacement)")
    
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
    
    print(f"\n⏱️  Completed in {elapsed:.0f} seconds")

if __name__ == '__main__':
    main()
