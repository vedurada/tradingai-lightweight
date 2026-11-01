# ADD-ON — Stop Location, Entry Cushion and Hypothetical Trade Generation

**Status: PRE-REGISTERED before any evaluation.** Every parameter, definition, split,
selection rule and gate below was fixed before a single arm was computed. Any later
change must be recorded in the Amendment log with a reason and a timestamp, and a
change that could be influenced by results invalidates the run.

**Write boundary:** `research/prevday_cpr_spread_study/stop_forensics/addon_stop_placement/`
only. The parent study's files are inputs, not to be modified.

**Production is frozen.** No production code, signal, alert, configuration, threshold,
deployment or restart is touched by this add-on. Every output is historical research:
not an alert, not a recommendation, not an order.

---

## 0. Objective and non-negotiables

1. For every **unchanged production baseline trigger** (the 129 signals produced by
   `app.research.cpr_trigger_engine.run_opens_range(inst, '2026-07-06',
   '2026-10-21', 'plain')`), derive candidate stop locations B0, S1–S5 using **only
   information available at the proposed entry timestamp**.
2. Measure the entry cushion for every candidate trade.
3. Emit one hypothetical trade record per (signal, variant), including NO TRADE rows
   with an explicit rejection reason.
4. Run two **independent** experiments: **A** = entry conditions with the production
   stop/target; **B** = stop placement on the same entry signals. A combined
   entry-plus-stop candidate may only be tested after both are evaluated, and only
   under the pre-registered pre-check in §7.
5. Compare fairly: gap-aware realized R, conservative ambiguous-candle handling,
   costs, IS/VAL/OOS, parameters selected on VAL only, OOS untouched until frozen.

The baseline entry, direction, session set and target are **never** changed by
Experiment B. The only thing that changes in Experiment B is the stop price.

---

## 1. Data, scope and frozen baseline

| item | value |
|---|---|
| Instruments | NIFTY, BANKNIFTY (index/spot level only) |
| Range | 2026-07-06 .. 2026-10-21 (complete sessions only) |
| IS | 2026-07-06 .. 2026-08-31 |
| VAL | 2026-09-01 .. 2026-09-30 |
| OOS | 2026-10-01 .. 2026-10-21 |
| Bars | 5-minute candles, `market_candles_5m`, timestamp offset `+05:30` |
| Baseline call | `run_opens_range(instrument, '2026-07-06', '2026-10-21', 'plain')` |
| Baseline stop | 0.5 % of entry (B0) |
| Baseline target | 2.0 % of entry, **unchanged in every variant of this add-on** |
| Exits | production opens model: subsequent candle **opens**, stop checked before target, flat at the 15:20 open |
| Baseline source | the study snapshot `outputs/snapshot/tradingai_snapshot.db` (read-only) |

No options/credit-spread/rupee claim is made. There is no historical option data in
this deployment (`option_contracts` = 0, `option_snapshots` = 0), so index points are
never converted to rupees.

### 1.1 OOS independence disclosure (pre-registered)

The 2026-10-01..10-21 window and the baseline signal set were already inspected in
the parent study (entry filters E1–E7). The **stop-placement hypotheses** S1–S5 are
new and have not been examined anywhere, but their OOS trades are the same
underlying signals that were previously reported. Therefore, for this add-on:

- OOS results are **exploratory-leaning**: they are a genuine first look at the new
  stop hypotheses, but the window is not virgin.
- **No variant can be declared eligible for human review in this add-on**, even if
  every gate passes. A pass is reported as `PASS_EXPLORATORY` and requires a fresh
  forward window (unavailable: data ends 2026-10-21) or a separately pre-registered
  replication before any review.
- This is recorded as field `oos_independence: PARTIAL` in every gate file.

---

## 2. Structural definitions (all point-in-time)

"At the proposed entry timestamp" means: only candles with
`timestamp <= trigger candle` may be used. The entry itself is the **open of the
candle after the trigger candle** (production rule). Nothing after the trigger candle
may influence a stop, a buffer, a swing, a retest or a rejection.

### 2.1 Confirmed swing (S1, S5)

- Fractal parameter **m = 2**.
- Bar `i` is a **swing high** iff
  `high[i] > high[i-1], high[i] > high[i-2], high[i] > high[i+1], high[i] > high[i+2]`
  (strict). A **swing low** is the strict mirror.
