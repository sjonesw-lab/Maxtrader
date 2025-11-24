"""
Full 22-Month Backtest: Relaxed ICT Parameters (0.75% displacement)

Compares PRODUCTION (1.0% displacement) vs RELAXED (0.75% displacement)
on full QQQ dataset (Jan 2024 - Oct 2025) to validate if relaxed parameters
maintain 80.5%+ win rate and <3% max drawdown.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timedelta
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
import numpy as np
import glob
import os

class RelaxedParamsBacktest:
    """Backtest relaxed ICT parameters on full dataset."""
    
    def __init__(self):
        self.data_dir = 'data/polygon_downloads'
        self.max_hold_minutes = 60
        self.atr_multiple = 5
        self.risk_per_trade = 0.05  # 5% like production
    
    def load_qqq_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load QQQ data from CSV files."""
        # Get all QQQ CSV files
        csv_files = sorted(glob.glob(f"{self.data_dir}/QQQ_*.csv"))
        
        if not csv_files:
            return pd.DataFrame()
        
        # Load and concatenate
        dfs = []
        for file in csv_files:
            try:
                df = pd.read_csv(file)
                dfs.append(df)
            except Exception as e:
                print(f"Warning: Could not load {file}: {e}")
        
        if not dfs:
            return pd.DataFrame()
        
        # Concatenate all data
        full_df = pd.concat(dfs, ignore_index=True)
        
        # Parse timestamp with UTC timezone
        full_df['timestamp'] = pd.to_datetime(full_df['timestamp'], format='mixed', utc=True)
        
        # Filter by date range (convert to UTC timezone-aware)
        start = pd.to_datetime(start_date, utc=True)
        end = pd.to_datetime(end_date, utc=True)
        full_df = full_df[(full_df['timestamp'] >= start) & (full_df['timestamp'] <= end)]
        
        # Sort by timestamp
        full_df = full_df.sort_values('timestamp').reset_index(drop=True)
        
        return full_df
        
    def calculate_atr(self, df: pd.DataFrame, period=14) -> pd.Series:
        """Calculate ATR."""
        df = df.copy()
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        return df['tr'].rolling(window=period).mean()
    
    def detect_signals(self, df: pd.DataFrame, displacement_threshold: float) -> list:
        """Detect ICT signals."""
        if len(df) < 100:
            return []
        
        df = df.copy()
        df['atr'] = self.calculate_atr(df)
        
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_all_structures(df, displacement_threshold=displacement_threshold)
        
        signals = []
        confluence_window = 6  # Production window
        
        for i in range(len(df) - confluence_window):
            # Bullish
            if df.iloc[i]['sweep_bullish']:
                window = df.iloc[i:i+confluence_window+1]
                if window['displacement_bullish'].any() and window['mss_bullish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'timestamp': df.iloc[i]['timestamp'],
                        'index': i,
                        'direction': 'LONG',
                        'price': price,
                        'atr': atr,
                        'target': price + (self.atr_multiple * atr)
                    })
            
            # Bearish
            if df.iloc[i]['sweep_bearish']:
                window = df.iloc[i:i+confluence_window+1]
                if window['displacement_bearish'].any() and window['mss_bearish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'timestamp': df.iloc[i]['timestamp'],
                        'index': i,
                        'direction': 'SHORT',
                        'price': price,
                        'atr': atr,
                        'target': price - (self.atr_multiple * atr)
                    })
        
        return signals
    
    def simulate_trade(self, signal: dict, df: pd.DataFrame, balance: float) -> dict:
        """Simulate trade execution and exit."""
        sig_idx = signal['index']
        remaining = df.iloc[sig_idx+1:].head(self.max_hold_minutes)
        
        if len(remaining) == 0:
            return None
        
        # Calculate position size (5% risk, 1-strike ITM options ~100% leverage)
        risk_amount = balance * self.risk_per_trade
        
        # Check if target hit
        if signal['direction'] == 'LONG':
            target_bars = remaining[remaining['high'] >= signal['target']]
            hit_target = len(target_bars) > 0
            
            if hit_target:
                exit_price = signal['target']
                pnl = risk_amount * (exit_price - signal['price']) / signal['atr'] * 0.2  # Options leverage factor
            else:
                # Time exit at last bar
                exit_price = remaining.iloc[-1]['close']
                pnl = risk_amount * (exit_price - signal['price']) / signal['atr'] * 0.2
        
        else:  # SHORT
            target_bars = remaining[remaining['low'] <= signal['target']]
            hit_target = len(target_bars) > 0
            
            if hit_target:
                exit_price = signal['target']
                pnl = risk_amount * (signal['price'] - exit_price) / signal['atr'] * 0.2
            else:
                exit_price = remaining.iloc[-1]['close']
                pnl = risk_amount * (signal['price'] - exit_price) / signal['atr'] * 0.2
        
        return {
            'timestamp': signal['timestamp'],
            'direction': signal['direction'],
            'entry_price': signal['price'],
            'exit_price': exit_price,
            'target': signal['target'],
            'hit_target': hit_target,
            'pnl': pnl,
            'atr': signal['atr']
        }
    
    def run_backtest(self, displacement_threshold: float, config_name: str):
        """Run full backtest."""
        print(f"\n{'='*80}")
        print(f"BACKTESTING: {config_name}")
        print(f"Displacement Threshold: {displacement_threshold}%")
        print(f"{'='*80}\n")
        
        # Load full dataset
        df = self.load_qqq_data('2024-01-01', '2025-10-31')
        
        if df is None or len(df) == 0:
            print("❌ No data found")
            return None
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        print(f"📊 Loaded {len(df)} bars ({len(df)/390:.0f} trading days)")
        print(f"   Period: {df['timestamp'].min()} to {df['timestamp'].max()}\n")
        
        # Group by day and process
        df['date'] = df['timestamp'].dt.date
        unique_dates = sorted(df['date'].unique())
        
        all_trades = []
        balance = 25000
        peak_balance = balance
        max_drawdown = 0
        
        print("Processing days...")
        for i, date in enumerate(unique_dates):
            day_df = df[df['date'] == date].copy().reset_index(drop=True)
            
            if len(day_df) < 100:
                continue
            
            signals = self.detect_signals(day_df, displacement_threshold)
            
            for signal in signals:
                trade = self.simulate_trade(signal, day_df, balance)
                if trade:
                    balance += trade['pnl']
                    peak_balance = max(peak_balance, balance)
                    drawdown = (peak_balance - balance) / peak_balance
                    max_drawdown = max(max_drawdown, drawdown)
                    
                    trade['balance_after'] = balance
                    trade['drawdown'] = drawdown
                    all_trades.append(trade)
            
            if (i + 1) % 50 == 0:
                print(f"  Processed {i+1}/{len(unique_dates)} days...")
        
        if not all_trades:
            print("\n❌ No trades generated\n")
            return None
        
        # Calculate metrics
        trades_df = pd.DataFrame(all_trades)
        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] <= 0]
        
        total_trades = len(trades_df)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl = trades_df['pnl'].sum()
        avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0
        profit_factor = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else float('inf')
        
        final_balance = balance
        total_return = ((final_balance - 25000) / 25000) * 100
        
        # Print results
        print(f"\n{'='*80}")
        print(f"RESULTS: {config_name}")
        print(f"{'='*80}\n")
        
        print(f"📈 PERFORMANCE:")
        print(f"   Total Trades:     {total_trades:,}")
        print(f"   Wins:            {win_count:,} ({win_rate:.1f}%)")
        print(f"   Losses:          {loss_count:,}")
        print(f"   Win Rate:        {win_rate:.1f}%")
        print(f"\n💰 P&L:")
        print(f"   Total P&L:       ${total_pnl:,.2f}")
        print(f"   Avg Win:         ${avg_win:,.2f}")
        print(f"   Avg Loss:        ${avg_loss:,.2f}")
        print(f"   Profit Factor:   {profit_factor:.2f}")
        print(f"\n📊 ACCOUNT:")
        print(f"   Starting:        $25,000.00")
        print(f"   Ending:          ${final_balance:,.2f}")
        print(f"   Total Return:    {total_return:+.1f}%")
        print(f"   Max Drawdown:    {max_drawdown*100:.2f}%")
        
        return {
            'config': config_name,
            'displacement': displacement_threshold,
            'total_trades': total_trades,
            'wins': win_count,
            'losses': loss_count,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'final_balance': final_balance,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'trades': trades_df
        }


