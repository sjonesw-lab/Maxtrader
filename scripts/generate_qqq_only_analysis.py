#!/usr/bin/env python3
"""
QQQ-ONLY Segmented Backtest Analysis
Uses full 22-month dataset from polygon_downloads to validate filtering strategies
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_displacement, detect_mss
from tabulate import tabulate


# ============================================================================
# NEWS EVENTS CALENDAR
# ============================================================================

def load_news_events():
    """Load major economic news events (FOMC, CPI, NFP, PCE)"""
    events = [
        # 2024 FOMC
        ('2024-01-31', 'FOMC'), ('2024-03-20', 'FOMC'), ('2024-05-01', 'FOMC'),
        ('2024-06-12', 'FOMC'), ('2024-07-31', 'FOMC'), ('2024-09-18', 'FOMC'),
        ('2024-11-07', 'FOMC'), ('2024-12-18', 'FOMC'),
        
        # 2025 FOMC
        ('2025-01-29', 'FOMC'), ('2025-03-19', 'FOMC'), ('2025-05-07', 'FOMC'),
        ('2025-06-18', 'FOMC'), ('2025-07-30', 'FOMC'), ('2025-09-17', 'FOMC'),
        ('2025-11-05', 'FOMC'),
        
        # 2024 CPI
        ('2024-01-11', 'CPI'), ('2024-02-13', 'CPI'), ('2024-03-12', 'CPI'),
        ('2024-04-10', 'CPI'), ('2024-05-15', 'CPI'), ('2024-06-12', 'CPI'),
        ('2024-07-11', 'CPI'), ('2024-08-14', 'CPI'), ('2024-09-11', 'CPI'),
        ('2024-10-10', 'CPI'), ('2024-11-13', 'CPI'), ('2024-12-11', 'CPI'),
        
        # 2025 CPI
        ('2025-01-15', 'CPI'), ('2025-02-12', 'CPI'), ('2025-03-12', 'CPI'),
        ('2025-04-10', 'CPI'), ('2025-05-13', 'CPI'), ('2025-06-11', 'CPI'),
        ('2025-07-10', 'CPI'), ('2025-08-13', 'CPI'), ('2025-09-10', 'CPI'),
        ('2025-10-10', 'CPI'),
        
        # 2024 NFP
        ('2024-01-05', 'NFP'), ('2024-02-02', 'NFP'), ('2024-03-08', 'NFP'),
        ('2024-04-05', 'NFP'), ('2024-05-03', 'NFP'), ('2024-06-07', 'NFP'),
        ('2024-07-05', 'NFP'), ('2024-08-02', 'NFP'), ('2024-09-06', 'NFP'),
        ('2024-10-04', 'NFP'), ('2024-11-01', 'NFP'), ('2024-12-06', 'NFP'),
        
        # 2025 NFP
        ('2025-01-10', 'NFP'), ('2025-02-07', 'NFP'), ('2025-03-07', 'NFP'),
        ('2025-04-04', 'NFP'), ('2025-05-02', 'NFP'), ('2025-06-06', 'NFP'),
        ('2025-07-03', 'NFP'), ('2025-08-01', 'NFP'), ('2025-09-05', 'NFP'),
        ('2025-10-03', 'NFP'),
        
        # 2024 PCE
        ('2024-01-26', 'PCE'), ('2024-02-29', 'PCE'), ('2024-03-29', 'PCE'),
        ('2024-04-26', 'PCE'), ('2024-05-31', 'PCE'), ('2024-06-28', 'PCE'),
        ('2024-07-26', 'PCE'), ('2024-08-30', 'PCE'), ('2024-09-27', 'PCE'),
        ('2024-10-31', 'PCE'), ('2024-11-27', 'PCE'), ('2024-12-20', 'PCE'),
        
        # 2025 PCE
        ('2025-01-31', 'PCE'), ('2025-02-28', 'PCE'), ('2025-03-28', 'PCE'),
        ('2025-04-30', 'PCE'), ('2025-05-30', 'PCE'), ('2025-06-27', 'PCE'),
        ('2025-07-31', 'PCE'), ('2025-08-29', 'PCE'), ('2025-09-26', 'PCE'),
        ('2025-10-31', 'PCE'),
    ]
    
    df = pd.DataFrame(events, columns=['date', 'event_type'])
    df['date'] = pd.to_datetime(df['date'])
    return df


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_atr(df, period=14):
    """Calculate ATR"""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def detect_sweeps_strict(df):
    """STRICT: Exact sweep of session levels"""
    df = df.copy()
    df['sweep_bullish'] = False
    df['sweep_bearish'] = False
    
    for idx in df.index:
        row = df.loc[idx]
        
        if pd.notna(row['asia_low']) and row['low'] < row['asia_low'] and row['close'] > row['asia_low']:
            df.at[idx, 'sweep_bullish'] = True
        elif pd.notna(row['london_low']) and row['low'] < row['london_low'] and row['close'] > row['london_low']:
            df.at[idx, 'sweep_bullish'] = True
        
        if pd.notna(row['asia_high']) and row['high'] > row['asia_high'] and row['close'] < row['asia_high']:
            df.at[idx, 'sweep_bearish'] = True
        elif pd.notna(row['london_high']) and row['high'] > row['london_high'] and row['close'] < row['london_high']:
            df.at[idx, 'sweep_bearish'] = True
    
    return df


def find_signals(df):
    """Find ICT confluence signals"""
    signals = []
    
    for i in range(len(df) - 5):
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'long',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'],
                    'price': df.iloc[i]['close'],
                    'direction': 'short',
                    'atr': df.iloc[i].get('atr', 0.5)
                })
    return signals


def estimate_option_premium(underlying_price, strike, time_minutes_from_open=0):
    """Estimate 0DTE option premium"""
    moneyness = (underlying_price - strike) / underlying_price
    
    if moneyness >= 0.01:
        base_premium = 3.0 + (moneyness * 100)
    elif moneyness >= 0.005:
        base_premium = 2.5
    elif moneyness >= -0.005:
        base_premium = 2.0
    elif moneyness >= -0.01:
        base_premium = 1.2
    elif moneyness >= -0.02:
        base_premium = 0.6
    else:
        base_premium = 0.2
    
    time_remaining_pct = max(0, (390 - time_minutes_from_open) / 390)
    time_decay = 0.3 + (0.7 * time_remaining_pct)
    vol_factor = underlying_price / 500
    premium = base_premium * time_decay * vol_factor
    
    return max(premium, 0.05)


def backtest_qqq(df, signals, starting_capital=25000, risk_pct=5.0):
    """Backtest with 1-strike ITM options (NO COMPOUNDING for fair comparison)"""
    trades = []
    last_exit_time = None
    balance = starting_capital
    market_open = df.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    
    for signal in signals:
        # Prevent overlap
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_idx = signal['index'] + 1
        if entry_idx >= len(df):
            continue
        
        entry_price = df.iloc[entry_idx]['open']
        entry_time = df.iloc[entry_idx]['timestamp']
        time_from_open = (entry_time - market_open).total_seconds() / 60
        
        atr_value = signal['atr']
        target_distance = 5.0 * atr_value
        
        if target_distance < 0.15:
            continue
        
        atm_strike = round(entry_price / 5) * 5
        
        # 1-strike ITM
        if signal['direction'] == 'long':
            strike = atm_strike - 5
            target_price = entry_price + target_distance
        else:
            strike = atm_strike + 5
            target_price = entry_price - target_distance
        
        premium_per_contract = estimate_option_premium(entry_price, strike, time_from_open)
        risk_dollars = balance * (risk_pct / 100)  # Fixed risk (no compounding for fair comparison)
        num_contracts = max(1, min(int(risk_dollars / (premium_per_contract * 100)), 10))
        total_premium_paid = num_contracts * premium_per_contract * 100
        
        exit_window_end = min(entry_idx + 60, len(df) - 1)
        exit_window = df.iloc[entry_idx:exit_window_end+1]
        
        if len(exit_window) == 0:
            continue
        
        hit_target = False
        exit_price = None
        exit_time = None
        
        for idx in range(len(exit_window)):
            bar = exit_window.iloc[idx]
            if signal['direction'] == 'long' and bar['high'] >= target_price:
                hit_target = True
                exit_price = target_price
                exit_time = bar['timestamp']
                break
            elif signal['direction'] == 'short' and bar['low'] <= target_price:
                hit_target = True
                exit_price = target_price
                exit_time = bar['timestamp']
                break
        
        if exit_price is None:
            exit_price = exit_window.iloc[-1]['close']
            exit_time = exit_window.iloc[-1]['timestamp']
        
        time_at_exit = (exit_time - market_open).total_seconds() / 60
        
        if hit_target:
            if signal['direction'] == 'long':
                intrinsic = max(0, exit_price - strike) * 100
            else:
                intrinsic = max(0, strike - exit_price) * 100
            option_value_at_exit = intrinsic * num_contracts
        else:
            exit_premium = estimate_option_premium(exit_price, strike, time_at_exit)
            option_value_at_exit = exit_premium * 100 * num_contracts
        
        position_pnl = option_value_at_exit - total_premium_paid
        
        trades.append({
            'timestamp': entry_time,
            'direction': signal['direction'],
            'entry_price': entry_price,
            'target_price': target_price,
            'exit_price': exit_price,
            'hit_target': hit_target,
            'pnl': position_pnl,
            'premium_paid': total_premium_paid
        })
        
        last_exit_time = exit_time
    
    return trades


def classify_trade(trade, news_df):
    """Classify trade by time, day, and news proximity"""
    ts = trade['timestamp']
    
    # Day of week
    weekday = ts.strftime('%A')
    
    # Hour bin
    hour = ts.hour
    minute = ts.minute
    total_minutes = hour * 60 + minute
    
    if 570 <= total_minutes < 630:  # 9:30-10:29
        hour_bin = '09:30-10:29'
    elif 630 <= total_minutes < 690:  # 10:30-11:29
        hour_bin = '10:30-11:29'
    elif 690 <= total_minutes < 750:  # 11:30-12:29
        hour_bin = '11:30-12:29'
    elif 750 <= total_minutes < 810:  # 12:30-13:29
        hour_bin = '12:30-13:29'
    elif 810 <= total_minutes < 870:  # 13:30-14:29
        hour_bin = '13:30-14:29'
    elif 870 <= total_minutes < 930:  # 14:30-15:29
        hour_bin = '14:30-15:29'
    else:  # 15:30-16:00
        hour_bin = '15:30-16:00'
    
    # News detection
    trade_date = ts.date()
    news_events = news_df[news_df['date'].dt.date == trade_date]
    
    is_news_day = len(news_events) > 0
    event_type = news_events.iloc[0]['event_type'] if is_news_day else None
    
    # Proximity (assuming news at 8:30 AM ET for most events)
    if is_news_day:
        news_time = ts.replace(hour=8, minute=30, second=0, microsecond=0)
        time_diff_minutes = (ts - news_time).total_seconds() / 60
        
        if time_diff_minutes < 30:
            proximity = 'Within 30 minutes'
        elif time_diff_minutes < 60:
            proximity = 'Within 1 hour'
        elif time_diff_minutes < 120:
            proximity = 'Within 2 hours'
        else:
            proximity = 'Outside 2 hours'
    else:
        proximity = None
    
    return {
        'weekday': weekday,
        'hour_bin': hour_bin,
        'is_news_day': is_news_day,
        'event_type': event_type,
        'proximity': proximity
    }


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

print("\n" + "="*70)
print("QQQ-ONLY COMPREHENSIVE BACKTEST ANALYSIS")
print("Segmented by: Day of Week, Time of Day, News Events")
print("="*70)

# Load news events
print("\n📅 Loading news events calendar...")
news_df = load_news_events()
print(f"✅ Loaded {len(news_df)} news events (FOMC, CPI, NFP, PCE)")

# Load all QQQ monthly files
print("\n📊 Loading QQQ monthly files from polygon_downloads...")
polygon_dir = Path('data/polygon_downloads')
qqq_files = sorted(polygon_dir.glob('QQQ_202[45]_*_1min.csv'))

print(f"✅ Found {len(qqq_files)} QQQ monthly files")

# Concatenate all data
all_data = []
for file in qqq_files:
    provider = CSVDataProvider(str(file))
    df = provider.load_bars()
    all_data.append(df)
    print(f"   Loaded {len(df):,} bars from {file.name}")

df_all = pd.concat(all_data, ignore_index=True)
df_all = df_all.sort_values('timestamp').reset_index(drop=True)

print(f"\n✅ Total QQQ bars loaded: {len(df_all):,}")
print(f"   Date range: {df_all['timestamp'].min()} to {df_all['timestamp'].max()}")

# Process data
print("\n🔄 Processing ICT structures...")
df_all = calculate_atr(df_all, period=14)
df_all = label_sessions(df_all)
df_all = add_session_highs_lows(df_all)
df_all = detect_sweeps_strict(df_all)
df_all = detect_displacement(df_all, atr_period=14, threshold=1.2)
df_all = detect_mss(df_all)

# Find signals
print("🔍 Finding ICT confluence signals...")
signals = find_signals(df_all)
print(f"✅ Found {len(signals)} QQQ signals")

# Run backtest
print("\n💰 Running backtest with 1-strike ITM options...")
trades = backtest_qqq(df_all, signals, starting_capital=25000, risk_pct=5.0)
print(f"✅ Executed {len(trades)} trades")

# Classify trades
print("\n🏷️  Classifying trades by temporal and news factors...")
for trade in trades:
    classification = classify_trade(trade, news_df)
    trade.update(classification)

# Convert to DataFrame
trades_df = pd.DataFrame(trades)
trades_df['win'] = trades_df['pnl'] > 0

# Overall stats
total_trades = len(trades_df)
total_wins = trades_df['win'].sum()
win_rate = total_wins / total_trades if total_trades > 0 else 0
total_pnl = trades_df['pnl'].sum()
avg_pnl = trades_df['pnl'].mean()

print(f"\n📊 OVERALL QQQ-ONLY PERFORMANCE:")
print(f"   Total Trades: {total_trades}")
print(f"   Win Rate: {win_rate:.1%}")
print(f"   Total P&L: ${total_pnl:,.2f}")
print(f"   Avg P&L: ${avg_pnl:.2f}")

# Segmented analysis
print("\n📈 Generating statistical summaries...")

# By weekday
weekday_stats = trades_df.groupby('weekday').agg({
    'pnl': ['sum', 'mean', 'count'],
    'win': 'sum'
}).round(2)
weekday_stats.columns = ['total_pnl', 'avg_pnl', 'total_trades', 'wins']
weekday_stats['win_rate'] = (weekday_stats['wins'] / weekday_stats['total_trades']).round(6)
weekday_stats = weekday_stats.reset_index()
weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
weekday_stats['weekday'] = pd.Categorical(weekday_stats['weekday'], categories=weekday_order, ordered=True)
weekday_stats = weekday_stats.sort_values('weekday')

# By hour
hourly_stats = trades_df.groupby('hour_bin').agg({
    'pnl': ['sum', 'mean', 'count'],
    'win': 'sum'
}).round(2)
hourly_stats.columns = ['total_pnl', 'avg_pnl', 'total_trades', 'wins']
hourly_stats['win_rate'] = (hourly_stats['wins'] / hourly_stats['total_trades']).round(6)
hourly_stats = hourly_stats.reset_index()

# News day vs normal
trades_df['day_type'] = trades_df['is_news_day'].apply(lambda x: 'News Day' if x else 'Normal Day')
news_day_stats = trades_df.groupby('day_type').agg({
    'pnl': ['sum', 'mean', 'count'],
    'win': 'sum'
}).round(2)
news_day_stats.columns = ['total_pnl', 'avg_pnl', 'total_trades', 'wins']
news_day_stats['win_rate'] = (news_day_stats['wins'] / news_day_stats['total_trades']).round(6)
news_day_stats = news_day_stats.reset_index()

# By event type
event_trades = trades_df[trades_df['event_type'].notna()]
event_stats = event_trades.groupby('event_type').agg({
    'pnl': ['sum', 'mean', 'count'],
    'win': 'sum'
}).round(2)
event_stats.columns = ['total_pnl', 'avg_pnl', 'total_trades', 'wins']
event_stats['win_rate'] = (event_stats['wins'] / event_stats['total_trades']).round(6)
event_stats = event_stats.reset_index()

# By proximity
proximity_trades = trades_df[trades_df['proximity'].notna()]
proximity_stats = proximity_trades.groupby('proximity').agg({
    'pnl': ['sum', 'mean', 'count'],
    'win': 'sum'
}).round(2)
proximity_stats.columns = ['total_pnl', 'avg_pnl', 'total_trades', 'wins']
proximity_stats['win_rate'] = (proximity_stats['wins'] / proximity_stats['total_trades']).round(6)
proximity_stats = proximity_stats.reset_index()

# Export CSVs
output_dir = Path('reports/analytics/qqq_only')
output_dir.mkdir(parents=True, exist_ok=True)

weekday_stats.to_csv(output_dir / 'weekday_performance.csv', index=False)
hourly_stats.to_csv(output_dir / 'hourly_performance.csv', index=False)
news_day_stats.to_csv(output_dir / 'news_day_performance.csv', index=False)
event_stats.to_csv(output_dir / 'news_event_type_performance.csv', index=False)
proximity_stats.to_csv(output_dir / 'news_proximity_performance.csv', index=False)
trades_df.to_csv(output_dir / 'full_trade_log.csv', index=False)

print("\n💾 Exporting downloadable CSV tables...")
print(f"   ✅ {output_dir}/weekday_performance.csv")
print(f"   ✅ {output_dir}/hourly_performance.csv")
print(f"   ✅ {output_dir}/news_day_performance.csv")
print(f"   ✅ {output_dir}/news_event_type_performance.csv")
print(f"   ✅ {output_dir}/news_proximity_performance.csv")
print(f"   ✅ {output_dir}/full_trade_log.csv")

# Print tables
print("\n" + "="*70)
print("SUMMARY TABLES")
print("="*70)

print("\n📅 DAY OF WEEK PERFORMANCE")
print(tabulate(weekday_stats, headers='keys', tablefmt='plain', showindex=False))

print("\n🕐 HOUR OF DAY PERFORMANCE")
print(tabulate(hourly_stats, headers='keys', tablefmt='plain', showindex=False))

print("\n📰 NEWS DAY vs NORMAL DAY")
print(tabulate(news_day_stats, headers='keys', tablefmt='plain', showindex=False))

print("\n📊 PERFORMANCE BY NEWS EVENT TYPE")
print(tabulate(event_stats, headers='keys', tablefmt='plain', showindex=False))

print("\n⏰ PERFORMANCE BY NEWS PROXIMITY")
print(tabulate(proximity_stats, headers='keys', tablefmt='plain', showindex=False))

print("\n" + "="*70)
print("✅ ANALYSIS COMPLETE - 5 tables exported")
print(f"📁 Download location: {output_dir}")
print("="*70)