- A swing is **confirmed at the close of bar `i + m`**.
- A swing is **usable** for a signal only if `i + m <= trigger_idx`. Bars
  `i+1..i+m` are confirmation bars, not future information.
- Lookback: `i >= trigger_idx - SWING_LOOKBACK` with **SWING_LOOKBACK = 20** bars.
- Selection: the **most recent usable swing** in the trade-relevant direction
  (swing high for BEAR, swing low for BULL). If the most recent one is on the wrong
  side of the entry, the structure is treated as **violated → NO TRADE** (the module
  does not skip back to an older, wider swing).

### 2.2 Failed-break extreme (S2)

- "Relevant opposing level" at the trigger:
  - BEAR: `X` = the nearest level of the day bundle **strictly above** the entry
    (min of `{r1, r2, pdh, tc, pp}` above entry).
  - BULL: `Y` = the nearest level **strictly below** the entry
    (max of `{s1, s2, pdl, bc, pp}` below entry).
- A **failed break attempt** is a sequence of bars before the trigger in which price
  crossed the level (`high >= X` for BEAR, `low <= Y` for BULL) and then **at least
  one close returned inside** (`close < X` for BEAR, `close > Y` for BULL) before the
  trigger.
- Attempt window = from the first crossing bar to the last bar **before** the
  trigger. Extreme = `max(high)` over that window (BEAR) / `min(low)` (BULL).
- S2 stop = extreme + EPS (BEAR) / extreme − EPS (BULL).
- If no failed attempt exists, **S2 = NO TRADE** (no invented stop).

### 2.3 Retested level (S3)

- Retest window = bars `[trigger_idx, entry_idx − 1]` (the entry bar itself is not a
  retest window: its open is the entry price).
- A **retest** is a bar in that window whose extreme returns to within
  **Z = 0.10 %** of the trigger level `L` and which **closes back on the trade-favourable
  side** (BEAR: `close < L`; BULL: `close > L`); `L` = the production level price of
  the signal, `NULL → NO TRADE`.
- Retest extreme = `max(high)` from `trigger_idx` to the retest bar (BEAR) /
  `min(low)` (BULL).
- S3 stop = retest extreme + EPS (BEAR) / retest extreme − EPS (BULL).
- If no retest occurred, **S3 = NO TRADE**.

### 2.4 CPR-boundary invalidation (S4)

- Applicable only when the setup is a CPR-boundary setup:
  `BELOW_CPR`, `ABOVE_CPR`, `BRK_BC`, `BRK_TC`. All other setups → **S4 = NO TRADE**
  (the setup does not support a CPR-boundary invalidation).
- BEAR: stop = `tc + EPS`. BULL: stop = `bc − EPS` (the opposite CPR boundary is the
  structural invalidation of a CPR break).

### 2.5 Structural stop with volatility buffer (S5)

- Uses the S1 swing (no swing → **NO TRADE**, no fallback).
- `median_range` = median intrabar range `(high − low)` of candles
  `0 .. trigger_idx` (inclusive), point-in-time; requires **≥ 3 bars**.
- S5 stop = S1 stop ± **K_VOL × median_range**, **K_VOL = 0.5**.
- The buffer is one-directional (always wider than S1).

### 2.6 Buffers, minimum and maximum

| parameter | value | meaning |
|---|---|---|
| EPS_PCT | 0.0002 | `EPS = 0.0002 × entry` (0.02 %), the minimum clearance beyond a structural extreme |
| Z | 0.0010 | retest tolerance (0.10 % of the level) |
| SWING_LOOKBACK | 20 bars | maximum distance between the swing bar and the trigger bar |
| SWING_M | 2 bars | fractal confirmation width |
| K_VOL | 0.5 | volatility buffer multiplier |
| VOL_MIN_BARS | 3 | minimum bars for a median-range buffer |
| MIN_STOP_PCT | 0.0025 | a stop closer than 0.25 % of entry is **unusable** → NO TRADE |
| MAX_STOP_PCT | 0.0150 | a stop wider than 1.50 % of entry is **excessive** → NO TRADE |
| PULLBACK_MULT | 1.0 | a stop closer than 1.0 × median bar range would be hit by ordinary bar noise |

