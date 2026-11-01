# Stop-Loss Forensics and Entry Optimization — Pre-Registration

Status: **FROZEN PRE-REGISTRATION** (written before any experiment was executed)
Scope: index (spot) level only — NIFTY and BANKNIFTY.
Directory: `research/prevday_cpr_spread_study/stop_forensics/` (isolated; no production file is modified).
Date of freeze: 2026-10-22. Authorisation: read-only audit + approved isolated research.

---

## 0. Non-negotiable boundary

No production code, live signal, alert, CPR calculation, StrategyEngine, OptionsEngine,
API, threshold, configuration, frontend or deployment is modified by this study. The
production trigger engine is **imported and executed unmodified** against a snapshot.
Every artifact this study writes lives under `research/prevday_cpr_spread_study/stop_forensics/`.
Nothing is committed, merged, deployed or restarted. A passing result authorises a
recommendation for separate human review only.

## 1. Baseline (frozen)

Baseline engine: `app/research/cpr_trigger_engine.py` (unmodified).

```
run_opens_range(instrument, '2026-07-06', '2026-10-21', 'plain')
```

Verified callable signature: `(instrument, date_start, date_end, variant='plain', stop_pct=0.005, target_pct=0.02)`.

Deployed flags observed at freeze time (imported from the module, not re-declared here):
`VALID=('NIFTY','BANKNIFTY','INDIA_VIX')`, `VARIANTS=('plain','aligned')`, `SHORT_ONLY=True`,
`SKIP_FRIDAY=True`, `SHADOW_SKIP_FRIDAY=True`, `BREAKOUT_ADDON=True`, `NO_CHASE_BEAR=False`,
`OPEN_STOP_PCT=0.005`, `OPEN_TARGET_PCT=0.02`, `OPEN_MIN='09:20'`, `OPEN_MAX='15:20'`,
`OPEN_EOD='15:20'`, `MIN_CANDLES=10`.

Baseline semantics as implemented (documented, not modified):

| Element | Rule |
|---|---|
| Trigger | first trigger of the session over scan candles (`timestamp[11:16] < '15:25'`); BEAR checked before BULL; first trigger per session wins |
| Trigger source | `bear_trigger`/`bull_trigger` on previous-session CPR/pivot/PDH/PDL levels; `BREAKOUT_ADDON` fallback on a fresh close-cross when no base trigger fires |
| Eligibility | `MIN_CANDLES=10` scan candles; a 15:20 candle must exist; Friday BEAR sessions skipped (`SKIP_FRIDAY`); `SHORT_ONLY` suppresses BULL base triggers |
| Entry | open of the candle **after** the trigger candle, entry window `[09:20, 15:20)` |
| Stop / target | 0.5 % / 2 % from the entry price; **stop checked before target** |
| Exit detection | **subsequent 5-minute OPENS only** (an open at/through the stop is a STOP, an open at/through the target is a TARGET) |
| Flat | open of the 15:20 candle; a session without a 15:20 candle is skipped (`missing_eod`) |
| Labelling | `decay_win` (tolerance label, not P&L) — reported as secondary only |

### 1.1 Sessions

Complete sessions only, `2026-07-06 .. 2026-10-21`, NIFTY + BANKNIFTY.
`2026-10-22` is excluded (live, incomplete session at study time).
Short sessions (73 candles) are **not** repaired; they remain in the data and are reported.
Data-quality defects are reported, never silently corrected.

### 1.2 Chronological splits (pre-registered)

| Split | Range |
|---|---|
| IS | 2026-07-06 .. 2026-08-31 |
| VAL | 2026-09-01 .. 2026-09-30 |
| OOS | 2026-10-01 .. 2026-10-21 (untouched until every parameter and selection decision is frozen) |

### 1.3 Walk-forward

Six contiguous, equal-count chronological session blocks over the full range
(2026-07-06 .. 2026-10-21). Blocks are evaluated with frozen parameters; no re-selection
inside a block (no leakage).

