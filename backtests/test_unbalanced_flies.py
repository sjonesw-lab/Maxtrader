#!/usr/bin/env python3
"""
Backtest Unbalanced Butterflies (1:-3:+2) vs Long Options
Uses ICT confluence signals with strict sweep detection
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_displacement, detect_mss


def calculate_atr(df, period=14):
    """Calculate ATR."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df


def detect_sweeps_strict(df):
    """STRICT: Exact sweep of session levels."""
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
    """Find ICT confluence signals."""
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
    """0DTE premium estimation."""
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


def construct_unbalanced_butterfly(underlying_price, direction, wing_width=10.0):
    """
    Construct 1:-3:+2 Unbalanced Butterfly.
    
    For CALL UBFly (bullish):
    - Buy 1x ATM call (K_low)
    - Sell 3x ATM+W call (K_body)
    - Buy 2x ATM+2W call (K_high)
    
    Returns: (net_debit, max_profit, body_strike, structure)
    """
    atm_strike = round(underlying_price / 5) * 5
    
    if direction == 'long':
        K_low = atm_strike
        K_body = atm_strike + wing_width
        K_high = atm_strike + 2 * wing_width
        
        # Estimate premiums (simplified for 0DTE ATM)
        prem_low = 2.5
        prem_body = 1.0
        prem_high = 0.3
        
        net_debit = (1 * prem_low) - (3 * prem_body) + (2 * prem_high)
        
        # Max profit occurs at K_body
        max_profit = (K_body - K_low) - net_debit
        
        return {
            'net_debit': net_debit,
            'max_profit': max_profit,
            'K_low': K_low,
            'K_body': K_body,
            'K_high': K_high,
            'wing_width': wing_width,
            'direction': 'call'
        }
    else:
        K_high = atm_strike
        K_body = atm_strike - wing_width
        K_low = atm_strike - 2 * wing_width
        
        prem_high = 2.5
        prem_body = 1.0
        prem_low = 0.3
        
        net_debit = (1 * prem_high) - (3 * prem_body) + (2 * prem_low)
        
        max_profit = (K_high - K_body) - net_debit
        
        return {
            'net_debit': net_debit,
            'max_profit': max_profit,
            'K_low': K_low,
            'K_body': K_body,
            'K_high': K_high,
            'wing_width': wing_width,
            'direction': 'put'
        }


def simulate_ubfly_exit(entry_price, fly_structure, exit_window_df, target_price):
    """
    Simulate UBFly exit logic.
    
    Exit conditions:
    1. Price reaches target (within body) → Max profit zone
    2. Price pins near body at 60% hold time → Take profit
    3. 60-bar timeout → Exit at current value
    4. Price breaches far wing → Significant loss
    """
    K_body = fly_structure['K_body']
    K_low = fly_structure['K_low']
    K_high = fly_structure['K_high']
    W = fly_structure['wing_width']
    net_debit = fly_structure['net_debit']
    max_profit = fly_structure['max_profit']
    
    direction = fly_structure['direction']
    
    for idx in range(len(exit_window_df)):
        bar = exit_window_df.iloc[idx]
        current_price = bar['close']
        
        # Check if target hit (approaching body)
        if direction == 'call':
            # Target is above entry, approaching K_body from below
            if bar['high'] >= target_price:
                # Price is moving toward body, capture profit
                distance_to_body = abs(current_price - K_body)
                if distance_to_body < W * 0.3:  # Within pin zone
                    # Near max profit
                    return max_profit * 0.8, True
                else:
                    # Partial profit
                    return max_profit * 0.5, True
            
            # Breached far wing = loss
            if bar['high'] > K_high:
                return -net_debit * 0.7, False
                
        else:  # put
            if bar['low'] <= target_price:
                distance_to_body = abs(current_price - K_body)
                if distance_to_body < W * 0.3:
                    return max_profit * 0.8, True
                else:
                    return max_profit * 0.5, True
            
            if bar['low'] < K_low:
                return -net_debit * 0.7, False
    
    # Timeout - exit at current value
    final_price = exit_window_df.iloc[-1]['close']
    
    if direction == 'call':
        if K_low < final_price < K_body:
            profit_pct = (final_price - K_low) / W
            return max_profit * profit_pct, False
        elif K_body <= final_price <= K_high:
            profit_pct = (K_high - final_price) / W
            return max_profit * profit_pct, False
        else:
            return -net_debit, False
    else:
        if K_body < final_price < K_high:
            profit_pct = (K_high - final_price) / W
            return max_profit * profit_pct, False
        elif K_low <= final_price <= K_body:
            profit_pct = (final_price - K_low) / W
            return max_profit * profit_pct, False
        else:
            return -net_debit, False


