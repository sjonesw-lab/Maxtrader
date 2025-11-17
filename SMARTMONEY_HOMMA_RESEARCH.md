# Smart Money + Homma MTF Strategy - Research Report

**Date:** November 17, 2025  
**Status:** RESEARCH PHASE - Not production-ready

---

## Executive Summary

Tested multi-timeframe Smart Money zone detection + Homma candlestick confirmation strategy across 8 HTF/LTF combinations on QQQ in both normal and high volatility environments.

**Key Finding:** 1H HTF / 5min LTF shows promise with 75% WR and 3.32R average in high volatility, but trade frequency is too low for production deployment (2-4 trades per 90 days).

---

## Strategy Overview

**Concept:**
- HTF (30m/1h/2h/4h): Detect Smart Money supply/demand zones (DBR, RBD, RBR, DBD patterns)
- LTF (3m/5m): Confirm entries with Homma candlestick patterns (hammer, engulfing, harami, doji)
- Entry: Zone revisit + LTF pattern + false break reclaim

**Validation Pillars:**
1. Clear pattern structure (minimum 0.3% impulse moves)
2. Freshness (zone not revisited before entry)
3. Reward:Risk ≥ 2:1

---

## Backtest Results

### Dataset 1: QQQ Aug-Nov 2025 (Normal Volatility)

| HTF/LTF | Trades | WR | Avg R | PF | Sharpe | P&L |
|---------|--------|-----|-------|-----|--------|-----|
| **1H/5min** | 2 | 50% | 2.22 | 5.44 | 0.49 | $13.37 |
| 2H/5min | 3 | 66.7% | 1.06 | 4.18 | 0.44 | $15.11 |
| 4H/5min | 2 | 100% | 4.23 | 0.00 | 0.83 | $6.31 |
| 4H/3min | 2 | 100% | 1.36 | 0.00 | 0.80 | $3.67 |

**Observations:**
- 4H combos had 100% WR but only 2 trades (not statistically significant)
- 1H/5min and 2H/5min showed consistency with 2-3 trades
- Low trade frequency across all combos

### Dataset 2: QQQ Mar-May 2020 (COVID Crash - High Volatility)

| HTF/LTF | Trades | WR | Avg R | PF | Sharpe | P&L |
|---------|--------|-----|-------|-----|--------|-----|
| **1H/5min** | 4 | 75% | 3.32 | 14.28 | 0.94 | $18.40 |
| 2H/5min | 2 | 50% | 2.35 | 7.36 | 0.54 | $6.47 |
| 2H/3min | 2 | 100% | 1.69 | 0.00 | 86.30* | $5.02 |
| 30min/3min | 3 | 33% | 2.39 | 4.58 | 0.41 | $9.46 |

*Likely calculation artifact due to very low standard deviation

**Observations:**
- 1H/5min improved to 75% WR with higher R-multiples
- More zones detected in high volatility (7-9 vs 3-4)
- Better Sharpe ratios overall
- Strategy performs better in volatile environments

---

## Best Performer: 1H HTF + 5min LTF

**Combined Statistics:**
- Normal Vol: 50% WR, 2.22R, Sharpe 0.49 (2 trades)
- High Vol: 75% WR, 3.32R, Sharpe 0.94 (4 trades)
- **Works across both regimes**

**Why it works:**
- 1H zones capture meaningful market structure
- 5min LTF provides precise entry timing
- False break reclaim filters out weak setups
- Homma patterns add confirmation

**Limitations:**
- Only 2-4 trades per 90-day period
- Need 12+ months of data for statistical significance
- Sample size too small for production

---

## Comparison to Existing Strategies

### vs Normal Vol Wave-Renko
| Metric | Wave-Renko | Smart Money 1H/5min |
|--------|------------|---------------------|
| Win Rate | 43.5% | 50-75% |
| Avg R | ~2.4 | 2.22-3.32 |
| Profit Factor | 9.39 | 5.44-14.28 |
| Trades/90d | 23 | **2-4** ❌ |
| Sharpe | ~2-3 | 0.49-0.94 |

**Verdict:** Smart Money has higher win rate and R-multiples but **critically low trade frequency**.

