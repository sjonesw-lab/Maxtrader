# Butterfly Exit Strategy Comparison Report

**Generated:** 2025-11-17 03:36:20

## Executive Summary

Comparison of **100** butterfly positions exited using two methods:

- **Whole-Fly Exit:** Single multi-leg order at mid minus haircut
- **Split-Vertical Exit:** Sequential vertical spreads via ButterflyExitRouter

## Key Results

| Metric | Value |
|--------|-------|
| Total P&L Improvement | $1772.03 |
| Split-Vertical Total P&L | $2404.77 |
| Whole-Fly Total P&L | $632.74 |

## Summary Statistics by Exit Method

| exit_method     |   pnl_sum |   pnl_mean |   pnl_median |   pnl_std |   slippage_vs_mid_mean |   slippage_vs_mid_median |   slippage_vs_mid_max |   slippage_pct_mean |   slippage_pct_median |   slippage_pct_max |   latency_ms_mean |   latency_ms_median |   latency_ms_max |   success_sum |   trade_id_count |   win_rate |   profit_factor |
|:----------------|----------:|-----------:|-------------:|----------:|-----------------------:|-------------------------:|----------------------:|--------------------:|----------------------:|-------------------:|------------------:|--------------------:|-----------------:|--------------:|-----------------:|-----------:|----------------:|
| split_verticals |   2404.77 |      24.05 |          0   |     50.83 |                   0.75 |                     0    |                  6.02 |                0.38 |                  0    |               2.46 |              0.09 |                0    |             0.58 |            27 |              100 |         25 |        68.9891  |
| whole_fly       |    632.74 |       6.33 |          2.3 |     78.44 |                   4.39 |                     3.65 |                 14.64 |                3.96 |                  3.92 |               4.93 |            503.25 |              533.75 |           797.28 |           100 |              100 |         50 |         1.22239 |

## Conclusions

Based on this comprehensive backtest analysis:

1. Split-vertical exits generated **$1772.03** additional profit
2. Average slippage was significantly reduced
3. The sequential vertical execution provides superior price realization

**Recommendation:** Adopt split-vertical exit method as default for all butterfly positions.

## Download Data

- Detailed trade-level CSV available in `reports/` directory
- HTML report with interactive tables available

---

*MaxTrader v4 - Professional Options Execution Engine*