## 2. Outcome accounting (corrected, applied identically to baseline and candidates)

The approved audit found 324/324 STOP-labelled trades booked at exactly −1.000 R while
their modelled fills were **beyond** the stop. This study therefore reports **realized R**
computed from the modelled exit fill:

```
risk_pts  = |entry - stop_price|                       stop_price = entry*(1-0.005) BULL / entry*(1+0.005) BEAR
signed_pts= (exit - entry) BULL / (entry - exit) BEAR
realized_R= signed_pts / risk_pts
```

* The production trigger/exit rules are **not** changed — only the accounting of the same modelled fill.
* The modelled fill is a *next-bar open model*, never presented as a guaranteed executable market fill.
* `stop_overshoot_pts` = adverse distance between the intended stop and the modelled fill; `stop_overshoot_r` = that distance ÷ `risk_pts`.
* `target_truncation_pts` / `_r` = favourable distance between the intended target and the modelled fill (booked target R is exactly 4.000 R, so the truncation is currently invisible in headline R).
* Every STOP/TARGET fill that is *not* exactly at the intended level is reported as a gap-through event.
* Where candle data cannot establish the order of a stop and a target inside one candle, a **conservative bound** is reported (stop-first = lower bound, target-first = upper bound). Intrabar execution order is never invented.

### 2.1 Excursions and forward paths (derived from the snapshot candles only)

Per trade, over the holding window (entry candle → exit candle, inclusive):

* `mae_hl_pts/r` — intrabar adverse excursion from the high/low extremes.
* `mfe_hl_pts/r` — intrabar favourable excursion.
* `mae_open_pts/r`, `mfe_open_pts/r` — open-based adverse/favourable excursion.
* `time_to_exit_minutes`.
* `fwd15/fwd30/fwd60_r` — signed underlying forward return from the exit fill over 15/30/60 minutes (close of the first candle at or after the horizon), plus the worst adverse and best favourable excursion inside that window.

Undocumented `trade_journal` MAE/MFE and `cf_*` columns are **never** used as a source of truth.

### 2.2 Counterfactual stop widths (analysis only, not production behaviour)

Stop widths `1.00 %, 0.75 %, 0.50 %, 0.375 %, 0.25 %` are re-simulated with the identical
open-based exit walk (target 2 %, stop-first, flat 15:20 open). For each width the study
reports the realised R and exit reason per trade. These are hypothetical widths; they are
not, and are never described as, production behaviour.

## 3. Cost model

Round-trip cost applied to R: **0.10 R per trade** (production display placeholder
`COST_R_PER_TRADE`), plus the sensitivity grid `{0.00, 0.10, 0.20, 0.30} R`.
Index points are reported separately from R. No rupee or option-premium P&L is claimed.

## 4. Forensic classification of stopped trades

Grouped by instrument, direction, setup (level token), session date and entry time.
Each stopped trade is tested against the following hypotheses (all computed point-in-time):

| Flag | Definition |
|---|---|
| `extended_entry` | \|entry − level_price\| / level_price > 0.25 % (extension in the trade direction) |
| `large_gap` | \|session open − previous close\| / previous close > 0.25 % |
| `narrow_cpr` | previous-session CPR width below the IS 25th percentile (frozen on IS) |
| `wide_cpr` | previous-session CPR width above the IS 75th percentile (frozen on IS) |
| `range_vs_stop` | session median intrabar range (candles up to the trigger only) > stop distance (0.5 % of entry) |
| `weak_followthrough` | maximum favourable excursion in the first 3 candles after entry ≤ 0 |
| `cpr_crossings` | number of closes crossing the CPR boundary (BC/TC) after the entry ≥ 2 |
| `conflicting_triggers` | a trigger of the opposite direction existed in the same session (production trigger functions) |
| `stop_then_continued` | adverse excursion > 0 inside the 60-minute forward window after the stop fill |
| `stop_then_reversed` | favourable excursion > 0 inside the 60-minute forward window after the stop fill |
| `opposite_entry_later` | a valid opposite-direction trigger occurred **after** the stop fill |
| `reentry_opportunity` | a fresh close-cross in the original direction occurred **after** the stop fill (same session or later) |