### vs High Vol Sweep-Reclaim (0.2% targets)
| Metric | Sweep-Reclaim | Smart Money 1H/5min |
|--------|---------------|---------------------|
| Win Rate | 69.8% | 75% |
| Avg R | -0.70 | **3.32** ✅ |
| Sharpe | -3.50 | **0.94** ✅ |
| Trades/90d | 281 | 4 |

**Verdict:** Smart Money has positive expectancy unlike sweep-reclaim, but extremely low frequency.

---

## Critical Issues

### 1. Sample Size
- 2-4 trades per 90 days = **8-16 trades/year**
- Need minimum 30-50 trades for statistical confidence
- Would require 2-3 years of data to validate
- Not enough for walk-forward optimization

### 2. Trade Frequency
- MaxTrader needs consistent signals for capital deployment
- Current frequency too low for meaningful income generation
- Long idle periods between trades

### 3. Zone Detection Sensitivity
Current parameters detect only 3-9 zones per 90 days per timeframe:
- Too strict: Miss opportunities
- Too loose: False signals increase

Tuning needed but risks overfitting on small sample.

---

## Potential Improvements

### Short-Term (Could test)
1. **Relax zone parameters:**
   - min_impulse_pct: 0.003 → 0.002 (0.2% vs 0.3%)
   - min_reward_risk: 2.0 → 1.5
   - Test if zone detection increases to 10-15/90d

2. **Add more patterns:**
   - Test intraday session highs/lows as zones
   - Volume profile nodes
   - Previous day high/low

3. **Remove Homma requirement:**
   - Test zone touch + false break reclaim alone
   - May increase frequency but reduce WR

### Long-Term (Phase 2)
1. **Multi-instrument diversification:**
   - Run on SPY, IWM, tech stocks simultaneously
   - Could generate 20-30 trades/month across portfolio

2. **Combine with other strategies:**
   - Use as confirmation filter for Wave-Renko entries
   - Hybrid approach: Wave-Renko + Smart Money zones

3. **Longer historical validation:**
   - Test on 2-3 years of data
   - Walk-forward optimization
   - Regime-specific parameter tuning

---

## Recommendations

### Option A: Continue Research (1-2 days)
- Relax parameters to increase trade frequency
- Test on additional data (2023-2024)
- Validate if we can get to 10-15 trades/month
- **Risk:** May not solve frequency problem

### Option B: Hybrid Integration
- Use Smart Money zones as **confluence filter** for existing Wave-Renko strategy
- Don't trade Smart Money standalone
- May improve Wave-Renko win rate from 43.5% to 50-55%
- **Benefit:** Leverages both edges

### Option C: Defer to Phase 2 (Recommended)
- Strategy shows promise but needs more work
- Current priorities: Runtime safety layer for 3 working strategies
- Revisit Smart Money + Homma in Phase 2 with:
  - Longer historical data
  - Multi-instrument testing
  - Hybrid approach evaluation

---

## Final Verdict

**Status:** PROMISING but NOT PRODUCTION-READY

**Strengths:**
- ✅ Positive expectancy across regimes
- ✅ High win rates (50-75%)
- ✅ Good R-multiples (2.22-3.32)
- ✅ Works in both normal and high volatility

**Weaknesses:**
- ❌ Extremely low trade frequency (2-4/90 days)
- ❌ Small sample size (not statistically significant)
- ❌ Long idle periods

**Recommendation:** Defer standalone implementation to Phase 2. Consider as confluence filter for existing strategies in future iteration.

---

## Code Artifacts

**Implemented Modules:**
- `strategies/smartmoney_zones.py` - Zone detection (DBR, RBD, RBR, DBD)
- `strategies/homma_patterns.py` - Candlestick patterns
- `strategies/smartmoney_homma_mtf.py` - Multi-timeframe strategy
- `backtest_smartmoney_homma.py` - Backtest runner

**Testing:**
- ✅ 8 HTF/LTF combinations
- ✅ 2 volatility regimes
- ✅ 180 days historical data
- ✅ Risk-adjusted metrics (Sharpe, PF, R-multiples)
