"""
Sampled Backtest: Production vs Relaxed (Every 3rd Month)
Fast comparison using representative sample
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
import glob
from datetime import datetime
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

def calculate_options_pnl(entry: float, exit: float, direction: str, risk_amt: float, atr: float) -> float:
    """Calculate realistic 0DTE ITM options P&L."""
    if direction == 'LONG':
        move_atr = (exit - entry) / atr
    else:
        move_atr = (entry - exit) / atr
    
    # ITM options ~120% delta, cap losses at -100%
    pnl_multiple = move_atr * 1.2
    if pnl_multiple < -1.0:
        pnl_multiple = -1.0
    
    return risk_amt * pnl_multiple

def run_backtest(displacement: float, name: str):
    """Run backtest for one configuration."""
    print(f"\n{'='*80}")
    print(f"BACKTESTING: {name}")
    print(f"{'='*80}\n")
    
    # Load data - SAMPLE EVERY 3RD MONTH
    all_files = sorted(glob.glob('data/polygon_downloads/QQQ_2024_*.csv'))
    all_files += sorted(glob.glob('data/polygon_downloads/QQQ_2025_*.csv'))
    csv_files = all_files[::3]  # Every 3rd month
    
    print(f"Sampling {len(csv_files)} of {len(all_files)} monthly files (every 3rd month)...\n")
    
    balance = 25000
    peak_balance = balance
    max_dd = 0
    trades = []
    
    for file_num, file in enumerate(csv_files, 1):
        # Load month
        df = pd.read_csv(file)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        
        # Group by day
        df['date'] = df['timestamp'].dt.date
        days = sorted(df['date'].unique())
        
        print(f"[{file_num}/{len(csv_files)}] {file.split('/')[-1]}: {len(days)} days", end=' ')
        
        day_signals = 0
        for date in days:
            day_df = df[df['date'] == date].copy().reset_index(drop=True)
            
            if len(day_df) < 50:
                continue
            
            # Detect signals
            day_df['atr'] = calculate_atr(day_df)
            day_df = label_sessions(day_df)
            day_df = add_session_highs_lows(day_df)
            day_df = detect_all_structures(day_df, displacement_threshold=displacement)
            
            # Find confluence signals
            for i in range(len(day_df) - 6):
                signal = None
                
                # Bullish
                if day_df.iloc[i]['sweep_bullish']:
                    window = day_df.iloc[i:i+7]
                    if window['displacement_bullish'].any() and window['mss_bullish'].any():
                        signal = {
                            'date': date,
                            'direction': 'LONG',
                            'entry': day_df.iloc[i]['close'],
                            'atr': day_df.iloc[i]['atr'],
                            'idx': i
                        }
                
                # Bearish
                if day_df.iloc[i]['sweep_bearish']:
                    window = day_df.iloc[i:i+7]
                    if window['displacement_bearish'].any() and window['mss_bearish'].any():
                        signal = {
                            'date': date,
                            'direction': 'SHORT',
                            'entry': day_df.iloc[i]['close'],
                            'atr': day_df.iloc[i]['atr'],
                            'idx': i
                        }
                
                if signal:
                    # Simulate trade
                    future = day_df.iloc[signal['idx']+1:signal['idx']+61]
                    
                    if signal['direction'] == 'LONG':
                        target = signal['entry'] + (5.0 * signal['atr'])
                        hits = future[future['high'] >= target]
                    else:
                        target = signal['entry'] - (5.0 * signal['atr'])
                        hits = future[future['low'] <= target]
                    
                    if len(hits) > 0:
                        exit_price = target
                        hit = True
                    else:
                        exit_price = future.iloc[-1]['close'] if len(future) > 0 else signal['entry']
                        hit = False
                    
                    # Calculate P&L (FIXED RISK - NO COMPOUNDING)
                    risk_amt = 1250  # Fixed 5% of $25K starting balance
                    pnl = calculate_options_pnl(signal['entry'], exit_price, signal['direction'], risk_amt, signal['atr'])
                    
                    balance += pnl
                    peak_balance = max(peak_balance, balance)
                    dd = (peak_balance - balance) / peak_balance
                    max_dd = max(max_dd, dd)
                    
                    trades.append({
                        'date': date,
                        'direction': signal['direction'],
                        'entry': signal['entry'],
                        'exit': exit_price,
                        'target': target,
                        'hit': hit,
                        'pnl': pnl,
                        'balance': balance
                    })
                    
                    day_signals += 1
        
        print(f"→ {day_signals} signals")
    
    # Results
    if not trades:
        print("\n❌ No trades generated\n")
        return None
    
    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df['hit'] == True]
    losses = trades_df[trades_df['hit'] == False]
    
    print(f"\n{'='*80}")
    print(f"RESULTS: {name}")
    print(f"{'='*80}\n")
    
    print(f"📊 PERFORMANCE:")
    print(f"   Total Trades:    {len(trades_df):,}")
    print(f"   Winners:         {len(wins):,} ({len(wins)/len(trades_df)*100:.1f}%)")
    print(f"   Losers:          {len(losses):,}")
    
    print(f"\n💰 P&L:")
    print(f"   Total P&L:       ${trades_df['pnl'].sum():,.2f}")
    print(f"   Avg Win:         ${wins['pnl'].mean():,.2f}" if len(wins) > 0 else "   Avg Win:         $0.00")
    print(f"   Avg Loss:        ${losses['pnl'].mean():,.2f}" if len(losses) > 0 else "   Avg Loss:        $0.00")
    
    if len(losses) > 0 and losses['pnl'].sum() != 0:
        pf = abs(wins['pnl'].sum() / losses['pnl'].sum())
        print(f"   Profit Factor:   {pf:.2f}")
    
    print(f"\n📈 ACCOUNT:")
    print(f"   Starting:        $25,000.00")
    print(f"   Ending:          ${balance:,.2f}")
    print(f"   Total Return:    {(balance - 25000) / 25000 * 100:+.1f}%")
    print(f"   Max Drawdown:    {max_dd*100:.2f}%")
    
    return {
        'name': name,
        'displacement': displacement,
        'trades': len(trades_df),
        'wins': len(wins),
        'win_rate': len(wins)/len(trades_df)*100,
        'total_pnl': trades_df['pnl'].sum(),
        'final_balance': balance,
        'return_pct': (balance - 25000) / 25000 * 100,
        'max_dd': max_dd * 100
    }

def main():
    print("\n" + "="*80)
    print("SAMPLED BACKTEST: PRODUCTION vs RELAXED (Every 3rd Month)")
    print("="*80)
    print("\nPeriod: Jan 2024 - Oct 2025 (sampled)")
    print("Symbol: QQQ")
    print("Account: $25,000")
    print("Risk: $1,250 per trade (FIXED - NO COMPOUNDING)")
    print("Options: 1-strike ITM 0DTE")
    print("Target: 5x ATR")
    print("Max Hold: 60 minutes")
    print("="*80)
    
    start = datetime.now()
    
    # Run both
    prod = run_backtest(1.0, "PRODUCTION (1.0% displacement)")
    relax = run_backtest(0.75, "RELAXED (0.75% displacement)")
    
    elapsed = (datetime.now() - start).total_seconds()
    
    # Compare
    if prod and relax:
        print(f"\n{'='*80}")
        print("COMPARISON")
        print(f"{'='*80}\n")
        
        print(f"{'Metric':25s} {'Production':>15s} {'Relaxed':>15s} {'Difference':>15s}")
        print(f"{'-'*80}")
        print(f"{'Total Trades':25s} {prod['trades']:>15,d} {relax['trades']:>15,d} {relax['trades']-prod['trades']:>15,d}")
        print(f"{'Win Rate':25s} {prod['win_rate']:>14.1f}% {relax['win_rate']:>14.1f}% {relax['win_rate']-prod['win_rate']:>14.1f}%")
        print(f"{'Total Return':25s} {prod['return_pct']:>14.1f}% {relax['return_pct']:>14.1f}% {relax['return_pct']-prod['return_pct']:>14.1f}%")
        print(f"{'Max Drawdown':25s} {prod['max_dd']:>14.2f}% {relax['max_dd']:>14.2f}% {relax['max_dd']-prod['max_dd']:>14.2f}%")
        print(f"{'Final Balance':25s} ${prod['final_balance']:>14,.2f} ${relax['final_balance']:>14,.2f} ${relax['final_balance']-prod['final_balance']:>14,.2f}")
        
        print(f"\n⏱️  Backtest completed in {elapsed:.1f} seconds")
        print("\n⚠️  NOTE: This is a SAMPLED backtest (every 3rd month)")
        print("   For full validation, run all 22 months")

if __name__ == '__main__':
    main()
