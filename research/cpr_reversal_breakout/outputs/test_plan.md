# Test plan — CPR reversal/breakout research

Test runner: pytest, invoked by `src/run_all.py::_run_tests` (also runnable
standalone). Isolation: `tests/conftest.py` points `TRADINGAI_DB_PATH` at a
temp SQLite backup of the production database (or reuses the snapshot the
orchestrator already set), and puts `src/` + `/opt/tradingai` on `sys.path`.
Nothing in the suite writes to any database.

## 1. Level math & data (parity / point-in-time)

| test | asserts |
|---|---|
| `test_level_math_matches_production` | research `day_levels` == production `day_levels` on normal, degenerate (H=L=C) and fractional inputs |
| `test_cpr_tc_bc_ordering_and_values` | PP/BC/TC/R1/S1/R2/S2/PDH/PDL are exactly the production formulas; TC ≥ BC after the swap |
| `test_day_levels_none_safe` | None / inverted / zero inputs return None |
| `test_prev_session_ohlc_strictly_prior_and_matches_production` | research loader == production loader, and the returned session is strictly prior for every August session of both instruments |

## 2. Reversal confirmation

| test | asserts |
|---|---|
| `test_bear_rejection_requires_all_conditions` | level tested + close back below + bearish body + min upper shadow; each failed condition produces the right rejection reason (close-through = break, not rejection; wick-only pierce = break; bullish body; untested; small shadow) |
| `test_bull_support_hold_and_breakdown_distinguished` | mirror conditions for support holds; a close through support is a breakdown, never a hold |
| `test_reversal_trigger_breaks_confirmation_extreme` | BEAR triggers on the first break of the rejection candle's low; no trigger while price holds; `trigger_require_close=True` suppresses a wick-only break and accepts a closing break |
| `test_bull_trigger_breaks_confirmation_high` | mirror for BULL (break of confirmation high) |

## 3. Breakout confirmation

| test | asserts |
|---|---|
| `test_fresh_cross_never_fires_on_wick_only` | close-cross only; wick-only pierce never counts; already-beyond is not "fresh" |
| `test_failed_breakout_is_rejected_before_entry` | cross then close back through the level ⇒ no trade, `rejected_failed_break` counted |
| `test_breakout_followthrough_entry_timing` | with `follow_through=1` entry is the open of the candle after the follow-through candle; confirm < trigger < entry indices; entry price/time taken from that candle |
| `test_breakout_retest_variant_waits_for_holding_pullback` | retest variant: a close back through the level fails the level; a holding pullback (touch within band + close beyond) triggers, `retest_hold` evidence recorded |
| `test_breakout_reward_filter_counts_rejections` | `min_level_rr` filter rejects when reward/risk to the next level is insufficient |

## 4. Entry window & session boundaries

| test | asserts |
|---|---|
| `test_entry_window_boundaries` | `[09:20, 15:20)` exactly: 09:15 no, 09:20 yes, 15:15 yes, 15:20/15:25 no |
| `test_short_session_is_rejected` | fewer than `MIN_SESSION_CANDLES` (10) ⇒ no candidates, counted |

## 5. Selection hierarchy

| test | asserts |
|---|---|
| `test_one_trade_per_session_and_breakout_priority` | a breakout beats a same-session reversal; non-chosen candidates counted as duplicates |
| `test_conflicting_reversals_earliest_wins_and_reject_variant` | earliest confirmation wins, tie → BEAR, `conflict_rule='reject'` drops the pair |
| `test_no_signal_records_no_trade` | empty candidate set → no trade + counter |

## 6. Exit mechanics / cost & label parity

| test | asserts |
|---|---|
| `test_exits_opens_abs_matches_production_exits_opens` | absolute-price exit walker ≡ production percentage walker on stop/target/EOD/never-hit/same-open cases, both directions |
| `test_stop_checked_before_target_on_same_open` | stop precedence (identical to production) |

## 7. Baseline reproduction

| test | asserts |
|---|---|
| `test_baseline_is_deterministic` | two calls to production `run_opens_range` on the same range are identical |
| `test_baseline_normalisation_round_trips_pnl` | normalised baseline rows keep production points/R/win-loss/period and gain the shared schema keys |
| `test_baseline_run_entries_inside_window` | every baseline entry time is inside the entry window |

## 8. Integrated runner (real snapshot data)

| test | asserts |
|---|---|
| `test_candidate_run_has_no_duplicates_and_valid_entries` (×2 instruments) | ≤1 trade/session; entries inside the window; risk/entry positive; `entry_time > trigger_time ≥ signal_time`; labels and periods valid |
| `test_position_risk_positive_for_all_produced_trades` (×2 instruments) | full-range run: positive risk, correct lot size, net = gross − cost on every row |
| `test_trade_pnl_reconciles_with_daily_and_totals` | Σ trade net = metric total = Σ daily; Σ R matches; win+loss+flat = n; gross − n×cost ≈ net |

## 9. No-look-ahead (property tests)

| test | asserts |
|---|---|
| `test_no_lookahead_property_synthetic` | for every prefix of a synthetic session, every candidate found on that prefix is reproduced identically (family/confirm/trigger/entry) in the full run — the signal never depends on later candles |
| `test_no_lookahead_property_real_session` | same property over real NIFTY sessions with multiple truncation points |
| `test_signal_uses_only_prior_session_levels` | levels for day D always come from a session < D |

## 10. Metric helpers

| test | asserts |
|---|---|
| `test_wilson_and_drawdown_helpers` | Wilson interval brackets the point estimate; drawdown (dd, peak, trough, duration) and empty-series behaviour; block bootstrap returns an interval containing the mean |

## Gate linkage

* Every FAIL here fails **G5 (no bias)**.
* PIT/structure results come from `data_quality.py` (G5).
* G7 (credit-spread economics) is independent of this suite and is BLOCKED
  when no historical option premiums exist.
