"""
Calculate Sharpe Ratio for High Vol strategy with OPTIONS PRICING

70% WR at 0.2% targets - but what's the actual P&L after premium?
"""

import pandas as pd
import numpy as np
from engine.data_provider import CSVDataProvider
from engine.strategy_shared import preprocess_market_data
from engine.strategy_high_vol import HighVolStrategy
from engine.regime_router import calculate_vix_proxy
from engine.timeframes import resample_to_timeframe

# Load March-April 2020 (VIX 40-80)
provider = CSVDataProvider('data/QQQ_1m_covid_2020.csv')
df_full = provider.load_bars()
df = df_full[
    (df_full['timestamp'] >= '2020-03-01') &
    (df_full['timestamp'] < '2020-05-01')
].copy().reset_index(drop=True)

df_daily = resample_to_timeframe(df, '1d')
vix = calculate_vix_proxy(df_daily, lookback=20)
context = preprocess_market_data(df, vix=vix, renko_k=4.0)

# Generate signals
strategy = HighVolStrategy()
signals = strategy.generate_signals(context)

print("HIGH VOL SHARPE CALCULATION (0.2% Targets, Options Pricing)")
print("=" * 80)
print()

# Simulate with realistic 0DTE options pricing
TARGET_PCT = 0.002  # 0.2% target
HOLD_BARS = 120  # 2 hours max

trade_returns = []

for sig in signals:
    idx = sig.index
    entry = sig.spot
    
    # 0.2% target
    if sig.direction == 'long':
        target = entry * (1 + TARGET_PCT)
    else:
        target = entry * (1 - TARGET_PCT)
    
    # Target profit in dollars
    target_profit = abs(target - entry)
    
    # Options premium estimation for 0DTE during high vol
    # Assume we're buying ATM options with ~2H to expiry in VIX 40-80 environment
    # Use simplified Black-Scholes for 0DTE
    time_to_expiry = 2/24/252  # 2 hours in years
    implied_vol = 0.80  # 80% IV during COVID crash
    
    # ATM option premium ≈ 0.4 * stock_price * IV * sqrt(T)
    # For 0DTE with 2H: premium ≈ $0.40-0.60 typically
    # But in VIX 80, multiply by ~2x
    atm_premium = 0.4 * entry * implied_vol * np.sqrt(time_to_expiry)
    
    # For $215 stock, 0.2% OTM option costs ~50-70% of ATM
    strike_distance = 0.002  # 0.2% OTM
    otm_multiplier = 0.60
    premium_paid = atm_premium * otm_multiplier
    
    # Check if target hit
    future = context.df_1min.iloc[idx:idx+HOLD_BARS]
    if len(future) < 2:
        continue
    
    if sig.direction == 'long':
        hit = (future['high'] >= target).any()
    else:
        hit = (future['low'] <= target).any()
    
    # Calculate P&L
    if hit:
        # WIN: Intrinsic value at target - premium paid
        intrinsic = target_profit  # $0.43 for 0.2% on $215
        pnl = intrinsic - premium_paid
        r_multiple = pnl / premium_paid if premium_paid > 0 else 0
    else:
        # LOSS: Lose full premium
        pnl = -premium_paid
        r_multiple = -1.0  # Lose 1R (full premium)
    
    trade_returns.append(r_multiple)

# Calculate statistics
returns = np.array(trade_returns)
mean_return = returns.mean()
std_return = returns.std()
sharpe = mean_return / std_return if std_return > 0 else 0

win_count = sum(1 for r in returns if r > 0)
total = len(returns)
actual_wr = win_count / total if total > 0 else 0

print(f"Total Trades: {total}")
print(f"Win Rate: {actual_wr*100:.1f}%")
print(f"Avg Return per Trade: {mean_return:.3f}R")
print(f"Std Dev of Returns: {std_return:.3f}")
print(f"Sharpe Ratio: {sharpe:.3f}")
print()

# Calculate total P&L in dollars
avg_premium = returns.mean() if len(returns) == 0 else 0
sample_premium = 0.4 * 215 * 0.80 * np.sqrt(2/24/252) * 0.60  # ~$1.20
total_pnl = sum(trade_returns) * sample_premium
print(f"Estimated Premium per Trade: ${sample_premium:.2f}")
print(f"Total P&L (all trades): ${total_pnl:.2f}")
print()

print("=" * 80)
print("INTERPRETATION:")
print()
if sharpe > 2.0:
    print("✅ EXCELLENT (Sharpe >2.0) - Strategy is viable!")
elif sharpe > 1.0:
    print("✓ GOOD (Sharpe >1.0) - Strategy works but needs position sizing")
elif sharpe > 0.5:
    print("⚠️  MARGINAL (Sharpe >0.5) - Barely profitable, high risk")
elif sharpe > 0:
    print("⚠️  WEAK (Sharpe >0) - Profitable but very noisy")
else:
    print("❌ NEGATIVE (Sharpe <0) - Strategy loses money")

print()
print("For comparison:")
print("  - S&P 500 long-term Sharpe: ~0.4")
print("  - Good trading strategy: >1.0")
print("  - Excellent strategy: >2.0")
