# Phase 6 — Historical Validation Report

**Status:** research / data-validation phase. No strategy rules changed.
**Engine:** Phase 5 deterministic pipeline (`scenario → qualification → risk → intraday-exit`) used unchanged.
**Date:** 2026-09-20. **Dataset:** 2026-07-27 → 2026-09-18 (before AND after Phase 6 — expansion not possible, see §3).

## 1. Dataset

| | NIFTY | BANKNIFTY |
|---|---|---|
| Source | yfinance `^NSEI` | yfinance `^NSEBANK` |
| Interval / timezone | 5m / Asia/Kolkata | 5m / Asia/Kolkata |
| Period | 2026-07-27T09:15 → 2026-09-18T15:25 | same |
| Candles / sessions | 2925 / 39 | 2925 / 39 |
| Invalid OHLC / duplicates / out-of-order / bad-tz / outside-session / weekend / missing / partial | 0 in all categories | 0 in all categories |

Machine-readable: `data/generated/phase6_data_quality.json` (quality + provenance + expansion attempts).

## 2. Regime-gap reconciliation (§Phase 5 “missing ~10%”)

Every session is explicitly classified or explicitly `INSUFFICIENT_DATA`. Nothing is silently discarded.

| Regime | NIFTY sessions | NIFTY % | BANKNIFTY sessions | BANKNIFTY % |
|---|---|---|---|---|
| DOWNTREND | 14 | 35.9 | 0 | 0.0 |
| HIGH_VOLATILITY | 14 | 35.9 | 35 | 89.7 |
| RANGE | 5 | 12.8 | 0 | 0.0 |
| UPTREND | 2 | 5.1 | 0 | 0.0 |
| LOW_VOLATILITY | 0 | 0.0 (not observed) | 0 | 0.0 (not observed) |
| TRANSITION | — (not a classifier category) | — | — | — |
| INSUFFICIENT_DATA | 4 (2026-07-27…30, <5 prior sessions for MA) | 10.3 | 4 (same dates) | 10.3 |
| **Total** | **39** | **100.0** | **39** | **100.0** |

Candle percentages are identical (75 candles/session). Automated test `test_regime_gap_reconciles_to_100pct` enforces this.

## 3. Data-expansion attempt (honest result: NOT possible)

- yfinance 5m history is limited to ~60 days. A fetch for 2026-03-01…2026-07-27 returned **0 rows** for both symbols.
- No other free, keyless, reproducible source provides NSE index 5m history. None used.
- **No synthetic, interpolated, or fabricated candles created.** Dataset retained as-is.
- Required for broader validation: licensed vendor history (e.g. exchange-authorized data vendor) or broker historical API covering ≥12 months of 5m.

## 4. Methodology (unchanged from Phase 5)

Scenario detection → qualification (`MAX_TRADES_PER_DAY=1` on historical trade date) → risk (percentage-based, min R:R 1.5) → entry → intraday exit scan on subsequent same-day completed candles: LONG `LOW<=STOP→STOP`, `HIGH>=TARGET→TARGET` (mirrored for SHORT); both touched in one candle → `AMBIGUOUS_INTRABAR` resolved conservatively as STOP; EOD fallback; no time exit. Signals use data ≤ T; exits use T+1 onward. Regime uses only dates ≤ classified session (tested).

Terminology: scenario event (scenario_candidates rows: NIFTY 1920 / BANKNIFTY 1983) ≠ qualification attempt (every candle evaluated: 2925 in FULL) ≠ qualified trade (≤1/day) = completed trade (every qualified trade exits, EOD if nothing else).

## 5. Results (same engine; 90D ≡ FULL because 90D window covers the whole dataset)

### NIFTY

| Period | Sessions | Attempts | Qual/Cmpl | W | L | Win% | EOD/TGT/STP/AMB | Avg R | Med R | Tot R | AvgHold | MFE | MAE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7D (09-09…09-18) | 7 | 450 | 6/6 | 5 | 1 | 83.3 | 6/0/0/0 | 13.89 | 20.43 | 83.37 | 362.5 | 23435 | 23214 |
| 30D (08-07…09-18) | 30 | 2175 | 29/29 | 27 | 2 | 93.1 | 29/0/0/0 | 21.57 | 22.14 | 625.67 | 362.6 | 24072 | 23885 |
| 90D | 39 | 2925 | 39/39 | 37 | 2 | 94.9 | 39/0/0/0 | 24.55 | 26.72 | 957.56 | 363.3 | 24137 | 23946 |
| FULL | 39 | 2925 | 39/39 | 37 | 2 | 94.9 | 39/0/0/0 | 24.55 | 26.72 | 957.56 | 363.3 | 24137 | 23946 |

