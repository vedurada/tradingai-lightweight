# NIFTY previous-day / CPR direction study (research only)

Index-level research on the question: *does the previous session's price
action, the Central Pivot Range (CPR), the opening gap, an opening-range
breakout/retest or an equal-weight VWAP proxy carry a tradeable directional
edge on NIFTY?*

**This folder is research output. It contains no production change.** No
production code, configuration, alert, API, schedule or database row was
modified while producing it. The only production module that is imported is
`app.market.nse_calendar` (stdlib only, no import-time side effects); the
production trigger engine is executed **once**, in an isolated subprocess with
`TRADINGAI_DB_PATH` pointing at the study snapshot, purely as a control.

## Scope boundary (deliberate)

- **Index level only.** No option premium, credit or spread economics exist in
  the data (`option_snapshots` = 0, `option_contracts` = 0, every
  `paper_spreads.credit` is NULL). Nothing here says anything about the
  profitability of an option spread written on this signal, and no rupee
  expectancy is claimed anywhere.
- **VWAP is a proxy.** The `volume` column of `market_candles_5m` is zero on
  every row, so the VWAP figure is an *equal-weight typical price* average,
  not a volume-weighted one.
- **The 2026-10-22 session is excluded** (in progress at the time of the run).

## Layout

```
spec.md                      frozen pre-registration (sha256 in the manifest)
src/
  data.py                    read-only access + snapshot + session quality
  features.py                point-in-time feature construction
  signals.py                 direction models A-F, closed reason taxonomy
  execution.py               entry / stop / target / exit simulation
  metrics.py                 expectancy, drawdown, Wilson CI, block bootstrap
  runner.py                  splits, variant grid, point-in-time checks
  run_all.py                 the study itself (writes outputs/)
  make_reports.py            renders reports/ from outputs/
tests/test_research.py       20 unit / no-look-ahead tests
outputs/                     every artefact of the run (ledgers, gates, manifest)
reports/                     the six markdown deliverables
```

## Reproduce

```bash
cd /opt/tradingai
python3 -m pytest research/prevday_cpr_spread_study/tests -q          # 20 passed
python3 -m research.prevday_cpr_spread_study.src.run_all             # ~15 s
python3 -m research.prevday_cpr_spread_study.src.make_reports
```

`run_all.py` writes only inside `research/prevday_cpr_spread_study/outputs/`.
It creates `outputs/snapshot.db` with sqlite3's backup API from a `mode=ro`
connection to `database/tradingai.db`, and every subsequent read goes to the
snapshot. The production database is never opened for writing.

Determinism: fixed seed `20261022` for the bootstrap, fixed split dates, fixed
variant grid (27 model configurations x 5 stops x 5 targets = 675 variants).

## Splits (frozen before the OOS window was touched)

| split | window | sessions |
| --- | --- | --- |
| IS | 2026-07-06 .. 2026-08-31 | 41 |
| VAL | 2026-09-01 .. 2026-09-30 | 21 |
| OOS | 2026-10-01 .. 2026-10-21 | 13 |

## Result in one paragraph

The frozen selection (Model B - the first 5-minute close beyond the previous
session's CPR boundary - with a structural stop 10 points beyond the CPR
level and a structural target) shows **+0.235 R/trade on IS+VAL (47 trades)**
and **+0.873 R/trade on OOS (12 trades, 66.7% win rate, +18.0 index points
per trade)**. The final gate is **FAIL**: the result is stop-distance
dependent (every percentage stop is negative on IS+VAL), only 2 of 6
walk-forward blocks are positive, and the best single trade carries 65.5% of
the OOS profit. See `reports/final_recommendation.md`.

## Where to look

| question | file |
| --- | --- |
| what was run, on what data, with what result | `reports/backtest_report.md` |
| which model family is worth anything | `reports/model_comparison.md` |
| why the result is fragile | `reports/stop_target_analysis.md` |
| the exact rules and the NO TRADE taxonomy | `reports/signal_decision_table.md` |
| every field of every artefact | `reports/signal_schema.md` |
| the verdict and what would have to change | `reports/final_recommendation.md` |
| per-session decisions | `outputs/signal_ledger.csv` |
| per-trade records of the frozen selection | `outputs/trade_ledger.csv` |
| every variant's metrics | `outputs/trades_all_variants.csv` |
| the gate-by-gate verdict | `outputs/gates.json` |
| hashes, seed, commit, split dates | `outputs/run_manifest.json` |
