"""Generate sample QQQ 1-minute data for backtesting."""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

np.random.seed(42)

start_date = datetime(2024, 1, 2, 0, 0, 0)
days = 5
base_price = 390.0

timestamps = []
opens = []
highs = []
lows = []
closes = []
volumes = []

current_price = base_price

for day in range(days):
    day_start = start_date + timedelta(days=day)
    
    for hour in range(24):
        for minute in range(60):
            ts = day_start + timedelta(hours=hour, minutes=minute)
            
            change = np.random.randn() * 0.5
            current_price = max(current_price + change, base_price * 0.9)
            current_price = min(current_price, base_price * 1.1)
            
            o = current_price
            c = current_price + np.random.randn() * 0.3
            h = max(o, c) + abs(np.random.randn()) * 0.2
            l = min(o, c) - abs(np.random.randn()) * 0.2
            v = int(np.random.uniform(100000, 500000))
            
            timestamps.append(ts.isoformat() + 'Z')
            opens.append(round(o, 2))
            highs.append(round(h, 2))
            lows.append(round(l, 2))
            closes.append(round(c, 2))
            volumes.append(v)
            
            current_price = c

df = pd.DataFrame({
    'timestamp': timestamps,
    'open': opens,
    'high': highs,
    'low': lows,
    'close': closes,
    'volume': volumes
})

df.to_csv('data/sample_QQQ_1m.csv', index=False)
print(f"Generated {len(df)} bars of sample data")
print(f"Date range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
