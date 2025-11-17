"""
Multi-Instrument Smart Money + Homma MTF Backtest
Tests across stocks (SPY, QQQ, IWM, DIA) and forex (EUR/USD, GBP/USD)
"""
import pandas as pd
import numpy as np
from engine.polygon_data_fetcher import PolygonDataFetcher
from strategies.smartmoney_homma_mtf import SmartMoneyHommaMTF
from engine.data_provider import CSVDataProvider
import os


def run_single_instrument_backtest(df_1m, instrument_name, htf='1h', ltf='5min'):
    """
    Run backtest on a single instrument
    
    Returns:
        Dict with performance metrics
    """
    print(f"\n{'='*70}")
    print(f"Testing {instrument_name} (HTF={htf}, LTF={ltf})")
    print(f"{'='*70}")
    
    strategy = SmartMoneyHommaMTF(
        htf_timeframe=htf,
        ltf_timeframe=ltf,
        min_impulse_pct=0.003,
        min_reward_risk=2.0,
        max_holding_bars=60
    )
    
    signals = strategy.generate_signals(df_1m)
    
    if signals.empty:
        print(f"  No signals generated for {instrument_name}")
        return {
            'instrument': instrument_name,
            'trades': 0,
            'win_rate': 0,
            'avg_r': 0,
            'profit_factor': 0,
            'total_pnl': 0,
            'sharpe': 0
        }
    
    # Simulate trades
    trades = []
    for idx, signal in signals.iterrows():
        entry_price = signal['entry_price']
        stop_loss = signal['stop_loss']
        take_profit = signal['take_profit']
        direction = signal['direction']
        
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        
        # Simulate execution over next 60 bars
        entry_time = signal['timestamp']
        future_bars = df_1m[df_1m['timestamp'] > entry_time].head(60)
        
        if future_bars.empty:
            continue
        
        hit_tp = False
        hit_sl = False
        
        for _, bar in future_bars.iterrows():
            if direction == 'long':
                if bar['high'] >= take_profit:
                    hit_tp = True
                    break
                elif bar['low'] <= stop_loss:
                    hit_sl = True
                    break
            else:  # short
                if bar['low'] <= take_profit:
                    hit_tp = True
                    break
                elif bar['high'] >= stop_loss:
                    hit_sl = True
                    break
        
        if hit_tp:
            pnl = reward
            r_multiple = reward / risk
        elif hit_sl:
            pnl = -risk
            r_multiple = -1.0
        else:
            # Hold to expiry
            exit_price = future_bars.iloc[-1]['close']
            if direction == 'long':
                pnl = exit_price - entry_price
            else:
                pnl = entry_price - exit_price
            r_multiple = pnl / risk
        
        trades.append({
            'entry_time': entry_time,
            'direction': direction,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'pnl': pnl,
            'r_multiple': r_multiple,
            'hit_tp': hit_tp,
            'hit_sl': hit_sl
        })
    
    if len(trades) == 0:
        print(f"  No completed trades for {instrument_name}")
        return {
            'instrument': instrument_name,
            'trades': 0,
            'win_rate': 0,
            'avg_r': 0,
            'profit_factor': 0,
            'total_pnl': 0,
            'sharpe': 0
        }
    
    # Calculate metrics
    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df['r_multiple'] > 0]
    losses = trades_df[trades_df['r_multiple'] < 0]
    
    win_rate = len(wins) / len(trades_df) if len(trades_df) > 0 else 0
    avg_r = trades_df['r_multiple'].mean()
    
    total_wins = wins['pnl'].sum() if len(wins) > 0 else 0
    total_losses = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    sharpe = (trades_df['r_multiple'].mean() / trades_df['r_multiple'].std()) if trades_df['r_multiple'].std() > 0 else 0
    
    print(f"  Trades: {len(trades_df)}")
    print(f"  WR: {win_rate*100:.1f}%")
    print(f"  Avg R: {avg_r:.2f}")
    print(f"  PF: {profit_factor:.2f}")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  Sharpe: {sharpe:.2f}")
    
    return {
        'instrument': instrument_name,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'avg_r': avg_r,
        'profit_factor': profit_factor,
        'total_pnl': total_pnl,
        'sharpe': sharpe,
        'trades_data': trades_df
    }