def backtest_ubfly_strategy(df, signals, starting_capital=25000, risk_pct=5.0):
    """Backtest using Unbalanced Butterflies."""
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    market_open = df.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    
    for signal in signals:
        if last_exit_time is not None and signal['timestamp'] <= last_exit_time:
            continue
        
        entry_idx = signal['index'] + 1
        if entry_idx >= len(df):
            continue
        
        entry_price = df.iloc[entry_idx]['open']
        entry_time = df.iloc[entry_idx]['timestamp']
        
        atr_value = signal['atr']
        target_distance = 5.0 * atr_value
        
        if target_distance < 0.15:
            continue
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
        else:
            target_price = entry_price - target_distance
        
        # Construct UBFly with $10 wing width
        fly = construct_unbalanced_butterfly(entry_price, signal['direction'], wing_width=10.0)
        
        # Position size based on net debit
        risk_dollars = account_balance * (risk_pct / 100)
        num_flies = max(1, int(risk_dollars / abs(fly['net_debit'] * 100)))
        num_flies = min(num_flies, 5)  # Cap at 5 units
        
        total_debit = num_flies * fly['net_debit'] * 100
        
        # 60-bar hold
        exit_window_end = min(entry_idx + 60, len(df) - 1)
        exit_window = df.iloc[entry_idx:exit_window_end+1]
        
        if len(exit_window) == 0:
            continue
        
        # Simulate exit
        pnl_per_fly, hit_target = simulate_ubfly_exit(
            entry_price, fly, exit_window, target_price
        )
        
        position_pnl = pnl_per_fly * num_flies
        account_balance += position_pnl
        
        trades.append({
            'timestamp': signal['timestamp'],
            'direction': signal['direction'],
            'hit_target': hit_target,
            'pnl': position_pnl,
            'balance': account_balance,
            'num_flies': num_flies,
            'K_body': fly['K_body']
        })
        
        last_exit_time = exit_window.iloc[-1]['timestamp']
    
    return pd.DataFrame(trades), account_balance


def backtest_long_options(df, signals, starting_capital=25000, risk_pct=5.0):
    """Backtest using Long Options (baseline)."""
    trades = []
    last_exit_time = None
    account_balance = starting_capital
    
    market_open = df.iloc[0]['timestamp'].replace(hour=9, minute=30, second=0, microsecond=0)
    
    for signal in signals:
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
        
        if signal['direction'] == 'long':
            target_price = entry_price + target_distance
            strike = round(entry_price / 5) * 5
        else:
            target_price = entry_price - target_distance
            strike = round(entry_price / 5) * 5
        
        premium_per_contract = estimate_option_premium(entry_price, strike, time_from_open)
        
        risk_dollars = account_balance * (risk_pct / 100)
        num_contracts = int(risk_dollars / (premium_per_contract * 100))
        num_contracts = max(1, min(num_contracts, 10))
        
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
            intrinsic_value = target_distance * 100
            option_value_at_exit = intrinsic_value * num_contracts
        else:
            exit_premium = estimate_option_premium(exit_price, strike, time_at_exit)
            option_value_at_exit = exit_premium * 100 * num_contracts
        
        position_pnl = option_value_at_exit - total_premium_paid
        account_balance += position_pnl
        
        trades.append({
            'timestamp': signal['timestamp'],
            'direction': signal['direction'],
            'hit_target': hit_target,
            'pnl': position_pnl,
            'balance': account_balance
        })
        
        last_exit_time = exit_time
    
    return pd.DataFrame(trades), account_balance


def analyze_performance(trades_df, label, starting_capital=25000):
    """Calculate performance metrics."""
    if len(trades_df) == 0:
        return {
            'label': label,
            'trades': 0,
            'win_rate': 0,
            'return_pct': 0,
            'max_dd_pct': 0
        }
    
    equity = trades_df['balance'].values
    running_max = np.maximum.accumulate(equity)
    drawdown = equity - running_max
    max_dd = drawdown.min()
    max_dd_pct = (max_dd / starting_capital) * 100
    
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    
    total_return = equity[-1] - starting_capital
    return_pct = (total_return / starting_capital) * 100
    
    profit_factor = 0
    if len(losers) > 0 and losers['pnl'].sum() != 0:
        profit_factor = abs(winners['pnl'].sum() / losers['pnl'].sum())
    
    return {
        'label': label,
        'trades': len(trades_df),
        'win_rate': (len(winners) / len(trades_df) * 100) if len(trades_df) > 0 else 0,
        'return_pct': return_pct,
        'max_dd_pct': max_dd_pct,
        'profit_factor': profit_factor,
        'avg_win': winners['pnl'].mean() if len(winners) > 0 else 0,
        'avg_loss': losers['pnl'].mean() if len(losers) > 0 else 0,
        'target_hit_rate': (trades_df['hit_target'].sum() / len(trades_df) * 100) if len(trades_df) > 0 else 0
    }


