# Ultra-Low Vol Strategy - Design Decision

## Current Status: Stuck Between Extremes

**Iteration 1:** 13,880 signals (too permissive)
**Iteration 2:** 443 signals (still too many)
**Iteration 3:** 0 signals (too strict)

## Root Cause Analysis

### The Core Problem

**Designer Environment:** VIX <13, ATR <0.5% (ultra-low vol)
**Test Environment:** VIX 18.3, ATR 0.17% (moderate vol, bear trend)

**This is NOT a strategy bug - it's environment mismatch.**

### Architect Feedback

1. ✅ **ATR now rolling** (fixed)
2. ✅ **Signal B stricter** (wick >2× body, must reclaim through band)
3. ❌ **Signal A still not firing** (logic issue)

### The Signal A Problem

**Designer Spec (literal):**
```
if price < vwap - threshold:
    wait for candle that CLOSES back above vwap - threshold
    ensure next candle does NOT make a lower low
    → long entry
```

**My Implementation:**
- Looks back 1-5 bars for old deviations
- Checks if current bar reclaims
- **Problem:** Rolling VWAP changes each bar, so "deviation at T-1" with VWAP(T-1) may not match "deviation at T" with VWAP(T)

**Better Interpretation:**
Signal A and Signal B are **the same pattern** from different perspectives:
- **Signal B (wick):** Deviation + reclaim happens WITHIN one bar
- **Signal A (multi-bar):** Deviation happens in bar N, reclaim in bar N+1

Both are "deviation → failure → reclaim" - just different timeframes.

## Recommended Path Forward

### Option A: Simplify to One Pattern (RECOMMENDED)

**Merge Signal A + B into single "deviation-failure-reclaim" logic:**

1. **Single-bar version** (current Signal B):
   - Low wicks below band, close above band = long
   - High wicks above band, close below band = short

2. **Multi-bar version** (current Signal A):
   - Bar N closes below band
   - Bar N+1 closes above band
   - Bar N+1 doesn't make new low

**Result:** Simpler, more robust, easier to tune

### Option B: Accept Environment Mismatch

**Acknowledge test data is wrong:**
- Dec 2024 is moderate vol, not ultra-low vol
- Strategy generates appropriate signals FOR MODERATE VOL (443)
- Find true VIX <13 data to validate properly

**Pros:** Strategy may be working correctly
**Cons:** Can't validate without proper data

### Option C: Treat Ultra-Low Vol as No-Trade

**Per designer:**
> "If strategy cannot produce sane behavior, treat ultra-low vol as no-trade regime"

- Router detects VIX <13
- Skips all trading
- Focus on Normal Vol + High Vol only

**Pros:** Conservative, prevents bad trades
**Cons:** Gives up on ultra-low vol opportunities

### Option D: Proceed to High Vol Validation

**Parallel work path:**
- High Vol strategy ready (30 signals on COVID 2020)
- Can backtest while debugging Ultra-Low Vol
- Don't block overall progress

## Decision Required

**I recommend:** Option A (simplify) + Option D (proceed in parallel)

1. Simplify Ultra-Low Vol to single deviation-reclaim pattern
2. Set realistic signal count for moderate vol environment
3. Move forward with High Vol backtest
4. Come back to Ultra-Low Vol with proper VIX <13 data later

**Why:** Unblocks progress, validates core architecture, allows iteration

## Next Steps

1. User decision on approach
2. If simplify: Merge Signal A+B logic
3. Run High Vol backtest (ready to go)
4. Document lessons learned
