# Phase 8 — Point-in-Time Replay & Live Decision Parity Audit

## Executive Summary

Phase 8 tested whether TradingAI's historical decisions could actually have been
made at their historical timestamps using only information available at those
timestamps. Result: **PASS with one genuine timing correction**.

* A global-latest scenario lookup (`get_active_scenario`, `ORDER BY created_at
  DESC LIMIT 1` with no timestamp bound) was reachable from the historical
  qualification path. It **did** affect decisions: on days before a scenario
  candidate existed (e.g. NIFTY 2026-07-27, BANKNIFTY 2026-07-27/28), the old
  path qualified trades using scenarios created on *later* days, and on
  2026-09-10 it qualified at 09:15 where the point-in-time path qualifies at
  15:25.
* Fixed by `ScenarioEngine.get_scenario_for_timestamp(instrument, timestamp)`
  (`created_at <= timestamp`, deterministic tiebreak `candidate_id ASC`, plus
  the candidate's latest match with `timestamp <= timestamp`) and a new
  `QualificationEngine.qualify(..., as_of=...)` parameter. Batch backtest,
  sequential replay and simulated live all pass `as_of` = candle timestamp.
* Batch backtest vs sequential replay: **IDENTICAL** trades on FULL for both
  instruments. Simulated live vs sequential replay: **IDENTICAL** decisions.
* Future-data mutations (candles, candidate insertion, metadata, later
  signals): all **PASS** — decisions/levels unchanged, only exits may move.
* One-trade-per-day: first qualifying signal wins on every traded day.
* Research/live isolation: `qualified_trades`, `paper_trades`,
  `daily_trade_locks` remain `(0, 0, 0)` after all research runs.
* Strategy rules unchanged (entry ×0.995, stop ×0.99, target ×1.02, RR 2.0,
  MAX 1 trade/day, LONG/SHORT + conservative AMBIGUOUS_INTRABAR + EOD exits).

> Can TradingAI now prove that a historical decision at timestamp T uses only
> information available at timestamp T? **YES** — every replay trace satisfies
> `scenario_timestamp <= T`, `scenario_count` is non-decreasing within a day,
> and mutation tests prove future rows cannot move the decision.
>
> Do batch backtest, sequential replay, and simulated live decision paths
> produce the same decisions and trades? **YES** — exact match, see
> `data/generated/phase8_replay_comparison.json` and
> `data/generated/phase8_point_in_time_summary.json`.

## Phase 7 Baseline (preserved, official)

From `data/generated/phase7_trade_audit.json` (NOT overwritten):

| Instrument | Trades | W/L | Win% | avg R | med R | total R | min R | max R | Exits |
|---|---|---|---|---|---|---|---|---|---|
| NIFTY | 39 | 37/2 | 94.9% | 0.48 | 0.56 | 18.70 | -1.13 | 1.50 | 38 EOD, 1 STOP |
| BANKNIFTY | 39 | 36/3 | 92.3% | 0.53 | 0.45 | 20.77 | -1.03 | 2.00 | 37 EOD, 1 TARGET, 1 STOP |

Risk denominators: NIFTY 231–245 pts, BANKNIFTY 555–576 pts. Holding ≈ 370 min avg/flat.

## Global-Latest Audit

Time-sensitive lookups found by repository-wide search:

| Location (pre-fix) | Pattern | Verdict |
|---|---|---|
| `app/scenarios/engine.py::get_active_scenario` | `ORDER BY created_at DESC LIMIT 1`, no timestamp bound | **BUG** — reachable from historical path |
| `app/core/qualification.py::qualify` | called `get_active_scenario(instrument)` unconditionally | **BUG** — same root cause |
| `app/research/backtest.py::_simulate_decision` | no `as_of` passed | **BUG** — same root cause |
| `app/api/app.py::research_replay` | `created_at LIKE '{date}%' ORDER BY created_at DESC` | **BUG (display)** — returned later-same-day scenarios for an early timestamp |
| `app/core/qualification.py` live branch (`as_of=None`) | `datetime.now(_IST)` for `trade_date` default + trade timestamps | OK — live path legitimately uses now; historical callers must pass explicit `trade_date` + `as_of` |
| `app/research/backtest.py::run` | `datetime.now(_IST)` for `runs_at` | OK — run metadata, not decision state |
| `IntradayExitEngine.find_exit` | reads only `candles_after_entry` (post-entry, same day) | OK — future use is legitimate after entry |

Whether it actually affected decisions: **YES**.
* NIFTY 2026-07-27 and BANKNIFTY 2026-07-27/28 have no scenario candidate with
  `created_at <=` any candle of the day (first candidates: NIFTY 07-28T09:15,
  BANKNIFTY 07-29T09:40), yet the old path qualified trades there using
  later-created scenarios — pure look-ahead.
* NIFTY 2026-09-10: old path first-qualified at 09:15, PIT path at 15:25
  (caught by `test_selection_is_first_qualifying_signal` after PIT alignment).

Fix (no strategy change):
* `get_scenario_for_timestamp(instrument, timestamp)`: `WHERE instrument_id=?
  AND created_at <= ? ORDER BY created_at DESC, candidate_id ASC LIMIT 1`,
  then the candidate's latest match `WHERE timestamp <= ?`. Returns None when
  nothing was knowable yet.
* `qualify(..., as_of=None)`: `as_of` set → scoped lookup; None → live
  `get_active_scenario` (kept for live/API as-of-now use).
* Backtest, sequential replay (`app/research/replay.py`), simulated live
  (`app/research/live_sim.py`) all pass `as_of` = candle timestamp and
  `trade_date` = candle date (never wall-clock).
* Replay API endpoint now filters `created_at <= requested timestamp`.

## Sequential Replay Architecture

`app/research/replay.py::SequentialReplay.run(instrument, start, end)`:

```text
candles (ORDER BY timestamp)
  → group by trade_date
    → per candle T in order:
        available = candles with timestamp <= T        (query-bounded)
        scen      = get_scenario_for_timestamp(inst, T) (PIT lookup)
        decision  = qualify(..., trade_date=day, as_of=T)
        lock check before/after (in-memory research set)
        if QUALIFIED_TRADE → build levels from signal candle only,
                             exit from post-entry same-day candles only
        emit trace (see below)
```

Information available at T: candle T and earlier (same query window),
scenario candidates with `created_at <= T`, match rows with `timestamp <= T`,
the day's research lock state. Nothing else.

## Decision Trace

Per-candle trace fields: `instrument, trade_date, timestamp, candle_index,
price, regime, scenario_count, selected_scenario, selected_candidate_id,
scenario_timestamp, scenario_match, qualification_status,
qualification_reason, daily_lock_before/after, trade_selected, trade_id,
entry_time/entry_price/stop_price/target_price, decision_source`
(`sequential_replay`). `scenario_count` (candidates knowable at T, via
precomputed bisect — no per-candle future reads) is non-decreasing within a
day. Compact per-day rollup: `data/generated/phase8_decision_trace_summary.json`.

## Future Mutation Tests (A–D)

| Mutation | Expectation | Result |
|---|---|---|
| A: scale all candles after signal T (+5% OHLC) | signal/levels/scenario unchanged; only exit may move | PASS |
| B: insert future candidate+match after T | decision at T unchanged | PASS |
| C: change future candidate metadata (confidence/status) | decision at T unchanged | PASS |
| D: later qualifying signals same day | first signal stands; ≤1 trade/day | PASS |

Script: `scripts/phase8_mutations.py` →
`data/generated/phase8_future_mutation_results.json`; unit versions in
`tests/test_phase8.py` (all mutations reverted in `finally`; residue verified 0).

## Batch vs Sequential

`scripts/phase8_compare.py` → `data/generated/phase8_replay_comparison.json`:
per-trade MATCH/MISMATCH rows over
(trade_date, scenario, direction, entry_time/price, stop/target, exit_time/price,
exit_reason, R, PnL, MFE, MAE, holding). FULL both instruments: **IDENTICAL**,
zero mismatches. Windows 30D/7D likewise (see summary JSON).

## Sequential vs Simulated Live

`app/research/live_sim.py::SimulatedLive` feeds candles one at a time through
the same `qualify` gate (same market-state builder, same lock keying,
`research=True`, `as_of`=candle ts). `test_simulated_live_parity`: every
( timestamp, decision ) pair over 2026-09-15..16 equals the replay trace —
**IDENTICAL**. No broker, no live writes.

## One-Trade-Day Verification

`MAX_TRADES_PER_DAY = 1` (`MAX_QUALIFIED_TRADES_PER_DAY` conceptually):
`test_first_signal_wins` (09-16: single QUALIFIED_TRADE at 14:15, everything
after carries `DAILY_TRADE_LIMIT_REACHED`) and
`test_later_signal_cannot_replace_first` (FULL sweep, both instruments: ≤1
trade/day, `entry_time` == first qualified trace). Locks keyed
`(instrument, trade_date)`; replay/live never touch `daily_trade_locks`.

## Research/Live Isolation

Before/after every research run (replay, batch, simulated live, mutations):
`(qualified_trades, paper_trades, daily_trade_locks) == (0, 0, 0)`.
`test_research_isolation_replay` asserts this; `phase8_summary.py` re-verifies.

## Phase 7 vs Phase 8

Phase 7 artifacts untouched. The old-path replica in `scripts/phase8_summary.py`
reproduces the Phase 7 official FULL numbers exactly (NIFTY 39/37/2/18.70 R,
BANKNIFTY 39/36/3/20.77 R), confirming the Phase 7 baseline was produced by the
global-latest path. Genuine timing correction (`before_after` in
`data/generated/phase8_point_in_time_summary.json`):

| Instrument | Path | Trades | W/L/BE | Win% | avg R | med R | total R | min/max R | Exits |
|---|---|---|---|---|---|---|---|---|---|
| NIFTY | Phase 7 (global-latest) | 39 | 37/2/0 | 94.9% | 0.48 | 0.56 | 18.70 | -1.13/1.50 | 38 EOD, 1 STOP |
| NIFTY | Phase 8 (point-in-time) | 34 | 31/2/1 | 91.2% | 0.48 | 0.56 | 16.21 | -1.13/1.50 | 33 EOD, 1 STOP |
| BANKNIFTY | Phase 7 (global-latest) | 39 | 36/3/0 | 92.3% | 0.53 | 0.45 | 20.77 | -1.03/2.00 | 37 EOD, 1 TARGET, 1 STOP |
| BANKNIFTY | Phase 8 (point-in-time) | 31 | 28/2/1 | 90.3% | 0.54 | 0.45 | 16.63 | -1.03/2.00 | 29 EOD, 1 TARGET, 1 STOP |

Removed as look-ahead (old entry 09:15 using scenarios created later that day
or on later days): NIFTY 07-27, 08-19, 09-07, 09-08, 09-09; BANKNIFTY 07-27,
07-28, 08-11, 08-19, 08-28, 09-07, 09-08, 09-09. Re-timed to the first
point-in-time qualifying signal the same day: NIFTY 08-28 09:15→15:15, 09-10
09:15→15:25, 09-16 09:15→14:15; BANKNIFTY 07-29 09:15→09:40, 08-12 09:15→09:20,
08-31 09:15→09:20, 09-10 09:15→15:25, 09-16 09:15→10:50. Medians, min/max R and
all economics formulas are unchanged — trade *selection* changed, trade *math*
did not. 30D/7D windows show the same pattern with batch/replay IDENTICAL in
every window (see summary JSON).

## Remaining Limitations

* Options data unavailable; options validity assumed in research.
* Net transaction costs not modeled.
* Live fill achievability not validated.
* Historical sample limited to 39 sessions of yfinance 5m data
  (2026-07-27 → 2026-09-18); 90D window not available, not fabricated.
* Non-Q3 regimes remain insufficiently validated.
* Scenario definitions unchanged and still coarse (all matches CONFIRMED in
  this sample).
* No claim of live profitability or future win probability.

## Test Suite

`tests/test_phase8.py`: 23 test functions covering all 23 spec items (see
module docstring map) + `tests/test_phase7.py::test_selection_is_first_qualifying_signal`
PIT-aligned (its independent loop now passes `as_of`, matching the engine
contract — strictly stronger, not weaker). Full suite: **98/98 passing**
(74 pre-existing + 24 Phase 8).