### 4.1 Missed-direction categories (reported separately; category C is never counted)

For each stopped trade the study asks whether the opposite direction was already inferable.

* **A — inferable at the original entry**: an opposite-direction trigger (production
  `bear_trigger`/`bull_trigger` on the session levels) occurred at or before the entry
  timestamp, i.e. the information was available when the trade was taken.
* **B — inferable only after subsequent confirmation**: the opposite-direction trigger
  occurred strictly after the entry (so the trade could only have been taken later).
* **C — retrospectively apparent only**: no opposite-direction trigger existed at any time
  during the session; the direction is visible only in hindsight.

Only A and B are treated as *potentially missed tradable* signals; C is reported as
context and explicitly excluded from missed-opportunity counts.

## 5. Pre-registered candidate entry conditions

All candidates act on the **unchanged production trigger set** (same sessions, same
production triggers, same levels, same execution model). No new signal family is introduced.

| ID | Rule | Formula | Parameter grid (pre-registered) | Rationale |
|---|---|---|---|---|
| **E1** | Risk-distance filter | skip if `0.005*entry > k * median_range_pit` where `median_range_pit` = median(high−low) over candles up to and including the trigger candle | k ∈ {1.00, 1.25, 1.50} | a 0.5 % stop is wider than the session's typical bar range → structurally over-sized risk |
| **E2** | Extension filter | skip if `(entry − level_price)·sign / level_price > x` | x ∈ {0.0010, 0.0025} | entering after the level has already been exceeded extends the stop distance and invites re-tests |
| **E3** | Retest re-entry | if the move beyond the level exceeds `y` before the entry, wait for a retest: a candle whose extreme returns within `z` of the level **and** closes on the original side; enter at that candle's **close** (a price available at that time). A close back through the level cancels the trade; no retest by 15:20 → no trade. If the move never exceeds `y`, the baseline entry is kept | y = 0.0025, z = 0.0010 | avoids entering at the extreme of an extended move and prices the entry at a level that actually traded |
| **E4** | Time window | keep only entries whose entry time ∈ `[09:20, W)` | W ∈ {11:00, 13:00} | some hours may be systematically adverse (fog/late-session reversals) |
| **E5** | CPR-width regime | skip if the **previous session** CPR width is in the frozen IS tail | skip if width < IS q10; skip if width > IS q90 | narrow CPR days trend; wide CPR days mean-revert |
| **E6** | Re-entry after stop | after a baseline STOP on level L, arm (instrument, L) for **later sessions only** (one-session cooldown); allow **at most one** re-entry per stop event, triggered by a fresh close-cross beyond L in the original direction, entered at the next eligible open in `[09:20, 15:20)` with the identical exit model | binary | a stop-out followed by a level re-assertion is a distinct, PIT-defined opportunity |
| **E7** | Conflict ranking | if a BEAR and a BULL trigger both qualify, rank by point-in-time reward-to-risk to the next relevant level; if no defensible comparison exists, skip the session | binary | see 5.1 |

Neighbouring settings are the remaining grid points of each family (and ±1 step where a
continuous grid exists). Parameter stability is measured on the neighbour grid.

### 5.0 Level groups (fixes the sign convention for E2 and the retest/cancel rules for E3)

Every production trigger belongs to exactly one group. The group fixes the **excursion
direction** (the side price travelled to reach the level), which makes the signed
extension of an entry unambiguous: `signed_extension = (entry - level) * dir`, `dir = +1`
for an upward excursion and `-1` for a downward one. A positive signed extension means
the entry was taken *after* price had already travelled that far beyond the level.

