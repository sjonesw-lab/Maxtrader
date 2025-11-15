"""
Wave-based Renko backtest with multi-timeframe confluence.

Implements successful backtest config:
- Wave detection (3+ bricks, retracement bands)
- Daily + 4H confluence
- Proper wave targets (TP1=1.0×, TP2=1.618×)
- ATR-based exits
- Quality filters (no artificial cooldowns)
"""

import pandas as pd
from engine.data_provider import CSVDataProvider
from engine.sessions_liquidity import label_sessions, add_session_highs_lows
from engine.renko import build_renko, get_renko_direction_series
from engine.regimes import detect_regime
from engine.strategy_wave_renko import generate_wave_signals, WaveSignal
from engine.strategy import Signal  # For backtest compatibility
from engine.backtest import Backtest
from engine.timeframes import resample_to_timeframe
from engine.ict_structures import detect_all_structures

print("="*70)
print("MaxTrader Wave System: Renko + Multi-TF Confluence + 0DTE")
print("="*70)

# Step 1: Load 1-minute data
print("\nStep 1: Loading QQQ 1-minute data...")
provider = CSVDataProvider('data/QQQ_1m_real.csv')
df_1min = provider.load_bars()
print(f"  ✓ Loaded {len(df_1min)} bars")
print(f"  ✓ Date range: {df_1min['timestamp'].min()} to {df_1min['timestamp'].max()}")

# Step 2: Resample to 4H and Daily
print("\nStep 2: Creating multi-timeframe data...")
df_4h = resample_to_timeframe(df_1min, '4h')
df_daily = resample_to_timeframe(df_1min, '1D')
print(f"  ✓ 4H bars: {len(df_4h)}")
print(f"  ✓ Daily bars: {len(df_daily)}")

# Step 3: Label sessions and add session high/low levels
print("\nStep 3: Labeling sessions and computing session levels...")
df_1min = label_sessions(df_1min)
df_1min = add_session_highs_lows(df_1min)
print(f"  ✓ Sessions labeled and high/low levels computed")

# Step 3.5: Detect ICT structures
print("\nStep 3.5: Detecting ICT structures...")
df_1min = detect_all_structures(df_1min, displacement_threshold=1.0)
print(f"  ✓ ICT structures detected (sweeps, displacement, FVG, MSS, OB)")

# Step 4: Build Renko chart (k=4.0 per tuning)
print("\nStep 4: Building Renko chart...")
k_value = 4.0  # ATR multiplier
renko_df = build_renko(df_1min, mode="atr", k=k_value, atr_period=14)
brick_size = renko_df['brick_size'].iloc[0]
print(f"  ✓ Built {len(renko_df)} Renko bricks")
print(f"  ✓ Brick size: ${brick_size:.2f} (k={k_value})")
print(f"  ✓ Compression: {len(df_1min)/len(renko_df):.1f}x")

# Step 5: Detect regime (30-min for context)
print("\nStep 5: Detecting 30-min regime...")
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

regime_counts = df_1min['regime'].value_counts()
print(f"  ✓ Regime distribution:")
for regime, count in regime_counts.items():
    pct = (count / len(df_1min)) * 100
    print(f"    - {regime}: {pct:.1f}%")

# Step 6: Generate wave-based signals with multi-TF confluence
print("\nStep 6: Generating wave signals with multi-TF confluence...")
print("  Testing: FIXED % TARGETS (v3 proven approach)")
print("  Quality filters:")
print("    - Wave: 3+ brick impulse")
print("    - Retracement: shallow/healthy only (skip deep >62%)")
print("    - Entry distance: ≤1.5 bricks from P2")
print("    - Confluence: daily+4H alignment, min 0.40 confidence")
print("    - Session: 09:45-15:45 ET")
print("  Targets:")
print("    - TP1: +1% from entry")
print("    - TP2: +2% from entry")
print("    - Stop: -0.7% from entry")
print("    - Max hold: 120 minutes")

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
    target_mode='fixed_pct'  # Test v3 proven % targets
)

print(f"\n  ✓ Generated {len(wave_signals)} wave signals")

# Convert to standard Signal format
signals = []
for ws in wave_signals:
    sig = Signal(
        index=df_1min[df_1min['timestamp'] == ws.timestamp].index[0] if (df_1min['timestamp'] == ws.timestamp).any() else 0,
        timestamp=ws.timestamp,
        direction=ws.direction,
        spot=ws.spot,
        target=ws.tp1,  # Use TP1 as primary target
        source_session=None,
        meta={
            'wave_height': ws.wave_height,
            'tp1': ws.tp1,
            'tp2': ws.tp2,
            'stop': ws.stop,  # Add stop loss
            'retrace_type': ws.retrace_type,
            'retrace_pct': ws.retrace_pct,
            'confidence': ws.meta['confidence'],
            'regime': ws.regime,
            'daily_direction': ws.meta['daily_direction'],
            'wave_bricks': ws.meta['wave_bricks']
        }
    )
    signals.append(sig)

# Signal breakdown
long_signals = [s for s in signals if s.direction == 'long']
short_signals = [s for s in signals if s.direction == 'short']
print(f"    - Long: {len(long_signals)}")
print(f"    - Short: {len(short_signals)}")

