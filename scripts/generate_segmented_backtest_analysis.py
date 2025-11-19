#!/usr/bin/env python3
"""
Comprehensive Backtest Analysis: Day of Week, Time of Day, News Events
Generates downloadable CSV tables for performance segmentation
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from pathlib import Path
from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures
from engine.options_engine import estimate_option_premium


def wilson_confidence_interval(wins, total, confidence=0.95):
    """
    Calculate Wilson score confidence interval for win rate
    More accurate than normal approximation for small samples
    """
    if total == 0:
        return 0.0, 0.0
    
    from scipy import stats
    z = stats.norm.ppf((1 + confidence) / 2)
    p = wins / total
    
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = z * np.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    
    return max(0, center - margin), min(1, center + margin)


def run_full_backtest(symbol: str, start_date: str, end_date: str):
    """
    Run backtest and return all individual trades with timestamps
    """
    print(f"\n{'='*70}")
    print(f"Running backtest for {symbol}: {start_date} to {end_date}")
    print(f"{'='*70}")
    
    fetcher = PolygonDataFetcher()
    df = fetcher.fetch_stock_bars(ticker=symbol, from_date=start_date, to_date=end_date)
    
    if df is None or len(df) == 0:
        print(f"❌ No data for {symbol}")
        return []
    
    # Prepare data
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()
    
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_all_structures(df, displacement_threshold=1.0)
    
    # Backtest settings
    starting_balance = 25000
    balance = starting_balance
    risk_pct = 0.05
    atr_multiple = 5.0
    max_hold_minutes = 60
    
    all_trades = []
    
    # Find confluence signals
    for i in range(len(df) - 5):
        signal_time = df.iloc[i]['timestamp']
        atr = df.iloc[i].get('atr', 0.5)
        entry_price = df.iloc[i]['close']
        
        direction = None
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+6]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                direction = 'LONG'
                target = entry_price + (atr_multiple * atr)
        
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+6]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                direction = 'SHORT'
                target = entry_price - (atr_multiple * atr)
        
        if direction is None:
            continue
        
        # Calculate time to expiry (4:00 PM ET = 21:00 UTC)
        expiry_time = signal_time.replace(hour=21, minute=0, second=0, microsecond=0)
        minutes_to_expiry = (expiry_time - signal_time).total_seconds() / 60
        time_to_expiry_days = minutes_to_expiry / (60 * 6.5)
        
        if time_to_expiry_days <= 0:
            continue
        
        # Estimate entry premium for 1-strike ITM option
        if direction == 'LONG':
            strike = entry_price - 1
            option_type = 'call'
        else:
            strike = entry_price + 1
            option_type = 'put'
        
        entry_premium = estimate_option_premium(
            kind=option_type,
            strike=strike,
            spot=entry_price,
            time_to_expiry_days=time_to_expiry_days,
            base_iv=0.20
        )
        
        # Position sizing: 5% risk, both strategies execute
        risk_amount = balance * risk_pct
        num_contracts = max(1, min(10, int(risk_amount / (entry_premium * 100))))
        total_contracts = num_contracts * 2  # Conservative + Aggressive
        total_cost = total_contracts * entry_premium * 100
        
        # Find exit
        exit_idx = None
        exit_reason = 'TIME'
        
        for j in range(i+1, min(i+max_hold_minutes+1, len(df))):
            if direction == 'LONG' and df.iloc[j]['high'] >= target:
                exit_idx = j
                exit_reason = 'TARGET'
                break
            elif direction == 'SHORT' and df.iloc[j]['low'] <= target:
                exit_idx = j
                exit_reason = 'TARGET'
                break
        
        if exit_idx is None:
            exit_idx = min(i+max_hold_minutes, len(df)-1)
        
        # Calculate exit value
        exit_time = df.iloc[exit_idx]['timestamp']
        exit_price = df.iloc[exit_idx]['close']
        exit_minutes_to_expiry = (expiry_time - exit_time).total_seconds() / 60
        exit_time_to_expiry_days = exit_minutes_to_expiry / (60 * 6.5)
        
        if exit_time_to_expiry_days > 0:
            exit_premium = estimate_option_premium(
                kind=option_type,
                strike=strike,
                spot=exit_price,
                time_to_expiry_days=exit_time_to_expiry_days,
                base_iv=0.20
            )
        else:
            # Expired - intrinsic value only
            if option_type == 'call':
                exit_premium = max(0, exit_price - strike)
            else:
                exit_premium = max(0, strike - exit_price)
        
        total_exit_value = total_contracts * exit_premium * 100
        pnl = total_exit_value - total_cost
        balance += pnl
        
        all_trades.append({
            'symbol': symbol,
            'entry_time': signal_time,
            'exit_time': exit_time,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'target': target,
            'exit_reason': exit_reason,
            'contracts': total_contracts,
            'entry_cost': total_cost,
            'exit_value': total_exit_value,
            'pnl': pnl,
            'won': pnl > 0
        })
    
    print(f"✅ Found {len(all_trades)} trades for {symbol}")
    return all_trades


def load_news_events():
    """Load news events calendar"""
    events_df = pd.read_csv('configs/news_events.csv')
    events_df['date'] = pd.to_datetime(events_df['date'])
    
    # Parse event times (ET timezone)
    et_tz = pytz.timezone('US/Eastern')
    
    def parse_event_datetime(row):
        date_str = row['date'].strftime('%Y-%m-%d')
        time_str = row['event_time_et']
        dt_str = f"{date_str} {time_str}"
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
        return et_tz.localize(dt)
    
    events_df['event_datetime'] = events_df.apply(parse_event_datetime, axis=1)
    
    return events_df


def classify_trades(trades_df, events_df):
    """
    Add classification columns for analysis:
    - weekday
    - hour of day
    - news_day (boolean)
    - news_event_type
    - minutes_from_news
    - within_30m, within_1h, within_2h of news
    """
    # Convert to US/Eastern timezone for consistent analysis
    et_tz = pytz.timezone('US/Eastern')
    trades_df['entry_time_et'] = trades_df['entry_time'].dt.tz_convert(et_tz)
    
    # Weekday (0=Monday, 4=Friday)
    trades_df['weekday'] = trades_df['entry_time_et'].dt.dayofweek
    trades_df['weekday_name'] = trades_df['entry_time_et'].dt.day_name()
    
    # Hour of day (9-16 for market hours)
    trades_df['hour'] = trades_df['entry_time_et'].dt.hour
    trades_df['minute'] = trades_df['entry_time_et'].dt.minute
    
    # Hour bins for analysis
    def hour_bin(row):
        h = row['hour']
        m = row['minute']
        if h == 9 and m >= 30:
            return '09:30-10:29'
        elif h == 10:
            return '10:30-11:29'
        elif h == 11:
            return '11:30-12:29'
        elif h == 12:
            return '12:30-13:29'
        elif h == 13:
            return '13:30-14:29'
        elif h == 14:
            return '14:30-15:29'
        elif h == 15:
            return '15:30-16:00'
        else:
            return 'Other'
    
    trades_df['hour_bin'] = trades_df.apply(hour_bin, axis=1)
    
    # News day classification
    trades_df['trade_date'] = trades_df['entry_time_et'].dt.date
    events_df['event_date'] = events_df['date'].dt.date
    
    # Mark news days
    news_dates = set(events_df['event_date'].unique())
    trades_df['news_day'] = trades_df['trade_date'].isin(news_dates)
    
    # Find closest news event for each trade
    def find_nearest_news(row):
        trade_dt = row['entry_time_et']
        trade_date = row['trade_date']
        
        # Get events on same day
        same_day_events = events_df[events_df['event_date'] == trade_date]
        
        if len(same_day_events) == 0:
            return None, None, None
        
        # Calculate time delta to each event
        deltas = []
        for _, event in same_day_events.iterrows():
            delta_minutes = (trade_dt - event['event_datetime']).total_seconds() / 60
            deltas.append({
                'event_type': event['event_type'],
                'delta_minutes': delta_minutes,
                'abs_delta': abs(delta_minutes)
            })
        
        # Find closest
        closest = min(deltas, key=lambda x: x['abs_delta'])
        
        return closest['event_type'], closest['delta_minutes'], closest['abs_delta']
    
    news_info = trades_df.apply(find_nearest_news, axis=1, result_type='expand')
    news_info.columns = ['news_event_type', 'minutes_from_news', 'abs_minutes_from_news']
    
    trades_df = pd.concat([trades_df, news_info], axis=1)
    
    # Proximity flags
    trades_df['within_30m'] = trades_df['abs_minutes_from_news'].notna() & (trades_df['abs_minutes_from_news'] <= 30)
    trades_df['within_1h'] = trades_df['abs_minutes_from_news'].notna() & (trades_df['abs_minutes_from_news'] <= 60)
    trades_df['within_2h'] = trades_df['abs_minutes_from_news'].notna() & (trades_df['abs_minutes_from_news'] <= 120)
    
    return trades_df


def generate_summary_tables(trades_df):
    """Generate segmented performance summary tables"""
    
    summaries = {}
    
    # 1. Day of Week Analysis
    weekday_summary = trades_df.groupby('weekday_name').agg({
        'pnl': ['count', 'sum', 'mean'],
        'won': 'sum'
    }).reset_index()
    
    weekday_summary.columns = ['weekday', 'total_trades', 'total_pnl', 'avg_pnl', 'wins']
    weekday_summary['win_rate'] = weekday_summary['wins'] / weekday_summary['total_trades']
    weekday_summary['avg_return_pct'] = (weekday_summary['avg_pnl'] / 25000) * 100  # Assume $25k balance
    
    # Add confidence intervals
    weekday_summary['win_ci_low'] = 0.0
    weekday_summary['win_ci_high'] = 0.0
    weekday_summary['sample_ok'] = weekday_summary['total_trades'] >= 20
    
    for idx, row in weekday_summary.iterrows():
        ci_low, ci_high = wilson_confidence_interval(row['wins'], row['total_trades'])
        weekday_summary.at[idx, 'win_ci_low'] = ci_low
        weekday_summary.at[idx, 'win_ci_high'] = ci_high
    
    # Sort by weekday order
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    weekday_summary['weekday'] = pd.Categorical(weekday_summary['weekday'], categories=weekday_order, ordered=True)
    weekday_summary = weekday_summary.sort_values('weekday')
    
    summaries['weekday'] = weekday_summary
    
    # 2. Hour of Day Analysis
    hour_summary = trades_df[trades_df['hour_bin'] != 'Other'].groupby('hour_bin').agg({
        'pnl': ['count', 'sum', 'mean'],
        'won': 'sum'
    }).reset_index()
    
    hour_summary.columns = ['hour_bin', 'total_trades', 'total_pnl', 'avg_pnl', 'wins']
    hour_summary['win_rate'] = hour_summary['wins'] / hour_summary['total_trades']
    hour_summary['avg_return_pct'] = (hour_summary['avg_pnl'] / 25000) * 100
    
    hour_summary['win_ci_low'] = 0.0
    hour_summary['win_ci_high'] = 0.0
    hour_summary['sample_ok'] = hour_summary['total_trades'] >= 20
    
    for idx, row in hour_summary.iterrows():
        ci_low, ci_high = wilson_confidence_interval(row['wins'], row['total_trades'])
        hour_summary.at[idx, 'win_ci_low'] = ci_low
        hour_summary.at[idx, 'win_ci_high'] = ci_high
    
    summaries['hourly'] = hour_summary
    
    # 3. News Day vs Non-News Day
    news_summary = trades_df.groupby('news_day').agg({
        'pnl': ['count', 'sum', 'mean'],
        'won': 'sum'
    }).reset_index()
    
    news_summary.columns = ['news_day', 'total_trades', 'total_pnl', 'avg_pnl', 'wins']
    news_summary['win_rate'] = news_summary['wins'] / news_summary['total_trades']
    news_summary['avg_return_pct'] = (news_summary['avg_pnl'] / 25000) * 100
    news_summary['day_type'] = news_summary['news_day'].map({True: 'News Day', False: 'Normal Day'})
    
    news_summary['win_ci_low'] = 0.0
    news_summary['win_ci_high'] = 0.0
    news_summary['sample_ok'] = news_summary['total_trades'] >= 20
    
    for idx, row in news_summary.iterrows():
        ci_low, ci_high = wilson_confidence_interval(row['wins'], row['total_trades'])
        news_summary.at[idx, 'win_ci_low'] = ci_low
        news_summary.at[idx, 'win_ci_high'] = ci_high
    
    summaries['news_day'] = news_summary[['day_type', 'total_trades', 'total_pnl', 'avg_pnl', 'wins', 'win_rate', 'win_ci_low', 'win_ci_high', 'avg_return_pct', 'sample_ok']]
    
    # 4. News Event Type (for trades on news days only)
    news_trades = trades_df[trades_df['news_day'] == True].copy()
    
    if len(news_trades) > 0:
        event_summary = news_trades.groupby('news_event_type').agg({
            'pnl': ['count', 'sum', 'mean'],
            'won': 'sum'
        }).reset_index()
        
        event_summary.columns = ['event_type', 'total_trades', 'total_pnl', 'avg_pnl', 'wins']
        event_summary['win_rate'] = event_summary['wins'] / event_summary['total_trades']
        event_summary['avg_return_pct'] = (event_summary['avg_pnl'] / 25000) * 100
        
        event_summary['win_ci_low'] = 0.0
        event_summary['win_ci_high'] = 0.0
        event_summary['sample_ok'] = event_summary['total_trades'] >= 20
        
        for idx, row in event_summary.iterrows():
            ci_low, ci_high = wilson_confidence_interval(row['wins'], row['total_trades'])
            event_summary.at[idx, 'win_ci_low'] = ci_low
            event_summary.at[idx, 'win_ci_high'] = ci_high
        
        summaries['news_event_type'] = event_summary
    
    # 5. News Proximity Analysis
    proximity_data = []
    
    for proximity_name, proximity_col in [('Within 30 minutes', 'within_30m'), 
                                           ('Within 1 hour', 'within_1h'), 
                                           ('Within 2 hours', 'within_2h'),
                                           ('Outside 2 hours', None)]:
        if proximity_col is None:
            # Outside 2 hours = news day but not within 2h
            subset = trades_df[(trades_df['news_day'] == True) & (trades_df['within_2h'] == False)]
        else:
            subset = trades_df[trades_df[proximity_col] == True]
        
        if len(subset) > 0:
            wins = subset['won'].sum()
            total = len(subset)
            ci_low, ci_high = wilson_confidence_interval(wins, total)
            
            proximity_data.append({
                'proximity': proximity_name,
                'total_trades': total,
                'total_pnl': subset['pnl'].sum(),
                'avg_pnl': subset['pnl'].mean(),
                'wins': wins,
                'win_rate': wins / total,
                'win_ci_low': ci_low,
                'win_ci_high': ci_high,
                'avg_return_pct': (subset['pnl'].mean() / 25000) * 100,
                'sample_ok': total >= 20
            })
    
    if proximity_data:
        summaries['news_proximity'] = pd.DataFrame(proximity_data)
    
    return summaries


def main():
    """Main execution"""
    print("\n" + "="*70)
    print("COMPREHENSIVE BACKTEST ANALYSIS")
    print("Segmented by: Day of Week, Time of Day, News Events")
    print("="*70)
    
    # Create output directory
    output_dir = Path('reports/analytics')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Load news events
    print("\n📅 Loading news events calendar...")
    events_df = load_news_events()
    print(f"✅ Loaded {len(events_df)} news events (FOMC, CPI, NFP, PCE)")
    
    # Step 2: Run backtests for all symbols
    print("\n📊 Running comprehensive backtests...")
    
    all_trades = []
    
    # QQQ backtest (Jan 2024 - Nov 2025)
    qqq_trades = run_full_backtest('QQQ', '2024-01-02', '2025-11-19')
    all_trades.extend(qqq_trades)
    
    # SPY backtest (Jan 2024 - Nov 2025)
    spy_trades = run_full_backtest('SPY', '2024-01-02', '2025-11-19')
    all_trades.extend(spy_trades)
    
    if len(all_trades) == 0:
        print("\n❌ No trades found. Exiting.")
        return
    
    # Convert to DataFrame
    trades_df = pd.DataFrame(all_trades)
    
    print(f"\n✅ Total trades collected: {len(trades_df)}")
    print(f"   QQQ: {len([t for t in all_trades if t['symbol'] == 'QQQ'])}")
    print(f"   SPY: {len([t for t in all_trades if t['symbol'] == 'SPY'])}")
    
    # Step 3: Classify trades
    print("\n🏷️  Classifying trades by temporal and news factors...")
    trades_df = classify_trades(trades_df, events_df)
    
    # Step 4: Generate summary tables
    print("\n📈 Generating statistical summaries...")
    summaries = generate_summary_tables(trades_df)
    
    # Step 5: Export to CSV
    print("\n💾 Exporting downloadable CSV tables...")
    
    for name, df in summaries.items():
        filepath = output_dir / f'{name}_performance.csv'
        df.to_csv(filepath, index=False)
        print(f"   ✅ {filepath}")
    
    # Also save full trade log
    trade_log_path = output_dir / 'full_trade_log.csv'
    trades_df.to_csv(trade_log_path, index=False)
    print(f"   ✅ {trade_log_path}")
    
    # Print summaries to console
    print("\n" + "="*70)
    print("SUMMARY TABLES")
    print("="*70)
    
    print("\n📅 DAY OF WEEK PERFORMANCE")
    print(summaries['weekday'].to_string(index=False))
    
    print("\n🕐 HOUR OF DAY PERFORMANCE")
    print(summaries['hourly'].to_string(index=False))
    
    print("\n📰 NEWS DAY vs NORMAL DAY")
    print(summaries['news_day'].to_string(index=False))
    
    if 'news_event_type' in summaries:
        print("\n📊 PERFORMANCE BY NEWS EVENT TYPE")
        print(summaries['news_event_type'].to_string(index=False))
    
    if 'news_proximity' in summaries:
        print("\n⏰ PERFORMANCE BY NEWS PROXIMITY")
        print(summaries['news_proximity'].to_string(index=False))
    
    print("\n" + "="*70)
    print(f"✅ ANALYSIS COMPLETE - {len(summaries)} tables exported")
    print(f"📁 Download location: {output_dir.absolute()}")
    print("="*70)


if __name__ == '__main__':
    try:
        from scipy import stats
    except ImportError:
        print("Installing scipy for statistical analysis...")
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'scipy'], check=True)
        from scipy import stats
    
    main()