| Group | Levels | Direction | `dir` | E3 retest | E3 cancel |
|---|---|---|---|---|---|
| 1 | BEAR fade at resistance: `R1`, `R2`, `PDH` | up | +1 | a candle whose low returns to within `z` above the level and which closes **below** the level | a close **above** the level |
| 2 | BULL fade at support: `S1`, `S2`, `PDL` | down | −1 | a candle whose high returns to within `z` below the level and which closes **above** the level | a close **below** the level |
| 3 | BULL breakout: `ABOVE_CPR`, `BRK_R1`, `BRK_R2`, `BRK_PDH`, `BRK_TC` | up | +1 | a candle whose low returns to within `z` above the level and which closes **above** the level | a close **below** the level |
| 4 | BEAR breakout: `BELOW_CPR`, `BRK_S1`, `BRK_S2`, `BRK_PDL`, `BRK_BC` | down | −1 | a candle whose high returns to within `z` below the level and which closes **below** the level | a close **above** the level |

E2 therefore uses `signed_extension / level > x` (not the raw entry–level distance).
E3 measures the excursion between the **trigger candle and the baseline entry candle**
(inclusive) and searches for the retest from the baseline entry candle onwards, stopping
at the 15:20 flat.

### 5.0a Tie-break convention (conservative setting)

Within a family, ties are broken towards the stricter filter: E1 → the **smaller** `k`
(more signals removed), E2 → the **smaller** `x`, E4 → the **earlier** window end.
E3, E5 and E6 have one setting per family (E5 has two tail variants) and therefore no
tie-break.

### 5.1 E7 status under the deployed configuration

Under `SHORT_ONLY=True` the production engine never emits a BULL base trigger
(`u = None if SHORT_ONLY else bull_trigger(...)`), so a BEAR/BULL conflict inside one
session cannot arise from base triggers; the only BULL source is the breakout add-on,
which by construction is only consulted when no base trigger fired. The study still
**detects** conflicts with the production trigger functions and reports the count; if the
conflict set is empty, **E7 is marked BLOCKED** (it cannot be evaluated without changing
the trigger set, which is prohibited) and is excluded from selection.

### 5.2 Selection rule (frozen before any candidate result exists)

1. Every family is evaluated over its pre-registered grid on **IS + VAL only**.
2. Within a family, the setting with the highest gap-aware **VAL net R per trade** is
   selected, subject to a minimum of 10 VAL trades; ties (|Δ| < 0.02 R/trade) are broken
   towards the **more conservative** setting (larger k, larger x, tighter window, q90 skip).
3. If no setting of a family reaches 10 VAL trades, the family is marked **INCONCLUSIVE**
   and excluded from selection.
4. The **primary candidate** is the family with the best VAL score under rule 2 (ties broken
   by the same conservatism rule).
5. The OOS period is evaluated **once**, after every parameter and selection decision above
   is frozen. All families are still reported descriptively; reporting several families'
   OOS numbers is not a selection, and the multiplicity caveat is stated in the report.
6. No parameter, threshold, split or gate may be changed after the OOS result is seen.
   Any deviation is appended to `unplanned_runs` in this file with a reason **before** it is
   executed; `unplanned_runs` is empty at freeze time.

### 5.3 Every arm must report

eligible signals, executed trades, trade count, gap-aware net R, net R per trade,
expectancy per trade and per session, net index points, profit factor (undefined cases
reported explicitly), maximum drawdown in R, MAE distribution, largest realised loss,
stop count and overshoot, target outcomes, missed-opportunity counterfactual (realised
expectancy of the signals a filter removed), breakdowns by instrument / direction / setup /
gap category / CPR width / time of day, cost sensitivity at 0/0.10/0.20/0.30 R,
neighbour-parameter stability, bootstrap confidence intervals and the six-block walk-forward.

## 6. Hard acceptance gates (mandatory)

