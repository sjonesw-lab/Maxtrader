#!/usr/bin/env python3
"""
Backtest specific downloaded months.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy_wave_renko import generate_wave_signals
from engine.strategy import Signal
from engine.backtest import Backtest
from engine.timeframes import resample_to_timeframe
from engine.ict_structures import detect_all_structures


def run_backtest(data_file: str):
    """Run backtest on a specific data file."""
    print(f"\n{'='*70}")
    print(f"📊 BACKTESTING: {data_file}")
    print(f"{'='*70}")
    
    data_path = Path(f'data/polygon_downloads/{data_file}')
    
    # Load data
    provider = CSVDataProvider(str(data_path))
    df_1min = provider.load_bars()
    
    print(f"Loaded {len(df_1min):,} bars")
    print(f"Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")
    
    # Resample to 4H and Daily
    df_4h = resample_to_timeframe(df_1min, '4h')
    df_daily = resample_to_timeframe(df_1min, '1D')
    
    # Label sessions
    df_1min = label_sessions(df_1min)
    df_1min = add_session_highs_lows(df_1min)
    
    # Detect ICT structures
    df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
    
    # Build Renko
    k_value = 4.0
    renko_df = build_renko(df_1min, mode="atr", k=k_value, atr_period=14)
    brick_size = renko_df['brick_size'].iloc[0]
    
    print(f"Built {len(renko_df)} Renko bricks (size: ${brick_size:.2f})")
    
    # Detect regime
    df_30min = resample_to_timeframe(df_1min, '30min')
    renko_30min = build_renko(df_30min, mode="atr", k=1.0)
    renko_direction_30min = get_renko_direction_series(df_30min, renko_30min)
    regime_30min = detect_regime(df_30min, renko_direction_30min, lookback=20)
    
    # Align regime to 1-min data
    df_1min['regime'] = 'sideways'
    for idx in range(len(df_1min)):
        ts = df_1min['timestamp'].iloc[idx]
        mask = df_30min['timestamp'] <= ts
        if mask.any():
            regime_idx = mask.sum() - 1
            if regime_idx < len(regime_30min):
                df_1min.loc[df_1min.index[idx], 'regime'] = regime_30min.iloc[regime_idx]
    
    # Generate signals
    wave_signals = generate_wave_signals(
        df_1min=df_1min,
        df_4h=df_4h,
        df_daily=df_daily,
        renko_df=renko_df,
        regime_series=df_1min['regime'],
        brick_size=brick_size,
        min_bricks=3,
        max_entry_distance=1.5,
        min_confidence=0.40,
        use_ict_boost=False,
        target_mode='swing_75',
        require_sweep=False,
        use_volume_filter=False,
        avoid_lunch_chop=False,
        use_dynamic_targets=False,
        min_rr_ratio=2.0
    )
    
    print(f"✅ Generated {len(wave_signals)} wave signals")
    
    # Convert to standard Signal format
    signals = []
    for ws in wave_signals:
        matching = df_1min[df_1min['timestamp'] == ws.timestamp]
        if not matching.empty:
            sig = Signal(
                index=matching.index[0],
                timestamp=ws.timestamp,
                direction=ws.direction,
                spot=ws.spot,
                target=ws.tp1,
                source_session=None,
                meta={
                    'wave_height': ws.wave_height,
                    'tp1': ws.tp1,
                    'tp2': ws.tp2,
                    'stop': ws.stop,
                    'retrace_type': ws.retrace_type,
                    'retrace_pct': ws.retrace_pct,
                    'confidence': ws.meta['confidence'],
                    'regime': ws.regime
                }
            )
            signals.append(sig)
    
    # Run backtest
    backtest = Backtest(df_1min, min_rr_ratio=1.6, use_scaling_exit=False)
    results = backtest.run(signals, max_bars_held=120)
    
    # Print results
    print(f"\n📈 RESULTS:")
    print(f"   Signals Generated: {len(signals)}")
    print(f"   Total Trades: {results.get('total_trades', 0)}")
    print(f"   Winning Trades: {results.get('winning_trades', 0)}")
    print(f"   Losing Trades: {results.get('losing_trades', 0)}")
    print(f"   Win Rate: {results.get('win_rate', 0.0):.1f}%")
    print(f"   Profit Factor: {results.get('profit_factor', 0.0):.2f}")
    print(f"   Total P&L: ${results.get('total_pnl', 0.0):,.2f}")
    print(f"   Avg Win: ${results.get('avg_win', 0.0):,.2f}")
    print(f"   Avg Loss: ${results.get('avg_loss', 0.0):,.2f}")
    print(f"   Sharpe Ratio: {results.get('sharpe_ratio', 0.0):.2f}")
    print(f"   Max Drawdown: ${results.get('max_drawdown', 0.0):,.2f}")
    
    return results


if __name__ == '__main__':
    print("\n" + "="*70)
    print("🎯 SPECIFIC MONTH BACKTEST")
    print("="*70)
    
    # Backtest the 3 most recent months from downloads
    months = [
        'QQQ_2021_05_1min.csv',  # May 2021
        'QQQ_2022_04_1min.csv',  # April 2022
        'QQQ_2023_06_1min.csv'   # June 2023
    ]
    
    all_results = []
    
    for month_file in months:
        try:
            result = run_backtest(month_file)
            all_results.append({
                'month': month_file.replace('QQQ_', '').replace('_1min.csv', ''),
                **result
            })
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n{'='*70}")
    print("📊 SUMMARY ACROSS ALL MONTHS")
    print(f"{'='*70}")
    
    if all_results:
        df = pd.DataFrame(all_results)
        total_trades = df['total_trades'].sum()
        total_pnl = df['total_pnl'].sum()
        avg_win_rate = df['win_rate'].mean()
        
        print(f"Total Trades: {total_trades}")
        print(f"Total P&L: ${total_pnl:,.2f}")
        print(f"Avg Win Rate: {avg_win_rate:.1f}%")
        
        print(f"\nPer Month:")
        for _, row in df.iterrows():
            print(f"  {row['month']}: {row['total_trades']} trades, ${row['total_pnl']:,.2f} P&L")
    
    print(f"{'='*70}\n")
