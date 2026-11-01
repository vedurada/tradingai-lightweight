# Research Specification (FROZEN — pre-registration)

**Study:** NIFTY previous-day price action + CPR + opening gap + opening-range breakout/retest → intraday direction signals (index level)
**Study dir:** `research/prevday_cpr_spread_study/` (research-only; no production file is read-modified, no production DB write)
**Version:** 1.0 · **Frozen:** 2026-10-22, before any model was executed · **Status:** pre-registered

---

## 0. Scope, and the boundary that governs every claim in this study

This study produces **directional signals on the NIFTY 50 index**, measured in **index points** and in **R multiples** (R = adverse move to the stop).

It does **NOT** produce option-spread profitability, because **no historical option premium, IV, greek, OI, bid or ask exists on this system** (verified: `option_contracts` = 0 rows, `option_snapshots` = 0 rows, `options_provider_cache` = `OPTIONS_UNAVAILABLE` for both underlyings; `app/options/provider.py` documents yfinance 404 / NSE 403 / Yahoo 429 from this VM).

Accordingly:

* A **BULLISH** signal is a *candidate* for a bull put credit spread; a **BEARISH** signal is a *candidate* for a bear call credit spread. Mapping is structural only.
* **No credit, no option P&L, no breakeven in option points, no ₹ expectancy, no live tradability claim** is made anywhere in this study.
* Index points and R are never presented as option profits. Where a monetary figure appears it is either (a) a **capital-reference ratio** used only as a *normalisation* for drawdown, or (b) a clearly-labelled **proxy cost** in R (see §7.4) representing hypothetical option-spread friction — never a measured option cost.
* The ₹1,000/trade and ₹2,000/day risk budgets **cannot be validated** here: max loss of a credit spread is `width − credit`, and no credit is observable. This is stated as a limitation, not approximated away.

---

## 1. Data, universe, and point-in-time rules

| item | rule |
|---|---|
| Universe | **NIFTY 50 only** (`^NSEI`, `instruments.instrument_id='NIFTY'`). BANKNIFTY is a **separate study** (§12), never pooled with NIFTY. |
| Source table | `market_candles_5m` (production table, **read-only**; the study reads a verified snapshot copy) |
| Bars | 5-minute, session 09:15–15:30 IST, 75 bars (09:15 … 15:25 open). Timestamps carry `+05:30`. |
| Sessions | **Complete sessions only**: 75 sessions, 2026-07-06 … **2026-10-21**. The in-progress session **2026-10-22 is excluded**. |
| Session validity | A session is usable iff it has ≥ 70 bars and its 09:15 bar exists. Two sessions have 73 bars (2026-09-21 missing 15:20/15:25; 2026-10-15 missing 11:45/11:50) → flagged, not silently dropped. |
| Trading calendar | `app/market.nse_calendar` (2026 weekday holidays; verified 2026-09-28; coverage to 2026-12-31). The three absent weekdays in the window (2026-09-14, 2026-10-02, 2026-10-20) are NSE holidays — **not** data gaps. |
| "Previous session" | The **previous session present in the data** (holiday-aware), never the previous calendar weekday. A gap of > 3 calendar days between consecutive data sessions is flagged `STALE_PREV_SESSION` and the session is excluded from primary results. |
| Look-ahead ban | Previous-day features use only bars of sessions `< D`. Intraday features use only bars of session D up to and including the **signal bar**. A signal is emitted only **at a bar close**; the entry price is the **open of the next bar** (never the signal bar's close, never the signal bar's open). |
| Today’s final H/L/C | Never used for an intraday signal. |
| Volume | `volume = 0` on every row (yfinance index) → **no true VWAP**. Only the documented equal-weight proxy (§5) is used, and it is always labelled `VWAP_PROXY_EQW`. |

## 2. Feature definitions (all point-in-time)

### 2.1 Previous-day price action (from the prior session's 5-minute bars)
`pd_open, pd_high, pd_low, pd_close, pd_range = pd_high − pd_low`
`body = pd_close − pd_open`; `body_pct = body / pd_range` (0 if range = 0)
`upper_wick = pd_high − max(pd_open, pd_close)`; `lower_wick = min(pd_open, pd_close) − pd_low`
`close_location = (pd_close − pd_low) / pd_range` → 0 if `pd_range = 0` (explicitly handled)
`pd_return_pct = 100 × (pd_close − pp_close) / pp_close` (pp = session before pd)
`range_ratio = pd_range / median(range of the 10 sessions before pd)` (needs ≥ 5 prior sessions, else `None`)
Structure vs the session before pd: `HH_HL / HH_LL / LH_HL / LH_LH` (higher-high = pd_high > pp_high; higher-low = pd_low > pp_low)
Day type: `INSIDE` (pd_high ≤ pp_high and pd_low ≥ pp_low) / `OUTSIDE` (pd_high ≥ pp_high and pd_low ≤ pp_low) / `NORMAL`
`close_class`: `NEAR_HIGH` if close_location ≥ 0.70; `NEAR_LOW` if ≤ 0.30; else `MIDDLE`