def main():
    """Run comparison backtest."""
    print("\n" + "="*80)
    print("22-MONTH BACKTEST: PRODUCTION vs RELAXED PARAMETERS")
    print("="*80)
    print("\nDataset: QQQ 1-minute bars (Jan 2024 - Oct 2025)")
    print("Goal: Validate if 0.75% displacement maintains quality\n")
    print("="*80)
    
    backtester = RelaxedParamsBacktest()
    
    # Run both configurations
    production = backtester.run_backtest(1.0, "PRODUCTION (1.0% displacement)")
    relaxed = backtester.run_backtest(0.75, "RELAXED (0.75% displacement)")
    
    # Comparison
    if production and relaxed:
        print(f"\n{'='*80}")
        print("COMPARISON SUMMARY")
        print(f"{'='*80}\n")
        
        print(f"{'Metric':30s} {'PRODUCTION':>20s} {'RELAXED':>20s} {'Change':>15s}")
        print(f"{'-'*80}")
        
        metrics = [
            ('Total Trades', production['total_trades'], relaxed['total_trades']),
            ('Win Rate', f"{production['win_rate']:.1f}%", f"{relaxed['win_rate']:.1f}%"),
            ('Total P&L', f"${production['total_pnl']:,.2f}", f"${relaxed['total_pnl']:,.2f}"),
            ('Total Return', f"{production['total_return']:+.1f}%", f"{relaxed['total_return']:+.1f}%"),
            ('Max Drawdown', f"{production['max_drawdown']*100:.2f}%", f"{relaxed['max_drawdown']*100:.2f}%"),
            ('Profit Factor', f"{production['profit_factor']:.2f}", f"{relaxed['profit_factor']:.2f}"),
        ]
        
        for name, prod_val, rel_val in metrics:
            change = ""
            if isinstance(prod_val, (int, float)) and isinstance(rel_val, (int, float)):
                diff = rel_val - prod_val
                change = f"{diff:+.1f}"
            print(f"{name:30s} {str(prod_val):>20s} {str(rel_val):>20s} {change:>15s}")
        
        print(f"\n{'='*80}")
        print("DECISION")
        print(f"{'='*80}\n")
        
        prod_win_rate = production['win_rate']
        rel_win_rate = relaxed['win_rate']
        prod_dd = production['max_drawdown'] * 100
        rel_dd = relaxed['max_drawdown'] * 100
        
        if rel_win_rate >= 80.5 and rel_dd <= 3.0:
            print("✅ RELAXED PARAMETERS VALIDATED:")
            print(f"   - Win rate: {rel_win_rate:.1f}% (≥80.5% threshold)")
            print(f"   - Max drawdown: {rel_dd:.2f}% (≤3.0% threshold)")
            print(f"   - Safe to deploy in production")
        elif rel_win_rate >= prod_win_rate and rel_dd <= prod_dd * 1.5:
            print("⚠️  RELAXED PARAMETERS ACCEPTABLE BUT RISKIER:")
            print(f"   - Win rate: {rel_win_rate:.1f}% (better than production {prod_win_rate:.1f}%)")
            print(f"   - Max drawdown: {rel_dd:.2f}% (within acceptable range)")
            print(f"   - Consider deploying with caution")
        else:
            print("❌ KEEP PRODUCTION PARAMETERS:")
            print(f"   - Relaxed win rate: {rel_win_rate:.1f}% (target: ≥80.5%)")
            print(f"   - Relaxed drawdown: {rel_dd:.2f}% (target: ≤3.0%)")
            print(f"   - Does not meet quality thresholds")


if __name__ == '__main__':
    main()