def main():
    print("="*90)
    print("MULTI-INSTRUMENT SMART MONEY + HOMMA MTF BACKTEST")
    print("Testing across stocks (SPY, QQQ, IWM, DIA) + forex (EUR/USD, GBP/USD)")
    print("Using REAL Polygon.io data")
    print("="*90)
    
    # Define instruments
    instruments = [
        {'type': 'stock', 'ticker': 'SPY', 'name': 'SPY (S&P 500)'},
        {'type': 'stock', 'ticker': 'QQQ', 'name': 'QQQ (NASDAQ)'},
        {'type': 'stock', 'ticker': 'IWM', 'name': 'IWM (Russell 2000)'},
        {'type': 'stock', 'ticker': 'DIA', 'name': 'DIA (Dow Jones)'},
        {'type': 'forex', 'from': 'EUR', 'to': 'USD', 'name': 'EUR/USD'},
        {'type': 'forex', 'from': 'GBP', 'to': 'USD', 'name': 'GBP/USD'}
    ]
    
    # Test period: Aug 18 - Nov 14, 2025
    from_date = '2025-08-18'
    to_date = '2025-11-14'
    
    # Check if we have cached data
    data_dir = 'data/multi_instrument'
    os.makedirs(data_dir, exist_ok=True)
    
    fetcher = PolygonDataFetcher()
    all_results = []
    
    for instrument in instruments:
        print(f"\n{'='*90}")
        
        if instrument['type'] == 'stock':
            ticker = instrument['ticker']
            csv_path = f"{data_dir}/{ticker}_1m_{from_date}_{to_date}.csv"
            
            # Fetch or load data
            if os.path.exists(csv_path):
                print(f"Loading cached data for {ticker}...")
                df = pd.read_csv(csv_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            else:
                df = fetcher.fetch_stock_bars(ticker, from_date, to_date)
                fetcher.save_to_csv(df, csv_path)
            
            # Run backtest
            result = run_single_instrument_backtest(df, instrument['name'])
            all_results.append(result)
            
        elif instrument['type'] == 'forex':
            from_curr = instrument['from']
            to_curr = instrument['to']
            pair_name = f"{from_curr}{to_curr}"
            csv_path = f"{data_dir}/{pair_name}_1m_{from_date}_{to_date}.csv"
            
            # Fetch or load data
            if os.path.exists(csv_path):
                print(f"Loading cached data for {pair_name}...")
                df = pd.read_csv(csv_path)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            else:
                df = fetcher.fetch_forex_bars(from_curr, to_curr, from_date, to_date)
                fetcher.save_to_csv(df, csv_path)
            
            # Run backtest
            result = run_single_instrument_backtest(df, instrument['name'])
            all_results.append(result)
    
    # Aggregate statistics
    print("\n" + "="*90)
    print("MULTI-INSTRUMENT AGGREGATE STATISTICS")
    print("="*90)
    
    results_df = pd.DataFrame([{
        'instrument': r['instrument'],
        'trades': r['trades'],
        'win_rate': r['win_rate'],
        'avg_r': r['avg_r'],
        'profit_factor': r['profit_factor'],
        'total_pnl': r['total_pnl'],
        'sharpe': r['sharpe']
    } for r in all_results])
    
    print(results_df.to_string(index=False))
    
    # Combined statistics
    total_trades = results_df['trades'].sum()
    
    # Combine all trades across instruments
    all_trades = []
    for result in all_results:
        if result['trades'] > 0 and 'trades_data' in result:
            all_trades.append(result['trades_data'])
    
    if all_trades:
        combined_trades = pd.concat(all_trades, ignore_index=True)
        
        combined_wr = len(combined_trades[combined_trades['r_multiple'] > 0]) / len(combined_trades)
        combined_avg_r = combined_trades['r_multiple'].mean()
        
        wins = combined_trades[combined_trades['r_multiple'] > 0]
        losses = combined_trades[combined_trades['r_multiple'] < 0]
        total_wins = wins['pnl'].sum() if len(wins) > 0 else 0
        total_losses = abs(losses['pnl'].sum()) if len(losses) > 0 else 0
        combined_pf = total_wins / total_losses if total_losses > 0 else 0
        
        combined_pnl = combined_trades['pnl'].sum()
        combined_sharpe = (combined_trades['r_multiple'].mean() / combined_trades['r_multiple'].std()) if combined_trades['r_multiple'].std() > 0 else 0
        
        print("\n" + "="*90)
        print("COMBINED PORTFOLIO STATISTICS")
        print("="*90)
        print(f"Total Instruments: {len(instruments)}")
        print(f"Total Trades: {total_trades}")
        print(f"Combined Win Rate: {combined_wr*100:.1f}%")
        print(f"Combined Avg R: {combined_avg_r:.2f}")
        print(f"Combined Profit Factor: {combined_pf:.2f}")
        print(f"Combined P&L: ${combined_pnl:.2f}")
        print(f"Combined Sharpe: {combined_sharpe:.2f}")
        print(f"\nTrade Frequency: {total_trades} trades / 90 days = {total_trades/3:.1f} trades/month")
        print(f"Annualized: ~{total_trades/3*12:.0f} trades/year")
        
        # Diversification benefit
        avg_single_sharpe = results_df[results_df['sharpe'] > 0]['sharpe'].mean()
        if avg_single_sharpe > 0:
            diversification_ratio = combined_sharpe / avg_single_sharpe
            print(f"\nDiversification Benefit: {diversification_ratio:.2f}x")
    
    print("\n" + "="*90)
    print("EVALUATION")
    print("="*90)
    if total_trades >= 15:
        print("✓ Trade frequency target MET (≥15 trades/90 days)")
    else:
        print(f"✗ Trade frequency target NOT MET ({total_trades} < 15 trades/90 days)")
    
    if total_trades >= 15 and combined_wr >= 0.55 and combined_avg_r >= 0.5:
        print("✓ Strategy is production-ready for multi-instrument deployment")
    else:
        print("⚠ Strategy needs further refinement")


if __name__ == '__main__':
    main()