| Gate | Requirement |
|---|---|
| **G-A** OOS improvement | candidate OOS gap-aware net expectancy per trade strictly greater than the frozen baseline OOS at 0.10 R |
| **G-B** not a trade-count artifact | improvement survives the cost grid and holds per session; the counterfactual expectancy of removed signals is reported |
| **G-C** risk | max drawdown ≤ 1.5 × baseline max drawdown; max drawdown ≤ 20 % of the capital base; largest single loss ≤ 5 % of the capital base; MAE not worse than baseline |
| **G-D** stability | positive in ≥ 2 of 3 chronological periods, ≥ 4 of 6 walk-forward blocks, both instruments, and ≥ 70 % of neighbouring parameter settings |
| **G-E** evidence sufficiency | ≥ 15 OOS trades total, ≥ 5 per instrument, and a block-bootstrap CI for the candidate-vs-baseline improvement that does not straddle zero |
| **G-F** integrity | prefix-property and PIT checks pass; no leakage; identical execution/cost model across arms; gap-aware accounting; no unresolved data-quality violation |
| **G-G** scope | index-level only; no option-premium, bid/ask or rupee-profit claims |

**Capital base:** no production-confirmed capital base exists for this research; the
percentage-of-capital sub-gates of G-C are therefore marked **INCONCLUSIVE** and the
risk gate is evaluated on the R-based and index-point comparisons that are confirmable.
No capital amount is invented and index points are never equated to rupees.

A gate that cannot be judged is INCONCLUSIVE; a failed gate is FAIL. A candidate that does
not pass **every** gate is **not eligible for human review**. Even a full pass changes no
production behaviour.

## 7. Known limitations (frozen)

* No historical option premiums or bid/ask data exist in this deployment → no credit-spread
  economics, no option profitability, no rupee profit claims.
* The 5-minute feed carries no volume (`volume = 0` on every row) → no liquidity or
  participation filter is possible.
* Only 5-minute candles are stored → intrabar order inside one bar is unknowable; ambiguous
  stop/target bars are reported as bounds.
* The exchange holiday calendar is applied for non-session checks only; no calendar is inferred
  from the data itself.
* The production DB is live during the study; a consistent `Connection.backup` snapshot is the
  only data source, and live writes after the snapshot are outside this study.
* Sample size: OOS covers ~15 sessions × 2 instruments; most statistics are small-sample and
  are reported with their sample size and interval.

## Amendment log (all amendments were made BEFORE the first candidate run)

| # | Date | Change | Reason |
|---|---|---|---|
| A1 | 2026-10-22 | Added §5.0 (level groups, `dir` sign convention, E2/E3 retest and cancel rules) and §5.0a (conservative tie-break) | The freeze-time wording of E2 and E3 did not fix the sign of the extension nor the group-specific cancel rule, and the tie-break rule named "more conservative" without saying which direction is conservative. Both are fixed here, before any candidate was evaluated, so no result could have influenced the definition. No parameter, threshold, split or gate was changed. |
| A2 | 2026-10-22 | E7 implemented as a **filter-only** arm | Under the deployed `SHORT_ONLY=True` configuration the production engine never trades a BULL base trigger. Ranking the two conflicting directions and then *flipping* would trade a signal family the production trigger set does not act on, which the pre-registration forbids. E7 therefore keeps the production direction only when it ranks at least as well on point-in-time reward-to-risk, and skips the session otherwise. Sessions where the opposite direction would have ranked better are reported descriptively (a flip is not traded). |
| A3 | 2026-10-22 | Walk-forward blocks computed over the full range | §1.3 pre-registers six chronological blocks over the full range with frozen parameters. The first implementation restricted the block comparison to the OOS window, which left the early blocks empty. This correction makes the implementation match the pre-registration; no parameter, threshold, split or gate changed. |

`unplanned_runs` is empty: the study executed exactly the pre-registered arms
(E1 ×3, E2 ×2, E3, E4 ×2, E5 ×2, E6) on the frozen baseline.