# ============================================================================
# MAIN TEST
# ============================================================================

print("\n" + "="*80)
print("UNBALANCED BUTTERFLY BACKTEST - 3 MONTHS")
print("="*80)
print("Testing: UBFly (1:-3:+2) vs Long Options")
print("Same ICT signals, different execution structures")
print("="*80)

months = [
    ('2025', '08', 'August'),
    ('2025', '09', 'September'),
    ('2025', '10', 'October')
]

all_data = []
for year, month, name in months:
    path = Path(f'data/polygon_downloads/QQQ_{year}_{month}_1min.csv')
    if path.exists():
        provider = CSVDataProvider(str(path))
        df = provider.load_bars()
        all_data.append(df)
        print(f"✓ Loaded {name} 2025: {len(df)} bars")

if not all_data:
    print("\n❌ No data found!")
    sys.exit(1)

df_all = pd.concat(all_data, ignore_index=True)
print(f"\n✅ Total: {len(df_all)} bars across 3 months")

# Prepare data
df_all = calculate_atr(df_all, period=14)
df_all = label_sessions(df_all)
df_all = add_session_highs_lows(df_all)
df_all = detect_sweeps_strict(df_all)
df_all = detect_displacement(df_all, threshold=1.0)
df_all = detect_mss(df_all)

# Generate signals
signals = find_signals(df_all)
print(f"\n🎯 ICT Confluence Signals: {len(signals)}")

# Test LONG OPTIONS (baseline)
print("\n" + "="*80)
print("STRATEGY 1: LONG OPTIONS (Baseline)")
print("="*80)

trades_long, final_long = backtest_long_options(df_all, signals)
metrics_long = analyze_performance(trades_long, "Long Options")

print(f"Total Trades:    {metrics_long['trades']}")
print(f"Win Rate:        {metrics_long['win_rate']:.1f}%")
print(f"Target Hit Rate: {metrics_long['target_hit_rate']:.1f}%")
print(f"3-Month Return:  {metrics_long['return_pct']:.2f}%")
print(f"Max Drawdown:    {metrics_long['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_long['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_long['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_long['avg_loss']:.2f}")

# Test UNBALANCED BUTTERFLIES
print("\n" + "="*80)
print("STRATEGY 2: UNBALANCED BUTTERFLIES (1:-3:+2)")
print("="*80)

trades_ubfly, final_ubfly = backtest_ubfly_strategy(df_all, signals)
metrics_ubfly = analyze_performance(trades_ubfly, "Unbalanced Fly")

print(f"Total Trades:    {metrics_ubfly['trades']}")
print(f"Win Rate:        {metrics_ubfly['win_rate']:.1f}%")
print(f"Target Hit Rate: {metrics_ubfly['target_hit_rate']:.1f}%")
print(f"3-Month Return:  {metrics_ubfly['return_pct']:.2f}%")
print(f"Max Drawdown:    {metrics_ubfly['max_dd_pct']:.2f}%")
print(f"Profit Factor:   {metrics_ubfly['profit_factor']:.2f}")
print(f"Avg Win:         ${metrics_ubfly['avg_win']:.2f}")
print(f"Avg Loss:        ${metrics_ubfly['avg_loss']:.2f}")

# COMPARISON
print("\n" + "="*80)
print("COMPARISON & VERDICT")
print("="*80)

delta_return = metrics_ubfly['return_pct'] - metrics_long['return_pct']
delta_dd = metrics_ubfly['max_dd_pct'] - metrics_long['max_dd_pct']
delta_wr = metrics_ubfly['win_rate'] - metrics_long['win_rate']

print(f"Win Rate:        {metrics_long['win_rate']:.1f}% → {metrics_ubfly['win_rate']:.1f}% ({delta_wr:+.1f}%)")
print(f"3-Month Return:  {metrics_long['return_pct']:.2f}% → {metrics_ubfly['return_pct']:.2f}% ({delta_return:+.2f}%)")
print(f"Max Drawdown:    {metrics_long['max_dd_pct']:.2f}% → {metrics_ubfly['max_dd_pct']:.2f}% ({delta_dd:+.2f}%)")

print("\n" + "="*80)
print("VERDICT")
print("="*80)

if metrics_ubfly['return_pct'] > metrics_long['return_pct'] * 1.2:
    print("✅ UNBALANCED BUTTERFLIES WIN")
    print(f"   → {delta_return:+.1f}% better returns")
    print(f"   → Defined risk with capped loss")
    print(f"   → Better capital efficiency")
elif delta_return > 0 and delta_dd < 10:
    print("✅ UNBALANCED BUTTERFLIES RECOMMENDED")
    print(f"   → Higher returns with acceptable drawdown")
else:
    print("⚠️  STICK WITH LONG OPTIONS")
    print(f"   → Simpler execution, similar performance")

print("="*80 + "\n")