### 2.2 CPR (identical formula to production `app/research/cpr_strategy_engine.py:33`)
`P  = (pd_high + pd_low + pd_close) / 3`
`BC = (pd_high + pd_low) / 2`
`TC = 2·P − BC`
`lower_CPR = min(BC, TC)`, `upper_CPR = max(BC, TC)` (production normalises TC ≥ BC — same result)
`cpr_width_pts = upper_CPR − lower_CPR`; `cpr_width_pct = 100 × cpr_width_pts / P`
`cpr_class`: production thresholds reused — `NARROW` if width_pct < 0.15, `WIDE` if > 0.30, else `NORMAL`
`cpr_width_pctile`: percentile of today's width against the previous 20 sessions' widths (needs ≥ 10 prior sessions, else `None`)
Pivots: `R1 = 2P − pd_low`, `S1 = 2P − pd_high`, `R2 = P + pd_range`, `S2 = P − pd_range`

### 2.3 Opening gap (magnitude and location recorded separately)
`gap_points = today_open − pd_close`; `gap_pct = 100 × gap_points / pd_close`; `gap_vs_prev_range = gap_points / pd_range`
Location, two independent axes (mutually exclusive within each axis, no ambiguity):
* `gap_dir ∈ {UP, FLAT, DOWN}` (FLAT if |gap_points| ≤ 2 pts)
* `cpr_pos ∈ {ABOVE_CPR, INSIDE_CPR, BELOW_CPR}` (open vs lower/upper CPR)
* `prev_range_pos ∈ {ABOVE_PDH, INSIDE_RANGE, BELOW_PDL}`
→ 3 × 3 = 9 gap cells. Magnitude (points / % / fraction of prior range) is always stored separately so no conclusion depends on a label.

### 2.4 Opening range
Primary **OR15** = bars 09:15, 09:20, 09:25 (completed range 09:15–09:30). Alternative **OR30** = bars 09:15…09:40 (09:15–09:45).
`or_high`, `or_low` from those bars only. A signal may not use an incomplete OR.

### 2.5 VWAP (documented proxy — volume is zero)
`vwap_proxy(t) = mean(typical_price(candles 09:15..t))`, `typical = (high+low+close)/3` — **equal-weight**, i.e. not a volume-weighted average. Production `app/live/engine.py:222` uses the same fallback when volume = 0. `vwap_relation ∈ {ABOVE, BELOW}` of the signal bar's close.

## 3. Direction models (each evaluated independently)

Every model returns exactly one of **BULLISH / BEARISH / NO TRADE** per session, with a reason code. NO TRADE is a first-class outcome.

| Model | Definition |
|---|---|
| **A — prev-day direction** | BULLISH iff `close_location ≥ th` AND pd made a higher low vs pp; BEARISH iff `close_location ≤ 1−th` AND pd made a lower high; else NO TRADE (`PREV_DAY_NEUTRAL`). `th ∈ {0.60, 0.70, 0.80}` (pre-declared). Signal time = OR15 completion (09:30). |
| **B — CPR position** | BULLISH iff a bar **closes above upper_CPR** (variant `B_accept2` requires 2 consecutive closes above); BEARISH iff a bar **closes below lower_CPR**; else NO TRADE (`NO_CPR_BREAK`). First qualifying bar wins. |
| **C — A + CPR** | BULLISH iff Model A bullish **and** no close below lower_CPR so far today **and** a bar closes above upper_CPR (upside confirmation). BEARISH mirror. A/C disagreement → NO TRADE (`DIRECTION_DISAGREEMENT`). |
| **D — A + CPR + gap** | As C, plus `setup_type`: **CONTINUATION** when gap direction agrees with the previous-day direction and CPR position agrees; **REVERSAL** when gap direction opposes the previous-day direction and price later reclaims the far CPR boundary (bearish pd + gap up + reclaim above upper_CPR = bullish reversal). Primary D variant keeps CONTINUATION only; the reversal variant is reported separately, never pooled with it. |
| **E — OR breakout / retest** | Bullish: a bar **closes above** a level L ∈ {OR15 high, pd_high, upper_CPR}. Then either (i) `breakout`: the next bar also closes above L (follow-through) → signal at that close; or (ii) `retest`: price returns to within `retest_band` of L and closes back on the trade side of L → signal at that close. A failed retest (close through L) → NO TRADE (`RETEST_FAILED`). Bearish mirror. **Max entry delay**: signal must occur by 14:45, else NO TRADE (`ENTRY_WINDOW`). |
| **F — C or E + VWAP proxy** | Model F = Model C variant `C_accept2` plus a VWAP-proxy filter (bullish needs close ≥ vwap_proxy, bearish needs close ≤ vwap_proxy); disagreement → NO TRADE (`VWAP_CONFLICT`). Proxy only. |

