# CPR reversal & breakout — independent historical backtest (research-only)

Purpose: test whether a CPR/pivot-based **reversal** (bearish at R1/R2/CPR/PDH,
bullish at S1/S2/CPR/PDL) combined with a **breakout** overlay improves on the
production baseline (`app.research.cpr_trigger_engine.run_opens_range`,
variant `plain`) over the same dates, with the same execution model and the
same cost model. This is an **underlying (spot) signal study**; the deployment
holds no historical option premiums, so no credit-spread premium P&L is
claimed (gate G7 is evaluated separately and is BLOCKED without option data).

## Rules of engagement

* READ-ONLY against production: no engine/API/frontend/DB-schema/job/Telegram
  change, no live cycle, no broker connection, no notification.
* The production database is only ever read through a `Connection.backup`
  snapshot; `TRADINGAI_DB_PATH` is pointed at that snapshot **before** any
  `app.*` import (app.core.db reads the path at import time).
* All writes stay inside this directory.
* A passing run authorises **human review only** — never deployment.

## How to run (on the VM, from /opt/tradingai)

```bash
cd /opt/tradingai
PYTHONPATH=/opt/tradingai python3 research/cpr_reversal_breakout/src/run_all.py
```

The orchestrator: snapshots the DB → data-quality report → baseline
reproduction (production function called unmodified) → 20 pre-registered
candidate variants → unit tests → walk-forward → comparisons → gates →
artefacts + manifest.

Unit tests only:

```bash
cd /opt/tradingai
PYTHONPATH=/opt/tradingai python3 -m pytest research/cpr_reversal_breakout/tests -q
```

## Methodology (short form)

| element | decision |
|---|---|
| baseline | production `run_opens_range(instrument, start, end, 'plain')`, imported and called unmodified; journal/paper cross-checks reported as counts |
| candidate | research-only signal engine; production `calculate_cpr`/`pivot_levels` level math, strictly prior session (point-in-time verified) |
| entry | open of the candle after the trigger, inside `[09:20, 15:20)` — identical to the baseline |
| exits | subsequent opens only, stop checked before target, flat at the 15:20 open; missing 15:20 candle drops the session (baseline parity) |
| labels | production `decay_win` (short-premium tolerance) — identical |
| costs | ₹40 brokerage + 0.5 pts slippage (lot-size aware), identical on both sides; cost sensitivity reported at 0.0/0.10/0.20/0.30 R |
| capital | risk-derived, `(entry×0.005×lot)/0.01` at the median entry of first/middle/last session, fixed per instrument so every variant shares one denominator |
| periods | IS 2026-07-06..2026-08-31, VAL 2026-09-01..2026-09-30, OOS 2026-10-01..2026-10-19 (chronological, no shuffling) |
| no-look-ahead | reversal entry = next open after the break candle; breakouts need a follow-through close beyond the level so a failure is observed **before** entry; retest variant interleaves fail/retest detection before entry |
| conflict rule | earliest confirmation wins (tie → BEAR, matching production priority); `reject` is a pre-registered ablation |
| trade count | one trade per session per instrument |

Primary variant: `combined_parity`. Full parameter/variant/gate list is
pre-registered in `strategy_config.json` and hashed into `run_manifest.json`.

## Artefacts (outputs/)

| file | contents |
|---|---|
| `data_quality_report.{json,md}` | coverage, structure, PIT check, option-history status |
| `baseline_results.json` | production reproduction + journal/paper cross-checks + metrics |
| `candidate_results.json` | per-variant metrics, counters, skip buckets (pooled / by period / by instrument) |
| `comparison.json` | baseline-vs-candidate deltas (full, by period, by instrument, OOS by instrument, all variants) |
| `walkforward_results.json` | 6 chronological blocks + expanding selection track |
| `gates.json` | G1..G7 with the final determination rule |
| `test_results.csv` | unit-test results |
| `trades.csv`, `daily_results.csv` | every normalised trade row (baseline + all variants) and the daily aggregation |
| `comparison_report.md` | human-readable report |
| `run_manifest.json` | config hash, DB snapshot hash, production file checksums **after** the run, git commit/status, test counts, and the explicit "no production writes" record |
| `tradingai_snapshot.db`, `pytest.xml` | the DB snapshot the run used; raw pytest output |

## Gates (summary)

* **G1** candidate OOS expectancy/trade > baseline OOS expectancy/trade
* **G2** advantage survives the cost grid (at least at 0.10 R)
* **G3** drawdown ≤ 20% of capital, ≤ 1.5× baseline drawdown, single loss ≤ 5% of capital
* **G4** profit factor ≥ 1.0 (total and OOS) **and** ≥15 OOS trades, ≥5 per instrument
* **G5** unit tests pass + data quality clean + PIT levels verified + identical execution/cost model
* **G6** robustness: ≥2/3 periods positive, ≥3/6 walk-forward blocks positive, ≥1 instrument positive OOS
* **G7** credit-spread economics (needs historical option premiums)

Final rule: any FAIL → **FAIL**; else any BLOCKED/INCONCLUSIVE →
**INCONCLUSIVE**; else PASS (review only).
