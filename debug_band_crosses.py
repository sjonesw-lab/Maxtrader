"""Debug why band cross/reclaim isn't triggering."""

from engine.data_provider import CSVDataProvider
from engine.strategy_shared import calculate_atr

provider = CSVDataProvider('data/QQQ_1m_ultralowvol_2017.csv')
df = provider.load_bars()

# Sample window
start, end = 1000, 1200
sample = df.iloc[start:end].copy()

print("Checking band cross/reclaim patterns in 2017 data...")
print()

crosses_found = 0
for i in range(50, len(sample)):
    window = sample.iloc[max(0, i-50):i+1]
    
    # VWAP
    typical = (window['high'] + window['low'] + window['close']) / 3
    if window['volume'].sum() > 0:
        vwap = (typical * window['volume']).sum() / window['volume'].sum()
    else:
        vwap = typical.mean()
    
    # Std dev
    std = (typical - vwap).std()
    
    # ATR
    atr = calculate_atr(window, period=14)
    
    # Threshold
    threshold = max(0.02, min(0.5 * atr, 1.0 * std))
    lower_band = vwap - threshold
    upper_band = vwap + threshold
    
    if i > 0:
        prev = sample.iloc[i-1]
        curr = sample.iloc[i]
        
        # Check for band cross + reclaim
        if prev['close'] < lower_band and curr['close'] > lower_band:
            crosses_found += 1
            if crosses_found <= 5:
                print(f"LONG: Bar {i}")
                print(f"  Prev close: ${prev['close']:.2f} < ${lower_band:.2f}")
                print(f"  Curr close: ${curr['close']:.2f} > ${lower_band:.2f}")
        
        if prev['close'] > upper_band and curr['close'] < upper_band:
            crosses_found += 1
            if crosses_found <= 5:
                print(f"SHORT: Bar {i}")
                print(f"  Prev close: ${prev['close']:.2f} > ${upper_band:.2f}")
                print(f"  Curr close: ${curr['close']:.2f} < ${upper_band:.2f}")

print()
print(f"Total crosses found in sample ({len(sample)} bars): {crosses_found}")

if crosses_found == 0:
    print()
    print("❌ NO CROSSES - Bands oscillate WITH price, never crossed!")
    print()
    print("The issue: VWAP is calculated from same window as bands,")
    print("so price rarely crosses because VWAP moves with it.")
    print()
    print("Solution: Use FIXED VWAP (session start) not rolling VWAP")