**Controls (reported as baselines, never pooled into a model):** A-only, B-only, E-breakout-only, E-retest-only, no-trade baseline, and the **production baseline** `app.research.cpr_trigger_engine.run_opens_range(instrument, start, end, 'plain')` reproduced unmodified from a snapshot.

**Model priority / tie-break:** if two models fire on the same session, the *model* comparison keeps them separate; within a model, the **first** qualifying bar wins (no cherry-picking), and if a bar satisfies both bullish and bearish conditions → **BEAR** wins (production priority), recorded as `TIE_BEAR_PRIORITY`.

## 4. Entry, stop, target, exit (index level)

* **Entry** = open of the bar **after** the signal bar. If that bar does not exist → NO TRADE (`NO_ENTRY_BAR`).
* **Direction convention**: BULLISH = long-NIFTY equivalent (bull put candidate); BEARISH = short-NIFTY equivalent (bear call candidate). `dir = +1 / −1`.
* **Stop distance** candidates (pre-declared, selected on IS+VAL only, §6):
  * `S_PCT`: 0.25 %, 0.35 %, 0.50 % of entry price (0.50 % = production `OPEN_STOP_PCT`)
  * `S_STRUCT`: structural invalidation level ± buffer (breakout/retest level for E; lower/upper CPR for C) with buffer ∈ {0.05 %, 10 pts}
  * `S_ATR`: 1.0 × ATR(14) of 5-minute ranges from the **prior** session, beyond the structural level (no look-ahead)
* **Target** candidates: 0.5 R, 1.0 R, 1.5 R, 2.0 R, and structural target (next level: R1/R2/S1/S2/pd_high/pd_low as applicable).
* **Time exits**: 13:30, 14:00, 14:30, and EOD (flat at the **15:20 open**, production convention). If the cutoff bar is missing, exit at the last available bar's close and flag `EXIT_BAR_MISSING` (sensitivity: drop the session instead).
* **Conservative intrabar ordering**: if a single 5-minute bar contains both the stop and the target price, the **STOP is assumed to be hit first** (worst case). If a bar **opens** beyond the stop, the fill is the **open** (gap-through, worse than the stop price) — no stop price improvement is ever assumed.
* **R** = `dir × (exit − entry) / stop_distance`. Points = `dir × (exit − entry)`. MFE/MAE in R from bar extremes.
* **Cost sensitivity (proxy only)**: a round-trip cost of `c ∈ {0.00, 0.05, 0.10, 0.15, 0.20} R` is deducted from R for robustness. This is a **proxy for option-spread friction**, not a measured option cost; at c = 0 the results are pure index moves. The production convention (0.10 R) is included for comparability with `research/cpr_reversal_breakout`.

## 5. Splits (chronological, pre-declared; actual verified coverage)

| split | range | complete sessions |
|---|---|---|
| **IS (train)** | 2026-07-06 … 2026-08-31 | 41 |
| **VAL** | 2026-09-01 … 2026-09-30 | 21 |
| **OOS (test)** | 2026-10-01 … 2026-10-21 | 13 (2 expiry Tuesdays: 10-06, 10-13) |
| **WFA** | 6 chronological blocks (13 sessions each) over 2026-07-06 … 2026-10-21 | 75 |

Expiry-day sessions (NIFTY weekly expiry = Tuesday) are reported separately.

## 6. Freeze protocol (anti-overfitting)

