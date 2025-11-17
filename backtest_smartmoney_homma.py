"""
Backtest Smart Money + Homma MTF Strategy

Tests all 8 HTF/LTF combinations on QQQ
"""

import pandas as pd
import numpy as np
from engine.data_provider import CSVDataProvider
from strategies.smartmoney_homma_mtf import SmartMoneyHommaMTF, resample_to_timeframe, MTFSignal
from typing import List


def run_backtest(signals: List[MTFSignal], df_ltf: pd.DataFrame, max_hold_bars: int = 120):
    trades = []
    
    for sig in signals:
        sig_idx = df_ltf[df_ltf['timestamp'] == sig.timestamp].index
        if len(sig_idx) == 0:
            continue
        
        sig_idx = sig_idx[0]
        
        future = df_ltf.iloc[sig_idx:sig_idx + max_hold_bars]
        
        if len(future) < 2:
            continue
        
        entry = sig.entry_price
        stop = sig.stop_loss
        target = sig.target
        
        hit_target = False
        hit_stop = False
        exit_price = entry
        exit_bar = len(future) - 1
        
        for i, row in enumerate(future.iterrows()):
            idx, bar = row
            
            if sig.direction == 'long':
                if bar['high'] >= target:
                    hit_target = True
                    exit_price = target
                    exit_bar = i
                    break
                
                if bar['low'] <= stop:
                    hit_stop = True
                    exit_price = stop
                    exit_bar = i
                    break
            
            else:
                if bar['low'] <= target:
                    hit_target = True
                    exit_price = target
                    exit_bar = i
                    break
                
                if bar['high'] >= stop:
                    hit_stop = True
                    exit_price = stop
                    exit_bar = i
                    break
        
        if not hit_target and not hit_stop:
            exit_price = future.iloc[-1]['close']
        
        if sig.direction == 'long':
            pnl = exit_price - entry
            risk = entry - stop
        else:
            pnl = entry - exit_price
            risk = stop - entry
        
        r_multiple = pnl / risk if risk > 0 else 0
        
        trades.append({
            'entry_time': sig.timestamp,
            'direction': sig.direction,
            'entry': entry,
            'exit': exit_price,
            'target': target,
            'stop': stop,
            'pnl': pnl,
            'r': r_multiple,
            'hit_target': hit_target,
            'hit_stop': hit_stop,
            'exit_bar': exit_bar,
            'zone_pattern': sig.zone_pattern,
            'homma_pattern': sig.homma_pattern,
            'htf': sig.htf,
            'ltf': sig.ltf,
            'rr': sig.reward_risk
        })
    
    return pd.DataFrame(trades)


def calculate_metrics(df_trades: pd.DataFrame):
    if len(df_trades) == 0:
        return {
            'total_trades': 0,
            'win_rate': 0,
            'avg_r': 0,
            'profit_factor': 0,
            'total_pnl': 0,
            'sharpe': 0
        }
    
    total = len(df_trades)
    wins = len(df_trades[df_trades['r'] > 0])
    wr = wins / total if total > 0 else 0
    
    avg_r = df_trades['r'].mean()
    
    winning_r = df_trades[df_trades['r'] > 0]['r'].sum()
    losing_r = abs(df_trades[df_trades['r'] < 0]['r'].sum())
    pf = winning_r / losing_r if losing_r > 0 else 0
    
    total_pnl = df_trades['pnl'].sum()
    
    std_r = df_trades['r'].std()
    sharpe = avg_r / std_r if std_r > 0 else 0
    
    return {
        'total_trades': total,
        'win_rate': wr,
        'avg_r': avg_r,
        'profit_factor': pf,
        'total_pnl': total_pnl,
        'sharpe': sharpe
    }


def main():
    import sys
    
    data_file = sys.argv[1] if len(sys.argv) > 1 else 'data/QQQ_1m_real.csv'
    
    print("=" * 90)
    print("SMART MONEY + HOMMA MTF BACKTEST")
    print(f"Testing all 8 HTF/LTF combinations on {data_file}")
    print("=" * 90)
    print()
    
    provider = CSVDataProvider(data_file)
    df_1m = provider.load_bars()
    
    htf_list = ['30min', '1h', '2h', '4h']
    ltf_list = ['3min', '5min']
    
    results = []
    
    for htf in htf_list:
        for ltf in ltf_list:
            print(f"Testing HTF={htf}, LTF={ltf}...")
            
            df_htf = resample_to_timeframe(df_1m, htf)
            df_ltf = resample_to_timeframe(df_1m, ltf)
            
            strategy = SmartMoneyHommaMTF(htf=htf, ltf=ltf, min_reward_risk=2.0)
            
            signals = strategy.generate_signals(df_htf, df_ltf)
            
            df_trades = run_backtest(signals, df_ltf, max_hold_bars=120)
            
            metrics = calculate_metrics(df_trades)
            metrics['htf'] = htf
            metrics['ltf'] = ltf
            
            results.append(metrics)
            
            print(f"  Trades: {metrics['total_trades']}")
            print(f"  WR: {metrics['win_rate']*100:.1f}%")
            print(f"  Avg R: {metrics['avg_r']:.2f}")
            print(f"  PF: {metrics['profit_factor']:.2f}")
            print(f"  Sharpe: {metrics['sharpe']:.2f}")
            print(f"  Total P&L: ${metrics['total_pnl']:.2f}")
            print()
    
    print("=" * 90)
    print("SUMMARY - BEST PERFORMERS")
    print("=" * 90)
    
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('sharpe', ascending=False)
    
    print(df_results.to_string(index=False))
    print()
    
    print("=" * 90)
    print("EVALUATION CRITERIA:")
    print("  - WR ≥ 55-60%")
    print("  - Avg R ≥ +0.2")
    print("  - PF ≥ 1.5")
    print("  - Sharpe ≥ 1.0 (good), ≥ 2.0 (excellent)")
    print("=" * 90)
    
    viable = df_results[
        (df_results['win_rate'] >= 0.55) &
        (df_results['avg_r'] >= 0.2) &
        (df_results['profit_factor'] >= 1.5) &
        (df_results['sharpe'] >= 1.0)
    ]
    
    if len(viable) > 0:
        print()
        print("✅ VIABLE COMBINATIONS:")
        print(viable[['htf', 'ltf', 'total_trades', 'win_rate', 'avg_r', 'sharpe']].to_string(index=False))
    else:
        print()
        print("⚠️  No combinations met all criteria - strategy needs refinement")


if __name__ == '__main__':
    main()
