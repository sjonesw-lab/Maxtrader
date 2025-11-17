"""
Smart Money Parameter Sensitivity Analysis
Tests different parameter combinations to optimize trade frequency vs quality
"""
import pandas as pd
import numpy as np
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.smartmoney_homma_mtf import SmartMoneyHommaMTF


def resample_to_timeframe(df_1m, timeframe):
    """Resample 1-minute bars to target timeframe"""
    df = df_1m.copy()
    df = df.set_index('timestamp')
    
    resampled = df.resample(timeframe).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()
    
    return resampled


def simulate_trades(signals, df_1m):
    """Simulate trade execution"""
    trades = []
    
    for signal in signals:
        entry_price = signal.entry_price
        stop_loss = signal.stop_loss
        take_profit = signal.target
        direction = signal.direction
        
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        
        # Simulate execution over next 60 bars
        entry_time = signal.timestamp
        future_bars = df_1m[df_1m['timestamp'] > entry_time].head(60)
        
        if future_bars.empty:
            continue
        
        hit_tp = False
        hit_sl = False
        
        for _, bar in future_bars.iterrows():
            if direction == 'long':
                if bar['high'] >= take_profit:
                    hit_tp = True
                    break
                elif bar['low'] <= stop_loss:
                    hit_sl = True
                    break
            else:  # short
                if bar['low'] <= take_profit:
                    hit_tp = True
                    break
                elif bar['high'] >= stop_loss:
                    hit_sl = True
                    break
        
        if hit_tp:
            pnl = reward
            r_multiple = reward / risk
        elif hit_sl:
            pnl = -risk
            r_multiple = -1.0
        else:
            # Hold to expiry
            exit_price = future_bars.iloc[-1]['close']
            if direction == 'long':
                pnl = exit_price - entry_price
            else:
                pnl = entry_price - exit_price
            r_multiple = pnl / risk
        
        trades.append({
            'pnl': pnl,
            'r_multiple': r_multiple
        })
    
    return pd.DataFrame(trades) if trades else pd.DataFrame()


def test_parameter_set(df_1m, min_impulse_pct, min_reward_risk, htf='1h', ltf='5min'):
    """Test a single parameter combination"""
    df_htf = resample_to_timeframe(df_1m, htf)
    df_ltf = resample_to_timeframe(df_1m, ltf)
    
    # Create custom strategy with modified parameters
    strategy = SmartMoneyHommaMTF(htf=htf, ltf=ltf, min_reward_risk=min_reward_risk)
    
    # Temporarily patch the min_impulse_pct in zone detector
    original_min_impulse = strategy.zone_detector.min_impulse_pct
    strategy.zone_detector.min_impulse_pct = min_impulse_pct
    
    signals = strategy.generate_signals(df_htf, df_ltf)
    
    # Restore original
    strategy.zone_detector.min_impulse_pct = original_min_impulse
    
    if len(signals) == 0:
        return {
            'min_impulse_pct': min_impulse_pct,
            'min_reward_risk': min_reward_risk,
            'zones_detected': 0,
            'trades': 0,
            'win_rate': 0,
            'avg_r': 0,
            'profit_factor': 0,
            'sharpe': 0,
            'total_pnl': 0
        }
    
    # Simulate trades
    trades_df = simulate_trades(signals, df_1m)
    
    if trades_df.empty:
        return {
            'min_impulse_pct': min_impulse_pct,
            'min_reward_risk': min_reward_risk,
            'zones_detected': len(signals),
            'trades': 0,
            'win_rate': 0,
            'avg_r': 0,
            'profit_factor': 0,
            'sharpe': 0,
            'total_pnl': 0
        }
    
    # Calculate metrics
    wins = trades_df[trades_df['r_multiple'] > 0]
    losses = trades_df[trades_df['r_multiple'] < 0]
    
    win_rate = len(wins) / len(trades_df) if len(trades_df) > 0 else 0
    avg_r = trades_df['r_multiple'].mean()
    
    total_wins = wins['pnl'].sum() if len(wins) > 0 else 0
    total_losses = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    sharpe = (trades_df['r_multiple'].mean() / trades_df['r_multiple'].std()) if trades_df['r_multiple'].std() > 0 else 0
    
    return {
        'min_impulse_pct': min_impulse_pct,
        'min_reward_risk': min_reward_risk,
        'zones_detected': len(signals),
        'trades': len(trades_df),
        'win_rate': win_rate,
        'avg_r': avg_r,
        'profit_factor': profit_factor,
        'sharpe': sharpe,
        'total_pnl': total_pnl
    }


