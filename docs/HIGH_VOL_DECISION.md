# High Vol Strategy - Decision Document

## Status: DEFERRED TO PHASE 2

**Date:** November 16, 2025  
**Decision:** Skip High Vol strategy for initial release, revisit in Phase 2

---

## What We Tested

### 1. Sweep-Reclaim Mean-Reversion (Original Approach)
**Logic:** Trade liquidity sweeps at key levels, expecting mean-reversion  
**Results:**
- Best config: 0.75% target, 0.25% stop
- Win Rate: 14.7%
- Avg R: -0.41R
- Profit Factor: 0.52
- **VERDICT:** ❌ FAILED - Negative expectancy

### 2. Crash-Trend Following (Redesign Attempt)
**Logic:** Short pullbacks in confirmed downtrends, ride the crash  
**Results:**
- Simple SMA-based shorts
- Win Rate: 20.3%
- Avg R: -0.39R
- Profit Factor: 0.51
- **VERDICT:** ❌ FAILED - Negative expectancy

---

## Why Both Approaches Failed

**Root Cause:** COVID crash (March 2020, VIX 38-93) had **violent intraday whipsaws**

### The Data:
- March 2020: ±2-3% hourly price swings
- 0DTE options with 2-hour max hold = constant stop-outs
- Mean-reversion: Every bounce got sold → stopped out
- Trend-following: Every dip got bought → stopped out
- **Net result:** Whipsaw hell for both strategies

### Mathematical Impossibility:
To achieve 85% WR in this environment, you'd need:
- Target: 0.14% (15th percentile 2H move)
- With 0.3% stop → **R:R = 0.5:1** (guaranteed loss)

---

## Strategic Recommendation

### Option 1: SKIP FOR NOW ✅ (CHOSEN)
**Rationale:**
- Normal Vol (Wave-Renko) works: 43.5% WR, 9.39 PF, $2,249 PnL
- Ultra-Low Vol V2 works: Complete with EXTREME_CALM_PAUSE
- Regime Router works: 4 regimes, proper switching
- **Focus on what works**, implement runtime safety, launch Phase 1

**Phase 2 Redesign Ideas:**
1. **Longer holds:** 4H-daily options instead of 0DTE
2. **Different timeframe:** 15min-1H bars instead of 1min
3. **Directional bias:** Weekly trend filter, only trade WITH crash
4. **Position sizing:** Much smaller size in high vol (0.25% risk vs 0.75%)

### Option 2: Redesign Now (NOT CHOSEN)
Would require:
- Complete strategy rebuild (2-3 days)
- Different data requirements (daily options chain)
- No guarantee it works
- Delays Phase 1 launch

---

## System Status

### ✅ Working Strategies:
1. **Normal Vol (VIX 13-30):** Wave-Renko with ICT confluence
   - 43.5% WR, 9.39 PF, $2,249 PnL over 90 days
   - 23 trades/month

2. **Ultra-Low Vol (VIX 8-13):** PA-confirmed VWAP mean-reversion
   - Session-anchored VWAP, band cross-reclaim triggers
   - Structurally complete, needs live tuning

3. **EXTREME_CALM_PAUSE (VIX <8):** No trading, capital preservation
   - Tested on 2017 data (VIX ~6) → correctly pauses

### ⏭️ Deferred:
4. **High Vol (VIX >30):** Needs redesign for longer timeframes
   - Current sweep-reclaim: -0.41R (loses money)
   - Crash-trend attempt: -0.39R (loses money)
   - Phase 2: Explore daily options with 4H-1D holds

---

## Architecture Impact

### RegimeRouter Behavior:
```python
if vix > 30:
    return 'HIGH_VOL'  # Router exists, strategy returns []
elif vix < 8 or atr_pct < 0.05:
    return 'EXTREME_CALM_PAUSE'  # No strategy, zero signals ✅
elif vix < 13 or atr_pct < 0.5:
    return 'ULTRA_LOW_VOL'  # Working ✅
else:
    return 'NORMAL_VOL'  # Working ✅
```

**Current HIGH_VOL handling:**
- Regime detected correctly
- Strategy exists but generates zero signals
- System degrades gracefully (no trades in high vol)
- **Production-ready:** Won't break, just won't trade in VIX >30

---

## Next Steps

### Immediate (Phase 1):
1. ✅ Document High Vol decision
2. ⏭️ Implement runtime safety layer:
   - RiskManager (position sizing, max positions)
   - VIX/ATR circuit breakers
   - Scaling exits
   - Production config
3. ⏭️ Multi-regime backtest validation
4. ⏭️ Paper trading deployment

### Phase 2 (Future):
1. Research high-vol edge on longer timeframes
2. Collect 4H/daily options data
3. Test directional crash playbook
4. Validate before production

---

## Lessons Learned

1. **Market type matters:** Strategies must match regime characteristics
2. **Timeframe matters:** 0DTE works in normal vol, fails in extreme vol
3. **Test early:** Better to discover failure in backtesting than production
4. **Focus matters:** Ship working strategies, iterate on broken ones later
5. **Graceful degradation:** System should handle unsupported regimes safely

---

## Final Verdict

**High Vol strategy deferred to Phase 2.**  

System will:
- Detect HIGH_VOL regime correctly ✅
- Generate zero signals (no trades) ✅
- Preserve capital ✅
- Log regime for monitoring ✅

**No production risk. Safe to proceed.**
