#!/usr/bin/env python3
"""
Comprehensive Comparison Analysis:
1. Non-compounding vs Compounding returns
2. Swing targets vs ATR targets vs Percent targets
3. 1-minute bars vs Tick bars (simulated)
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.timeframes import resample_to_timeframe


def find_swing_targets(df_htf, signal_time, lookback_bars=20):
    """Find swing high/low on higher timeframe."""
    mask = df_htf['timestamp'] <= signal_time
    if not mask.any():
        return None
    
    current_idx = mask.sum() - 1
    start_idx = max(0, current_idx - lookback_bars)
    recent = df_htf.iloc[start_idx:current_idx + 1]
    
    if len(recent) == 0:
        return None
    
    return {
        'swing_high': recent['high'].max(),
        'swing_low': recent['low'].min(),
        'swing_range': recent['high'].max() - recent['low'].min()
    }


def calculate_atr(df, period=14):
    """Calculate ATR for each bar."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def find_ict_confluence_signals(df):
    """Find ICT confluence signals."""
    signals = []
    
    for i in range(len(df) - 5):
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
        
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
    
    return pd.DataFrame(signals)


def backtest_strategy(df_1min, df_15min, signals, target_type='swing', target_value=1.0, compounding=False, 
                     starting_capital=25000, risk_pct=5.0):
    """
    Unified backtesting engine.
    
    Args:
        target_type: 'swing' (15-min swing), 'atr' (ATR multiple), 'percent' (% move)
        target_value: Multiplier (1.0 = 100% swing, 1.5 = 1.5x ATR, 0.003 = 0.3% move)
        compounding: True = adjust position size based on balance, False = fixed shares
    """
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    for _, signal in signals.iterrows():
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        # Calculate target based on type
        if target_type == 'swing':
            swing_data = find_swing_targets(df_15min, signal['timestamp'], lookback_bars=20)
            if not swing_data or swing_data['swing_range'] < 0.30:
                continue
            
            entry_mask = df_1min['timestamp'] > signal['timestamp']
            if not entry_mask.any():
                continue
            
            entry_idx = df_1min[entry_mask].index[0]
            entry_bar = df_1min.loc[entry_idx]
            entry_price = entry_bar['open']
            
            if signal['direction'] == 'long':
                target_price = swing_data['swing_low'] + (target_value * swing_data['swing_range'])
            else:
                target_price = swing_data['swing_high'] - (target_value * swing_data['swing_range'])
            
            target_distance = abs(target_price - entry_price)
            
        elif target_type == 'atr':
            entry_mask = df_1min['timestamp'] > signal['timestamp']
            if not entry_mask.any():
                continue
            
            entry_idx = df_1min[entry_mask].index[0]
            entry_bar = df_1min.loc[entry_idx]
            entry_price = entry_bar['open']
            
            atr_value = signal.get('atr', 0.5)
            target_distance = target_value * atr_value
            
            if signal['direction'] == 'long':
                target_price = entry_price + target_distance
            else:
                target_price = entry_price - target_distance
        
        elif target_type == 'percent':
            entry_mask = df_1min['timestamp'] > signal['timestamp']
            if not entry_mask.any():
                continue
            
            entry_idx = df_1min[entry_mask].index[0]
            entry_bar = df_1min.loc[entry_idx]
            entry_price = entry_bar['open']
            
            target_distance = entry_price * target_value
            
            if signal['direction'] == 'long':
                target_price = entry_price + target_distance
            else:
                target_price = entry_price - target_distance
        
        # Minimum target filter
        if target_distance < 0.15:
            continue
        
        # Exit logic
        exit_window = df_1min.loc[entry_idx:entry_idx + 60]
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        exit_price = None
        exit_time = None
        
        for idx, bar in exit_window.iterrows():
            if signal['direction'] == 'long':
                if bar['high'] >= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    break
            else:
                if bar['low'] <= target_price:
                    hit_target = True
                    exit_price = target_price
                    exit_time = bar['timestamp']
                    break
        
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        # Position sizing
        if compounding:
            # Calculate shares based on current balance and risk
            risk_dollars = account_balance * (risk_pct / 100)
            shares = int(risk_dollars / target_distance)
            shares = max(10, min(shares, 1000))  # Min 10, max 1000 shares
        else:
            # Fixed position size
            shares = 100
        
        # Calculate P&L
        if signal['direction'] == 'long':
            pnl_per_share = exit_price - entry_price
        else:
            pnl_per_share = entry_price - exit_price
        
        position_pnl = pnl_per_share * shares
        account_balance += position_pnl
        
        trades.append({
            'entry_time': entry_bar['timestamp'],
            'entry_price': entry_price,
            'exit_time': exit_time,
            'exit_price': exit_price,
            'direction': signal['direction'],
            'hit_target': hit_target,
            'pnl_per_share': pnl_per_share,
            'shares': shares,
            'position_pnl': position_pnl,
            'balance': account_balance
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades)


def calculate_performance(trades_df, starting_capital=25000):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return None
    
    final_balance = trades_df.iloc[-1]['balance']
    equity_curve = trades_df['balance'].values
    
    # Max drawdown
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_drawdown = drawdown.min()
    max_drawdown_pct = (max_drawdown / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl_per_share'] > 0]
    
    return {
        'final_balance': final_balance,
        'total_return': final_balance - starting_capital,
        'return_pct': ((final_balance - starting_capital) / starting_capital) * 100,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'total_trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df)) * 100,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df)) * 100,
    }


def load_test_data(year, month):
    """Load monthly data."""
    filename = f'QQQ_{year}_{month:02d}_1min.csv'
    data_path = Path(f'data/polygon_downloads/{filename}')
    
    if not data_path.exists():
        return None, None, None
    
    provider = CSVDataProvider(str(data_path))
    df_1min = provider.load_bars()
    
    if len(df_1min) == 0:
        return None, None, None
    
    # Calculate ATR
    df_1min = calculate_atr(df_1min, period=14)
    
    df_15min = resample_to_timeframe(df_1min, '15min')
    
    df_1min = label_sessions(df_1min)
    df_1min = add_session_highs_lows(df_1min)
    df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
    
    signals = find_ict_confluence_signals(df_1min)
    
    return df_1min, df_15min, signals


# ============================================================================
# COMPARISON 1: NON-COMPOUNDING VS COMPOUNDING
# ============================================================================

print("\n" + "="*80)
print("COMPARISON 1: NON-COMPOUNDING vs COMPOUNDING")
print("="*80)
print("Strategy: 100% of 15-Minute Swing, 5% Risk")
print("="*80)

test_months = [
    (2024, [2, 3, 4]),  # Q1 2024
]

for comparison_type in ['non_compounding', 'compounding']:
    all_trades = []
    
    for year, months in test_months:
        for month in months:
            df_1min, df_15min, signals = load_test_data(year, month)
            if df_1min is None or len(signals) == 0:
                continue
            
            is_compounding = (comparison_type == 'compounding')
            trades = backtest_strategy(df_1min, df_15min, signals, 
                                      target_type='swing', target_value=1.0,
                                      compounding=is_compounding, risk_pct=5.0)
            
            if len(trades) > 0:
                all_trades.append(trades)
    
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        perf = calculate_performance(combined)
        
        label = "NON-COMPOUNDING (Fixed 100 shares)" if comparison_type == 'non_compounding' else "COMPOUNDING (% of balance)"
        print(f"\n{label}:")
        print(f"  Final Balance: ${perf['final_balance']:,.2f}")
        print(f"  Total Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
        print(f"  Max Drawdown: ${perf['max_drawdown']:,.2f} ({perf['max_drawdown_pct']:.2f}%)")
        print(f"  Trades: {perf['total_trades']}")
        print(f"  Win Rate: {perf['win_rate']:.1f}%")


# ============================================================================
# COMPARISON 2: SWING vs ATR vs PERCENT TARGETS
# ============================================================================

print("\n" + "="*80)
print("COMPARISON 2: TARGET METHODS")
print("="*80)
print("Testing: Swing (100%), ATR (1.5x), Percent (0.3%)")
print("="*80)

target_configs = [
    ('15-Min Swing (100%)', 'swing', 1.0),
    ('ATR (1.5x)', 'atr', 1.5),
    ('Percent (0.3%)', 'percent', 0.003),
]

for label, target_type, target_value in target_configs:
    all_trades = []
    
    for year, months in test_months:
        for month in months:
            df_1min, df_15min, signals = load_test_data(year, month)
            if df_1min is None or len(signals) == 0:
                continue
            
            trades = backtest_strategy(df_1min, df_15min, signals, 
                                      target_type=target_type, target_value=target_value,
                                      compounding=False, risk_pct=5.0)
            
            if len(trades) > 0:
                all_trades.append(trades)
    
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        perf = calculate_performance(combined)
        
        print(f"\n{label}:")
        print(f"  Final Balance: ${perf['final_balance']:,.2f}")
        print(f"  Total Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
        print(f"  Trades: {perf['total_trades']}, Win Rate: {perf['win_rate']:.1f}%, Hit Rate: {perf['target_hit_rate']:.1f}%")


# ============================================================================
# COMPARISON 3: 1-MINUTE BARS vs SIMULATED TICK BARS
# ============================================================================

print("\n" + "="*80)
print("COMPARISON 3: 1-MINUTE BARS vs TICK BARS (Simulated)")
print("="*80)
print("Tick bars simulated by subsampling 1-min bars to 60-90 second intervals")
print("="*80)

# For tick bars, we simulate by creating irregular time intervals
def create_tick_bars(df_1min):
    """Simulate tick bars with 60-90 second average intervals."""
    tick_bars = []
    i = 0
    
    while i < len(df_1min):
        # Random interval: 1 or 2 bars (60 or 120 seconds)
        interval = np.random.choice([1, 2], p=[0.6, 0.4])  # 60% 1-bar, 40% 2-bar
        
        if i + interval > len(df_1min):
            interval = len(df_1min) - i
        
        chunk = df_1min.iloc[i:i+interval]
        
        if len(chunk) > 0:
            tick_bars.append({
                'timestamp': chunk.iloc[-1]['timestamp'],
                'open': chunk.iloc[0]['open'],
                'high': chunk['high'].max(),
                'low': chunk['low'].min(),
                'close': chunk.iloc[-1]['close'],
                'volume': chunk['volume'].sum()
            })
        
        i += interval
    
    return pd.DataFrame(tick_bars)


print("\nProcessing tick bars (this may take a moment)...")

for bar_type in ['1min', 'tick']:
    all_trades = []
    
    for year, months in [(2024, [2, 3, 4])]:
        for month in months:
            df_1min, df_15min, signals = load_test_data(year, month)
            if df_1min is None or len(signals) == 0:
                continue
            
            if bar_type == 'tick':
                # Create tick bars and reprocess
                df_tick = create_tick_bars(df_1min)
                df_tick = label_sessions(df_tick)
                df_tick = add_session_highs_lows(df_tick)
                df_tick = detect_all_structures(df_tick, displacement_threshold=1.0)
                signals = find_ict_confluence_signals(df_tick)
                
                if len(signals) == 0:
                    continue
                
                trades = backtest_strategy(df_tick, df_15min, signals, 
                                          target_type='swing', target_value=1.0,
                                          compounding=False, risk_pct=5.0)
            else:
                trades = backtest_strategy(df_1min, df_15min, signals, 
                                          target_type='swing', target_value=1.0,
                                          compounding=False, risk_pct=5.0)
            
            if len(trades) > 0:
                all_trades.append(trades)
    
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True)
        perf = calculate_performance(combined)
        
        label = "1-Minute Bars" if bar_type == '1min' else "Tick Bars (60-90s avg)"
        print(f"\n{label}:")
        print(f"  Final Balance: ${perf['final_balance']:,.2f}")
        print(f"  Total Return: ${perf['total_return']:,.2f} ({perf['return_pct']:.2f}%)")
        print(f"  Trades: {perf['total_trades']}, Win Rate: {perf['win_rate']:.1f}%")

print("\n" + "="*80 + "\n")
