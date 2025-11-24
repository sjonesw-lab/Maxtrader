"""
ICT Parameter Sweep Analysis

Tests different ICT parameter combinations on historical data to find
optimization opportunities without sacrificing win rate and drawdown.

Analyzes Nov 21 and Nov 24, 2025 QQQ trading days.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timedelta
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.polygon_data_fetcher import PolygonDataFetcher
import pytz

class ICTParamSweep:
    """Parameter sweep analyzer for ICT detection."""
    
    def __init__(self):
        self.data_fetcher = PolygonDataFetcher()
        self.max_hold_minutes = 60  # Same as auto_trader
        
    def fetch_day_data(self, date_str: str, symbol: str = 'QQQ') -> pd.DataFrame:
        """Fetch 1-minute bars for a specific day."""
        date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Get data from previous day for context
        start = date - timedelta(days=3)
        end = date
        
        df = self.data_fetcher.fetch_stock_bars(
            ticker=symbol,
            from_date=start.strftime('%Y-%m-%d'),
            to_date=end.strftime('%Y-%m-%d')
        )
        
        if df is None or len(df) == 0:
            return pd.DataFrame()
        
        # Filter to just target day's market hours
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df[df['timestamp'].dt.date == date.date()].copy()
        
        return df
    
    def calculate_atr(self, df: pd.DataFrame, period=14) -> pd.Series:
        """Calculate ATR for each bar."""
        df = df.copy()
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        return df['tr'].rolling(window=period).mean()
    
    def detect_signals_with_params(self, df: pd.DataFrame, displacement_threshold: float, confluence_window: int) -> list:
        """Detect ICT signals with specific parameters."""
        if len(df) < 20:
            return []
        
        df = df.copy()
        df['atr'] = self.calculate_atr(df)
        
        # Apply ICT structure detection
        df = label_sessions(df)
        df = add_session_highs_lows(df)
        df = detect_all_structures(df, displacement_threshold=displacement_threshold)
        
        signals = []
        
        # Check for confluence (sweep + displacement + MSS within window)
        for i in range(len(df) - confluence_window):
            timestamp = df.iloc[i]['timestamp']
            
            # Bullish signal
            if df.iloc[i]['sweep_bullish']:
                window = df.iloc[i:i+confluence_window+1]
                if window['displacement_bullish'].any() and window['mss_bullish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'timestamp': timestamp,
                        'index': i,
                        'direction': 'LONG',
                        'price': price,
                        'atr': atr,
                        'target': price + (5 * atr)  # 5x ATR target
                    })
            
            # Bearish signal
            if df.iloc[i]['sweep_bearish']:
                window = df.iloc[i:i+confluence_window+1]
                if window['displacement_bearish'].any() and window['mss_bearish'].any():
                    atr = df.iloc[i].get('atr', 0.5)
                    price = df.iloc[i]['close']
                    
                    signals.append({
                        'timestamp': timestamp,
                        'index': i,
                        'direction': 'SHORT',
                        'price': price,
                        'atr': atr,
                        'target': price - (5 * atr)
                    })
        
        return signals
    
    def evaluate_signal(self, signal: dict, df: pd.DataFrame) -> dict:
        """Check if signal would have hit target within max hold time."""
        sig_idx = signal['index']
        
        # Get bars after signal up to max hold time
        remaining = df.iloc[sig_idx+1:].copy()
        
        if len(remaining) == 0:
            return {'hit_target': False, 'reason': 'EOD signal', 'bars_held': 0, 'max_profit': 0}
        
        # Limit to max hold minutes
        remaining = remaining.head(self.max_hold_minutes)
        
        if signal['direction'] == 'LONG':
            # Check if target hit
            target_bars = remaining[remaining['high'] >= signal['target']]
            if len(target_bars) > 0:
                bars_to_target = target_bars.index[0] - sig_idx
                return {'hit_target': True, 'bars_held': bars_to_target, 'max_profit': signal['target'] - signal['price']}
            else:
                max_profit = remaining['high'].max() - signal['price']
                return {'hit_target': False, 'reason': 'Target not reached', 'bars_held': len(remaining), 'max_profit': max_profit}
        
        else:  # SHORT
            target_bars = remaining[remaining['low'] <= signal['target']]
            if len(target_bars) > 0:
                bars_to_target = target_bars.index[0] - sig_idx
                return {'hit_target': True, 'bars_held': bars_to_target, 'max_profit': signal['price'] - signal['target']}
            else:
                max_profit = signal['price'] - remaining['low'].min()
                return {'hit_target': False, 'reason': 'Target not reached', 'bars_held': len(remaining), 'max_profit': max_profit}
    
    def analyze_day(self, date_str: str, symbol: str = 'QQQ'):
        """Run parameter sweep for a single day."""
        print(f"\n{'='*80}")
        print(f"ANALYZING {symbol} - {date_str}")
        print(f"{'='*80}\n")
        
        # Fetch data
        df = self.fetch_day_data(date_str, symbol)
        
        if len(df) == 0:
            print(f"❌ No data found for {date_str}\n")
            return None
        
        print(f"📊 Loaded {len(df)} 1-minute bars")
        print(f"   Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
        print(f"   Session: {df['timestamp'].min()} to {df['timestamp'].max()}\n")
        
        # Calculate daily ATR for reference
        atr_14 = self.calculate_atr(df).iloc[-1] if len(df) > 14 else 0.5
        print(f"📈 Daily ATR (14-bar): ${atr_14:.2f}\n")
        
        # Parameter sets to test
        param_sets = [
            {'name': 'PRODUCTION', 'displacement': 1.0, 'window': 6},
            {'name': 'Relaxed Displacement (0.75%)', 'displacement': 0.75, 'window': 6},
            {'name': 'Wider Window (8 bars)', 'displacement': 1.0, 'window': 8},
            {'name': 'Aggressive (0.75% + 8 bars)', 'displacement': 0.75, 'window': 8},
        ]
        
        results = []
        
        for params in param_sets:
            print(f"\n{'─'*80}")
            print(f"🔍 {params['name']}")
            print(f"   Displacement: {params['displacement']}% | Window: {params['window']} bars")
            print(f"{'─'*80}")
            
            # Detect signals
            signals = self.detect_signals_with_params(df, params['displacement'], params['window'])
            
            if not signals:
                print("   ❌ No signals detected\n")
                results.append({
                    'config': params['name'],
                    'signals': 0,
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0,
                    'details': []
                })
                continue
            
            print(f"   ✅ Found {len(signals)} signal(s)\n")
            
            # Evaluate each signal
            wins = 0
            losses = 0
            
            for i, sig in enumerate(signals, 1):
                result = self.evaluate_signal(sig, df)
                sig.update(result)
                
                status = "🎯 WIN" if result['hit_target'] else "❌ MISS"
                profit_pct = (result['max_profit'] / sig['atr']) / 5 * 100
                
                print(f"   Signal #{i}: {status}")
                print(f"   ├─ Time: {sig['timestamp']}")
                print(f"   ├─ {sig['direction']} @ ${sig['price']:.2f}")
                print(f"   ├─ Target: ${sig['target']:.2f} (5x ATR)")
                
                if result['hit_target']:
                    wins += 1
                    print(f"   └─ Hit in {result['bars_held']} bars\n")
                else:
                    losses += 1
                    print(f"   └─ Max profit: ${result['max_profit']:.2f} ({profit_pct:.1f}% of target)\n")
            
            win_rate = (wins / len(signals) * 100) if signals else 0
            
            results.append({
                'config': params['name'],
                'signals': len(signals),
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'details': signals
            })
        
        # Summary table
        print(f"\n{'='*80}")
        print(f"SUMMARY - {date_str}")
        print(f"{'='*80}\n")
        print(f"{'Configuration':40s} {'Signals':>8s} {'Wins':>8s} {'Losses':>8s} {'Win %':>8s}")
        print(f"{'-'*80}")
        
        for res in results:
            print(f"{res['config']:40s} {res['signals']:>8d} {res['wins']:>8d} {res['losses']:>8d} {res['win_rate']:>7.1f}%")
        
        return results


def main():
    """Run parameter sweep analysis."""
    print("\n" + "="*80)
    print("ICT PARAMETER SWEEP ANALYSIS")
    print("="*80)
    print("\nGoal: Find parameters that generate profitable trades without")
    print("      sacrificing validated 80.5% win rate and 3% max drawdown")
    print("\n" + "="*80)
    
    analyzer = ICTParamSweep()
    
    # Analyze both days
    dates = ['2025-11-21', '2025-11-24']
    all_results = {}
    
    for date in dates:
        results = analyzer.analyze_day(date)
        if results:
            all_results[date] = results
    
    # Final recommendations
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    print("""
    Analysis Complete:
    
    1. PRODUCTION parameters (1% displacement, 6-bar window):
       - Calibrated for HIGH QUALITY signals (80.5% win rate validated)
       - Some days have 0 signals by design
    
    2. If relaxed parameters show opportunities:
       - Need FULL 22-month backtest validation
       - Cannot optimize on 2 days (overfitting risk)
       - Must maintain 80.5%+ win rate and <3% drawdown
    
    3. Risk Assessment:
       - Looser parameters = more signals, likely lower quality
       - Could degrade from 80.5% to <70% win rate
       - Could increase drawdown from 3% to >5%
    
    DECISION CRITERIA:
    ✅ Keep PRODUCTION if: Relaxed params don't show clear edge on BOTH days
    ⚠️  Test further if: Relaxed params hit 100% on both days with 4+ signals
    ❌ Never change: Without full backtest validation
    """)

if __name__ == '__main__':
    main()