def main():
    print("="*90)
    print("SMART MONEY PARAMETER SENSITIVITY ANALYSIS")
    print("Testing QQQ (Aug 18 - Nov 14, 2025)")
    print("="*90)
    
    # Load QQQ data
    df_1m = pd.read_csv('data/multi_instrument/QQQ_1m_2025-08-18_2025-11-14.csv')
    df_1m['timestamp'] = pd.to_datetime(df_1m['timestamp'])
    print(f"\nLoaded {len(df_1m):,} bars")
    
    # Parameter grid
    impulse_params = [0.003, 0.0025, 0.002, 0.0015]  # 0.3%, 0.25%, 0.2%, 0.15%
    rr_params = [2.0, 1.75, 1.5]
    
    results = []
    
    print("\nTesting parameter combinations...")
    print(f"{'Impulse %':<12} {'R:R':<8} {'Zones':<8} {'Trades':<8} {'WR':<8} {'Avg R':<10} {'PF':<10} {'Sharpe':<10}")
    print("-" * 90)
    
    for impulse in impulse_params:
        for rr in rr_params:
            result = test_parameter_set(df_1m, impulse, rr)
            results.append(result)
            
            print(f"{impulse*100:<12.2f} {rr:<8.2f} {result['zones_detected']:<8} {result['trades']:<8} "
                  f"{result['win_rate']*100:<8.1f} {result['avg_r']:<10.2f} "
                  f"{result['profit_factor']:<10.2f} {result['sharpe']:<10.2f}")
    
    results_df = pd.DataFrame(results)
    
    # Find best by different criteria
    print("\n" + "="*90)
    print("BEST PERFORMERS BY CRITERIA")
    print("="*90)
    
    # Best by trade frequency (while maintaining quality)
    quality_filtered = results_df[
        (results_df['win_rate'] >= 0.50) & 
        (results_df['avg_r'] >= 0.5) &
        (results_df['trades'] > 0)
    ]
    
    if not quality_filtered.empty:
        best_frequency = quality_filtered.loc[quality_filtered['trades'].idxmax()]
        print("\nBest Trade Frequency (WR≥50%, Avg R≥0.5):")
        print(f"  Impulse: {best_frequency['min_impulse_pct']*100:.2f}%")
        print(f"  R:R: {best_frequency['min_reward_risk']:.2f}")
        print(f"  Trades: {best_frequency['trades']}")
        print(f"  WR: {best_frequency['win_rate']*100:.1f}%")
        print(f"  Avg R: {best_frequency['avg_r']:.2f}")
        print(f"  Sharpe: {best_frequency['sharpe']:.2f}")
        print(f"  Monthly: {best_frequency['trades']/3:.1f} trades/month")
    
    # Best by Sharpe ratio
    sharpe_filtered = results_df[results_df['trades'] >= 2]
    if not sharpe_filtered.empty:
        best_sharpe = sharpe_filtered.loc[sharpe_filtered['sharpe'].idxmax()]
        print("\nBest Sharpe Ratio (min 2 trades):")
        print(f"  Impulse: {best_sharpe['min_impulse_pct']*100:.2f}%")
        print(f"  R:R: {best_sharpe['min_reward_risk']:.2f}")
        print(f"  Trades: {best_sharpe['trades']}")
        print(f"  Sharpe: {best_sharpe['sharpe']:.2f}")
    
    # Best overall (balanced)
    if not quality_filtered.empty:
        quality_filtered['score'] = (
            quality_filtered['trades'] * 0.4 +  # 40% weight on frequency
            quality_filtered['sharpe'] * 10 * 0.3 +  # 30% weight on Sharpe
            quality_filtered['win_rate'] * 100 * 0.3  # 30% weight on WR
        )
        best_overall = quality_filtered.loc[quality_filtered['score'].idxmax()]
        print("\nBest Overall (Balanced Score):")
        print(f"  Impulse: {best_overall['min_impulse_pct']*100:.2f}%")
        print(f"  R:R: {best_overall['min_reward_risk']:.2f}")
        print(f"  Trades: {best_overall['trades']}")
        print(f"  WR: {best_overall['win_rate']*100:.1f}%")
        print(f"  Avg R: {best_overall['avg_r']:.2f}")
        print(f"  Sharpe: {best_overall['sharpe']:.2f}")
    
    print("\n" + "="*90)
    print("RECOMMENDATION")
    print("="*90)
    
    max_trades = results_df['trades'].max()
    print(f"\nMaximum trades achieved: {max_trades} (over 90 days)")
    print(f"Monthly frequency: {max_trades/3:.1f} trades/month")
    
    if max_trades >= 15:
        print("✓ Target frequency MET (≥15 trades/90 days on single instrument)")
        print("  → Proceed to multi-instrument testing")
    else:
        print(f"✗ Target frequency NOT MET ({max_trades} < 15 trades/90 days)")
        print(f"  → Need {15-max_trades} more trades to reach target")
        print("\nOptions:")
        print("  1. Test on more instruments (expand from 6 to 10-15)")
        print("  2. Test longer historical periods (12-24 months)")
        print("  3. Consider hybrid integration with Wave-Renko")
        print("  4. Defer to Phase 2 and focus on Runtime Safety Layer")


if __name__ == '__main__':
    main()
