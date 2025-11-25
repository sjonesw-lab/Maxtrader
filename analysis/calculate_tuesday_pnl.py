"""
Calculate P&L for Tuesday Nov 25 missed trades
Uses realistic 1-strike ITM 0DTE options pricing
"""
import sys
sys.path.insert(0, '.')

import pandas as pd
from engine.polygon_data_fetcher import PolygonDataFetcher
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.ict_structures import detect_all_structures

def calculate_atr(df: pd.DataFrame, period=14) -> pd.Series:
    """Calculate ATR."""
    df = df.copy()
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift(1))
    df['l-pc'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
    return df['tr'].rolling(window=period).mean()

def calculate_options_pnl(entry_price: float, exit_price: float, direction: str, 
                          risk_amount: float, atr: float) -> float:
    """
    Calculate realistic 0DTE 1-strike ITM options P&L.
    
    ITM options have ~100-150% delta (move more than underlying).
    Risk amount is the premium paid (max loss).
    """
    # Price movement in ATR units
    if direction == 'LONG':
        move_atr = (exit_price - entry_price) / atr
    else:  # SHORT
        move_atr = (entry_price - exit_price) / atr
    
    # ITM options leverage factor: ~120% of underlying move
    # For 5x ATR target, winning trades typically return 3-6x risk
    leverage_factor = 1.2
    
    # P&L as multiple of risk amount
    pnl_multiple = move_atr * leverage_factor
    
    # Cap losses at risk amount (premium paid)
    if pnl_multiple < -1.0:
        pnl_multiple = -1.0
    
    return risk_amount * pnl_multiple

def main():
    print("\n" + "="*80)
    print("TUESDAY NOV 25, 2025 - P&L CALCULATION")
    print("="*80 + "\n")
    
    # Fetch data
    fetcher = PolygonDataFetcher()
    df = fetcher.fetch_stock_bars('QQQ', '2025-11-25', '2025-11-25')
    
    if df is None or len(df) == 0:
        print("❌ No data")
        return
    
    # Detect signals
    df = df.copy()
    df['atr'] = calculate_atr(df)
    df = label_sessions(df)
    df = add_session_highs_lows(df)
    df = detect_all_structures(df, displacement_threshold=1.0)
    
    # Find signals
    signals = []
    for i in range(len(df) - 6):
        # Bullish
        if df.iloc[i]['sweep_bullish']:
            window = df.iloc[i:i+7]
            if window['displacement_bullish'].any() and window['mss_bullish'].any():
                atr = df.iloc[i]['atr']
                price = df.iloc[i]['close']
                target = price + (5.0 * atr)
                
                future = df.iloc[i+1:i+61]
                if len(future) > 0:
                    hit_target = (future['high'] >= target).any()
                    if hit_target:
                        exit_price = target
                    else:
                        exit_price = future.iloc[-1]['close']
                    
                    signals.append({
                        'time': df.iloc[i]['timestamp'],
                        'direction': 'LONG',
                        'entry': price,
                        'exit': exit_price,
                        'target': target,
                        'hit_target': hit_target,
                        'atr': atr
                    })
        
        # Bearish
        if df.iloc[i]['sweep_bearish']:
            window = df.iloc[i:i+7]
            if window['displacement_bearish'].any() and window['mss_bearish'].any():
                atr = df.iloc[i]['atr']
                price = df.iloc[i]['close']
                target = price - (5.0 * atr)
                
                future = df.iloc[i+1:i+61]
                if len(future) > 0:
                    hit_target = (future['low'] <= target).any()
                    if hit_target:
                        exit_price = target
                    else:
                        exit_price = future.iloc[-1]['close']
                    
                    signals.append({
                        'time': df.iloc[i]['timestamp'],
                        'direction': 'SHORT',
                        'entry': price,
                        'exit': exit_price,
                        'target': target,
                        'hit_target': hit_target,
                        'atr': atr
                    })
    
    # Account setup
    starting_balance = 25000
    risk_pct = 0.05  # 5% per trade
    
    print(f"📊 ACCOUNT SETUP:")
    print(f"   Starting Balance: ${starting_balance:,.2f}")
    print(f"   Risk Per Trade:   {risk_pct*100:.1f}%")
    print(f"   Risk Amount:      ${starting_balance * risk_pct:,.2f}\n")
    
    # Calculate P&L for each trade
    print("="*80)
    print("TRADES")
    print("="*80)
    
    total_pnl = 0
    risk_amount = starting_balance * risk_pct
    
    for i, sig in enumerate(signals, 1):
        pnl = calculate_options_pnl(
            sig['entry'], 
            sig['exit'], 
            sig['direction'], 
            risk_amount,
            sig['atr']
        )
        total_pnl += pnl
        
        status = "✅ WIN" if sig['hit_target'] else "❌ LOSS"
        time_str = sig['time'].strftime('%I:%M %p ET')
        
        print(f"\nTrade #{i} - {time_str}")
        print(f"  Direction:  {sig['direction']}")
        print(f"  Entry:      ${sig['entry']:.2f}")
        print(f"  Exit:       ${sig['exit']:.2f}")
        print(f"  Target:     ${sig['target']:.2f}")
        print(f"  Result:     {status}")
        print(f"  P&L:        ${pnl:+,.2f} ({pnl/risk_amount*100:+.1f}% of risk)")
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    wins = sum(1 for s in signals if s['hit_target'])
    losses = len(signals) - wins
    
    print(f"\nTotal Trades:     {len(signals)}")
    print(f"Winners:          {wins}")
    print(f"Losers:           {losses}")
    print(f"Win Rate:         {wins/len(signals)*100:.1f}%")
    
    print(f"\n💰 P&L:")
    print(f"   Total P&L:        ${total_pnl:+,.2f}")
    print(f"   Return on Risk:   {total_pnl/(risk_amount*len(signals))*100:+.1f}%")
    print(f"   Account Return:   {total_pnl/starting_balance*100:+.2f}%")
    print(f"\n   Final Balance:    ${starting_balance + total_pnl:,.2f}")
    
    if total_pnl > 0:
        print(f"\n✅ Profitable day - missed ${total_pnl:,.2f} in gains")
    else:
        print(f"\n⚠️  Losing day - avoided ${abs(total_pnl):,.2f} in losses")

if __name__ == '__main__':
    main()