A structural level on the wrong side of the entry is a **NO TRADE** for that variant.

### 2.7 Variant table

| variant | rule | no-trade condition |
|---|---|---|
| B0 | production 0.5 % of entry | never (baseline) |
| S1 | confirmed swing extreme + EPS | no usable swing, wrong side, outside MIN/MAX |
| S2 | failed opposite-side break extreme + EPS | no failed attempt, wrong side, outside MIN/MAX |
| S3 | retest extreme + EPS | no retest, no level price, wrong side, outside MIN/MAX |
| S4 | opposite CPR boundary + EPS | setup not `BELOW_CPR/ABOVE_CPR/BRK_BC/BRK_TC`, wrong side, outside MIN/MAX |
| S5 | S1 stop ± K_VOL × median range | same as S1 plus < VOL_MIN_BARS |

Every NO TRADE is a recorded row with a rejection reason, counted as a **missed
opportunity** in the metrics.

---

## 3. Entry cushion (per candidate trade)

For every (signal, variant) with a valid stop:

1. `stop_distance_pts = |entry − stop|`; `stop_distance_pct = stop_distance_pts / entry`.
2. `nearest_opposing_level`: nearest level **below** the entry for BEAR, **above** for
   BULL; report its name, price, and `distance_pts` / `distance_pct`.
3. `reward_to_target_pts = |entry × (1 ± 0.02) − entry|`;
   `rr_to_target = reward_to_target_pts / stop_distance_pts`.
4. `rr_to_nearest_level = nearest_opposing_distance_pts / stop_distance_pts`.
5. **Adverse excursion before favourable movement**:
   `mae_before_first_profit_pts` = the maximum adverse excursion measured over the
   bars from entry up to and including the **first bar whose close is on the
   profitable side of the entry**; if the trade never closes in profit, the full MAE
   is used. `bars_to_first_profit` is reported.
6. `pullback_would_hit = stop_distance_pts < PULLBACK_MULT × median_range_pts`
   (point-in-time median range, same definition as §2.5).
7. `stop_breached_before_target`: from the execution model (see §4).
8. `risk_excessive = stop_distance_pct > MAX_STOP_PCT` (rejection);
   `wider_than_production = stop_distance_pts > 0.005 × entry`.

A wider cushion is **not** a better trade. The cushion is reported as context; the
acceptance decision is made only by the gates.

---

## 4. Execution models

Two models are computed for every variant. Both are reported; the **primary gate uses
the production opens model** (the model the accepted baseline uses), and a variant
must also not fail the intrabar-conservative model.

- **`opens` (primary):** walk the candles after the entry; at each candle's **open**,
  if the open is beyond the stop, exit at that open (gap-through, realized R worse
  than −1); else if beyond the target, exit at that open; else continue. Flat at the
  15:20 open. Exactly the production `exits_opens` semantics with an absolute stop.
- **`intrabar` (conservative robustness):** at each candle, a gap beyond the stop or
  target at the open fills at the open; otherwise a stop touched intrabar fills **at
  the stop price**; a target touched intrabar fills **at the target price**; if a
  single bar touches **both**, the stop is assumed first (conservative lower bound)
  and the bar is counted as ambiguous. Flat at the 15:20 open.

Realized R = signed points of the modelled fill / `|entry − stop|`. Booked −1 R is
never assumed. Gap-through losses are modelled in both models.

---

## 5. Experiment A — entry conditions (production stop and target)

Reuse the parent study's **frozen** families and settings (selected on VAL there, not
re-selected here):

`E1_k1.00`, `E2_x0.10pct`, `E3_retest`, `E4_until_1100`, `E5_skip_q90`,
`E6_reentry`, `E7_conflict`, plus `BASELINE`.

For each: IS/VAL/OOS gap-aware net R/trade, trade count, stop-out rate, average loss,
largest loss, MAE/MFE, drawdown, target attainment, missed opportunities (signals
removed by the filter), results by instrument. No new entry filter is introduced and
no parameter is re-tuned.

## 6. Experiment B — stop placement (same entry signals)

All 129 baseline signals are held fixed. Each variant B0, S1–S5 is evaluated on the
same entry price, direction, target and exit model. Two comparisons are reported:

