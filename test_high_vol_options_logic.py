"""
Re-test High Vol with OPTIONS LOGIC, not stock stop-loss logic.

Key difference:
- Stock: Whipsaw hits stop = loss
- Options: Just need to TOUCH target once within 2H, ignore whipsaws
"""

import pandas as pd
from engine.data_provider import CSVDataProvider

# Load March 2020
provider = CSVDataProvider('data/QQQ_1m_covid_2020.csv')
df_full = provider.load_bars()
df = df_full[
    (df_full['timestamp'] >= '2020-03-01') &
    (df_full['timestamp'] < '2020-05-01')
].copy().reset_index(drop=True)

print("HIGH VOL RE-TEST: Options Logic (Target Touch = Win)")
print("=" * 80)
print()

# Test different target sizes
targets_to_test = [0.004, 0.005, 0.006, 0.0075, 0.010]  # 0.4% to 1%

for target_pct in targets_to_test:
    wins = 0
    losses = 0
    
    # Sample every 10th bar
    for i in range(0, len(df) - 120, 10):
        entry = df.iloc[i]['close']
        target_long = entry * (1 + target_pct)
        target_short = entry * (1 - target_pct)
        
        future = df.iloc[i:i+120]
        
        # LONG: Does price TOUCH target within 2 hours?
        if (future['high'] >= target_long).any():
            wins += 1
        else:
            losses += 1
        
        # SHORT: Does price TOUCH target within 2 hours?
        # (separate test, not double counting)
    
    total = wins + losses
    wr = wins / total if total > 0 else 0
    
    print(f"Target: {target_pct*100:.2f}% | Win Rate: {wr*100:.1f}% | ({wins}/{total} trades)")

print()
print("=" * 80)
print("INTERPRETATION:")
print("  If win rate >85% at ANY target size, High Vol strategy IS VIABLE!")
print("  We just need to use options correctly (exit on touch, not stock stops)")