1. This spec, the model list, the parameter grid and the acceptance criteria are **frozen before execution**; the file's SHA-256 is recorded in `outputs/run_manifest.json`.
2. **Selection is performed on IS+VAL only**, by this declared rule: among the candidate (model, stop, target, time-exit) configurations, keep those with (i) positive expectancy in **both** IS and VAL, (ii) ≥ 20 trades in IS+VAL, (iii) max drawdown ≤ 3.0 R on IS+VAL, (iv) no single loss worse than −1.2 R; then take the **highest IS+VAL expectancy per trade**; ties → lowest max DD → widest stop → lexicographic. The winner is written to `outputs/frozen_selection.json` with the SHA-256 of the selection inputs.
3. The **OOS evaluation of the frozen configuration is the confirmatory result.** Every other configuration's OOS numbers are reported for transparency and are explicitly labelled **exploratory**; the "best-of-N" OOS expectancy across all tested configurations is reported alongside the frozen one to quantify selection bias.
4. A session-level **paired block bootstrap** (block = 5 consecutive sessions, 4 000 resamples, seed 20261022) supplies uncertainty on expectancy for IS+VAL and OOS.
5. No parameter may be revised after seeing OOS. Any change requires a new spec version and a fresh freeze.

## 7. Metrics (per model / direction / stop / target)

Eligible sessions · signals · executed trades · NO TRADE count and reason histogram · bullish vs bearish counts · win rate with Wilson 95 % CI · mean/median net P&L (points and R) · mean win · mean loss · profit factor · expectancy per trade (points, R) · cumulative curve · max drawdown (R and points) and its duration · max consecutive losses · stop-hit rate · target-hit rate · time-exit rate · mean/median holding time (bars and minutes) · MFE/MAE in R · proxy-cost contribution · worst single trade · % of total profit from the best trade · results by gap cell, by previous-day close class, by CPR class, by opening position, by continuation vs reversal, by entry method, by entry time-of-day, and by split.

## 8. Acceptance criteria (pre-declared) — all must hold for "validated"

1. **PIT integrity**: unit tests pass; a point-in-time recomputation of every session's features from a truncated feed reproduces the live-computed features exactly.
2. **Data quality clean**: no missing session days, no OHLC violations, all sessions complete or flagged.
3. **OOS expectancy > 0** in points and R, with the block-bootstrap p-value ≤ 0.10.
4. **Sample sufficiency**: ≥ 8 OOS trades, ≥ 3 in each direction, ≥ 2 distinct weeks.
5. **Robustness**: ≥ 2 of 3 splits positive; ≥ 4 of 6 walk-forward blocks positive; ≥ 70 % of the immediate parameter neighbours keep a positive IS+VAL expectancy.
6. **Risk shape**: max DD ≤ 3.0 R on IS+VAL; no single loss worse than −1.2 R; daily loss (in R) breaches of the 3R-equivalent flagged and reported.
7. **Concentration**: the best single trade contributes ≤ 40 % of total OOS profit, and expectancy stays positive with the best trade removed.
8. **Cost robustness**: OOS expectancy still > 0 at the 0.10 R proxy cost.
9. **Clear NO TRADE mechanism**: every NO TRADE carries a reason code from a closed taxonomy, and NO TRADE sessions are reported per model.
10. **Directional transparency**: bullish and bearish results are reported separately for the frozen configuration.

If any criterion fails, the conclusion is **NOT VALIDATED** — stated as such, with the failing criteria listed.

## 9. Deliverables (all inside `research/prevday_cpr_spread_study/`)

`spec.md` (this file) · `README.md` (reproduction) · `outputs/data_quality_report.{json,md}` · `outputs/feature_table_NIFTY.csv` · `outputs/signal_ledger.csv` (one row per signal **and** per NO TRADE session with reason) · `outputs/trade_ledger.csv` · `outputs/model_comparison.{json,md}` · `outputs/stop_target_matrix.csv` · `outputs/walkforward_results.json` · `outputs/bootstrap_ci.json` · `outputs/frozen_selection.json` · `outputs/gates.json` · `outputs/run_manifest.json` · `outputs/pytest.xml` · `reports/`: `backtest_report.md`, `model_comparison.md`, `stop_target_analysis.md`, `signal_decision_table.md`, `signal_schema.md`, `final_recommendation.md`.

## 10. Explicit non-goals / prohibitions

No production code, config, alert, API, DB schema, job or service is modified. No live signal is emitted. No option premium is invented. No external data is fetched. No dependency is installed. No commit, deploy or restart. The production DB is read via a **snapshot copy**; the study never opens the production DB for writing.