# Retracement breakdown
retrace_breakdown = {}
for ws in wave_signals:
    retrace_breakdown[ws.retrace_type] = retrace_breakdown.get(ws.retrace_type, 0) + 1

print(f"  Retracement types:")
for rtype, count in retrace_breakdown.items():
    print(f"    - {rtype}: {count}")

# Confidence stats
wave_confidences = [ws.meta.get('wave_confidence', 0) for ws in wave_signals]
ict_scores = [ws.meta.get('ict_confluence_score', 0) for ws in wave_signals]
final_confidences = [ws.meta['confidence'] for ws in wave_signals]

if final_confidences:
    print(f"  Wave confidence: {min(wave_confidences):.2f} - {max(wave_confidences):.2f} (mean: {sum(wave_confidences)/len(wave_confidences):.2f})")
    print(f"  ICT confluence: {min(ict_scores):.2f} - {max(ict_scores):.2f} (mean: {sum(ict_scores)/len(ict_scores):.2f})")
    print(f"  Final confidence: {min(final_confidences):.2f} - {max(final_confidences):.2f} (mean: {sum(final_confidences)/len(final_confidences):.2f})")

# ICT structure breakdown
if wave_signals:
    ict_counts = {
        'sweep': sum(1 for ws in wave_signals if ws.ict_confluence and ws.ict_confluence.has_sweep),
        'displacement': sum(1 for ws in wave_signals if ws.ict_confluence and ws.ict_confluence.has_displacement),
        'fvg': sum(1 for ws in wave_signals if ws.ict_confluence and ws.ict_confluence.has_fvg),
        'mss': sum(1 for ws in wave_signals if ws.ict_confluence and ws.ict_confluence.has_mss),
        'order_block': sum(1 for ws in wave_signals if ws.ict_confluence and ws.ict_confluence.has_order_block)
    }
    print(f"  ICT structure presence:")
    for structure, count in ict_counts.items():
        pct = (count / len(wave_signals)) * 100
        print(f"    - {structure}: {count} ({pct:.1f}%)")

# Step 7: Run backtest with fixed % targets (120 min hold)
print("\nStep 7: Running backtest with fixed % targets (0DTE options)...")
backtest = Backtest(df_1min, min_rr_ratio=1.2)
results = backtest.run(signals, max_bars_held=120)  # 120 min per v3 config

# Step 8: Results
print("\n" + "="*70)
print("WAVE SYSTEM PERFORMANCE")
print("="*70)
print(f"Total Trades:        {results['total_trades']}")
print(f"Win Rate:            {results['win_rate']*100:.1f}%")
print(f"Average PnL:         ${results['avg_pnl']:.2f}")
print(f"Average R-Multiple:  {results['avg_r_multiple']:.2f}R")
print(f"Total PnL:           ${results['total_pnl']:.2f}")
print(f"Max Drawdown:        ${results['max_drawdown']:.2f}")

if results['total_trades'] > 0:
    trades_per_month = results['total_trades'] / 3  # 90 days ≈ 3 months
    print(f"\nTrade Frequency:     {trades_per_month:.1f} trades/month")
    print(f"  (Let by market quality, not artificial limits)")
    
    # Calculate profit factor
    wins = [t.pnl for t in results['trades'] if t.pnl > 0]
    losses = [abs(t.pnl) for t in results['trades'] if t.pnl < 0]
    
    if losses:
        profit_factor = sum(wins) / sum(losses) if sum(losses) > 0 else float('inf')
        print(f"Profit Factor:       {profit_factor:.2f}")
    
    print("\nSample Trades:")
    print("-" * 70)
    for i, trade in enumerate(results['trades'][:10], 1):
        ws = [w for w in wave_signals if w.timestamp == trade.signal.timestamp]
        retrace = ws[0].retrace_type if ws else 'unknown'
        conf = trade.signal.meta.get('confidence', 0)
        
        print(f"Trade {i}:")
        print(f"  {trade.signal.direction.upper()}: {trade.signal.timestamp}")
        print(f"  Entry: ${trade.signal.spot:.2f} → TP1: ${trade.signal.meta['tp1']:.2f}")
        print(f"  Wave: {retrace} retrace, conf={conf:.2f}")
        print(f"  Result: ${trade.pnl:.2f} ({trade.r_multiple:.2f}R)")
    
    if len(results['trades']) > 10:
        print(f"... and {len(results['trades']) - 10} more trades")

# Equity curve
print("\n" + "="*70)
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

if results['total_trades'] > 0:
    pnls = [t.pnl for t in results['trades']]
    cumulative = [sum(pnls[:i+1]) for i in range(len(pnls))]
    
    plt.figure(figsize=(12, 6))
    plt.plot(cumulative, marker='o', linewidth=2, markersize=4)
    plt.axhline(0, color='red', linestyle='--', alpha=0.5)
    plt.title('Wave System: Equity Curve (Quality Filters, No Cooldowns)', 
              fontsize=14, fontweight='bold')
    plt.xlabel('Trade Number')
    plt.ylabel('Cumulative P&L ($)')
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig('equity_curve_wave.png', dpi=150)
    print(f"✓ Equity curve saved: equity_curve_wave.png")

print("="*70)
print("Wave backtest complete!")
print("="*70)