### BANKNIFTY

| Period | Sessions | Attempts | Qual/Cmpl | W | L | Win% | EOD/TGT/STP/AMB | Avg R | Med R | Tot R | AvgHold | MFE | MAE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7D | 7 | 450 | 6/6 | 4 | 2 | 66.7 | 5/1/0/0 | 22.80 | 15.69 | 136.77 | 345.0 | 56559 | 55909 |
| 30D | 30 | 2175 | 29/29 | 26 | 3 | 89.7 | 28/1/0/0 | 24.69 | 20.09 | 715.95 | 360.7 | 57434 | 56918 |
| 90D | 39 | 2925 | 39/39 | 36 | 3 | 92.3 | 38/1/0/0 | 26.90 | 21.52 | 1049.18 | 361.7 | 57450 | 56928 |
| FULL | 39 | 2925 | 39/39 | 36 | 3 | 92.3 | 38/1/0/0 | 26.90 | 21.52 | 1049.18 | 361.7 | 57450 | 56928 |

Max trades/day = 1 everywhere. Lookahead violations = 0 everywhere. Trades/session ≈ 0.86 (7D) → 0.97 (30D) → 1.0 (90D/FULL).

## 6. Regime-by-regime (FULL period)

### NIFTY

| Regime | Sess | Trades | W/L | Win% | Avg R | Tot R | Sample |
|---|---|---|---|---|---|---|---|
| DOWNTREND | 14 | 14 | 13/1 | 92.9 | 18.73 | 262.19 | limited |
| HIGH_VOLATILITY | 14 | 14 | 13/1 | 92.9 | 23.53 | 329.48 | limited |
| RANGE | 5 | 5 | 5/0 | 100 | 35.98 | 179.90 | limited |
| UPTREND | 2 | 2 | 2/0 | 100 | 29.38 | 58.76 | very limited — no conclusions |
| INSUFFICIENT_DATA | 4 | 4 | 4/0 | 100 | 31.81 | 127.23 | very limited — no conclusions |
| LOW_VOLATILITY / TRANSITION | — | — | — | not observed | — | — | — |

### BANKNIFTY

| Regime | Sess | Trades | W/L | Win% | Avg R | Tot R | Sample |
|---|---|---|---|---|---|---|---|
| HIGH_VOLATILITY | 35 | 35 | 32/3 | 91.4 | 27.13 | 949.44 | adequate |
| INSUFFICIENT_DATA | 4 | 4 | 4/0 | 100 | 24.94 | 99.74 | very limited — no conclusions |
| UPTREND / DOWNTREND / RANGE / LOW_VOLATILITY / TRANSITION | — | — | — | not observed | — | — | — |

## 7. Period stability (factual, no tuning)

- NIFTY win rate rises 83.3 → 93.1 → 94.9 as the window widens; the 7D dip is one September loss on a 6-trade sample.
- BANKNIFTY 7D (66.7%, 6 trades) vs 30D (89.7%) vs 90D (92.3%): same small-sample effect.
- Exit behavior is stable: ~100% EOD exits (38/39 BANKNIFTY, 39/39 NIFTY) — stops/targets are almost never touched intraday at current 1%/2% levels. This is a descriptive finding, not a trigger for re-tuning (Phase 6 forbids optimization).

## 8. Limitations (explicit)

- **Options validation: NOT AVAILABLE** — results are underlying/index research, not executable option trades.
- **NET P&L not modeled** — GROSS/MODEL R only; no brokerage, slippage, or costs.
- **39 sessions / single quarter (Q3 2026)** — regime samples mostly limited/very limited; BANKNIFTY has no UPTREND/DOWNTREND/RANGE observations at all.
- **No LOW_VOLATILITY or TRANSITION observed** in either instrument.
- **Expansion blocked** by free-source 5m limits (documented in §3, not worked around).
- High win rates with ~6h average holding and EOD-everything exits reflect the engine mechanics on this sample, not proof of edge.

## 9. Validation checklist

Tests 61/61 PASS (44 Phase 5 + 17 Phase 6) · API 200 on scenarios/performance/replay · ingestion N/A (no new data) · data validation PASS (all-zero issue counts) · backtest PASS · no-look-ahead PASS · one-trade/day PASS · research/live isolation PASS (`qualified_trades=paper_trades=daily_trade_locks=0` before and after).

Machine-readable outputs: `data/generated/phase6_summary.json`, `phase6_nifty.json`, `phase6_banknifty.json`, `phase6_regime_analysis.json`, `phase6_data_quality.json`.