- **Full set:** each variant's own trade count (NO TRADE rows excluded).
- **Paired (primary):** B0 measured **on the same signals the variant accepts**, so
  the only difference is the stop price. This isolates stop placement from signal
  selection.

### 6.1 Selection (VAL only, pre-registered)

Among S1–S5, eligible = variants with **≥ 10 VAL trades** (opens model). The selected
variant = highest **VAL net R/trade**; ties (`< 0.02 R`) broken toward the **smaller
mean stop distance** (the more conservative risk). OOS is evaluated once, after the
selection is frozen. B0 is not selectable (it is the baseline).

### 6.2 Gates (added to, never relaxed from, the parent gates)

Compared against B0 on the paired subset, opens model, cost 0.10 R:

| gate | pass condition |
|---|---|
| G-A | OOS net R/trade > paired baseline net R/trade |
| **G-A2 (added)** | OOS **points per trade** not worse than paired baseline (guards against an R gain produced only by a smaller denominator) |
| G-B | improvement at 0.10 R holds at 0.20 R and 0.30 R, and the removed-signal counterfactual does not explain the gain |
| G-C | OOS maxDD ≤ 1.5 × baseline maxDD; MAE not worse; **largest loss not worse** (added); percentage-of-capital sub-gates INCONCLUSIVE (no verified capital base) |
| G-D | ≥ 2/3 periods positive; ≥ 4/6 full-range blocks positive; both instruments positive; **variant ranking consistency** = the selected variant is the best VAL variant in NIFTY AND in BANKNIFTY separately (added, replaces neighbour-stability which needs a parameter grid) |
| G-E | ≥ 15 OOS trades; ≥ 5 per instrument; paired block bootstrap CI does not straddle 0 |
| G-F | same signals, same execution, same costs, gap-aware, no DQ violations, no lookahead (`no_lookahead_checks` must all pass) |
| G-G | index-level only; no options/rupee claim |
| G-H | `oos_independence: PARTIAL` → even a full pass is `PASS_EXPLORATORY`, never eligible for review |

`INCONCLUSIVE` (not FAIL) when a variant has < 10 VAL trades or < 15 OOS trades.
A structurally sensible stop that worsens expectancy is **not** an improvement.

## 7. Combined entry-plus-stop (conditional)

Tested only if **all** of the following hold after A and B are frozen:

- Experiment B has a selected variant passing G-A and G-A2 on VAL-equivalent checks
  (`VAL net R/trade > paired baseline VAL` and `VAL points/trade ≥ paired baseline`).
- Experiment A's frozen entry filter has `VAL net R/trade > VAL baseline`.

Otherwise the combined step is **NOT RUN** and the reason is recorded: the add-on
must not spend the single OOS look on a candidate whose components both failed on
VAL. If it is run, the combined candidate uses the A entry filter's entries and the
B variant's stop, and is evaluated once on OOS with the same gates.

---

## 8. Deliverables

- `outputs/hypothetical_trades.csv` — one row per (signal × variant), including
  NO TRADE rows with `rejection_reason`.
- `outputs/experiment_b_metrics.json`, `experiment_b_paired.csv`,
  `experiment_b_selection.json`, `experiment_b_gates.json`.
- `outputs/experiment_a_arm_metrics.json` (+ per-arm CSVs).
- `outputs/cushion_analysis.csv`, `outputs/stopout_analysis.json`,
  `outputs/structural_diagnostics.json`, `outputs/data_quality.json`,
  `outputs/snapshot_meta.json`, `outputs/run_manifest.json`.
- `reports/ADDON_STOP_PLACEMENT_REPORT.md`.
- `run_manifest.json` at the add-on root.

Every record carries the data-quality and execution limitations (§1, §4).

## 9. Known limitations (pre-registered, not after-the-fact)

- 5-minute candles only: intrabar order of stop and target is unknowable; the
  conservative model assumes the stop first.
- No volume in the feed: no liquidity/participation filter.
- Fills are modelled (opens or stop/target touches), never guaranteed.
- The structural definitions are deliberately simple and pre-registered; they are not
  claimed to be the best possible structure.
- S3 will be sparse by construction (only signals with a completed retest before the
  entry); S4 applies only to CPR-boundary setups.
- The stopped-trade sample is small; every statistic is reported with its n.
- OOS independence is PARTIAL (§1.1).
