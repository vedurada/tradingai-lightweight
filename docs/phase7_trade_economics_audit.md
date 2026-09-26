# Phase 7 — Trade Economics & R-Multiple Sanity Audit

**Verdict: the Phase 6 R values were a unit bug (50× inflation). Win rates were genuine arithmetic, explained by model mechanics + sample. Four genuine accounting bugs fixed; strategy rules untouched.**

## A. Executive summary (direct answers)

1. **R formula correct?** NO (was) → YES (now). `R = rupee-PnL / point-risk` inflated every R by the 50× lot multiplier (measured engine/true ratio 49.7–50.0 on all 78 trades). Now points/points.
2. **Risk denominator correct?** YES — NIFTY 231–245 pts, BANKNIFTY 555–576 pts (~1% of price). No tiny-denominator inflation. Minimum > 0 on all trades.
3. **Why so large?** B1 (50× units) × EOD exits capturing full-session drift ÷ 1% risk. Corrected avg R: NIFTY 0.48, BANKNIFTY 0.53.
4. **Entry/stop/target point-in-time?** YES — verified exact on all trades: `entry=round(sig_close×0.995,2)`, `stop=round(entry×0.99,2)`, `target=round(entry×1.02,2)`; theoretical R:R exactly 2.000. Uses only the signal candle's own close.
5. **Any look-ahead?** None in signal/entry/stop/target/exit/regime math (mutation tests prove future changes can't move levels). One staleness limitation: the trade/no-trade gate reads the single globally-latest scenario candidate (constant CONFIRMED BREAKOUT), so the backtest measures entry/risk/exit mechanics, not scenario-timing skill. Documented, engine unchanged (redesign = out of scope).
6. **Scenario selection point-in-time?** Construction is (per-candle features, status never uses future outcomes — audited in `generate_historical_scenarios.py`). Every eligible candle is evaluated; `measure_outcomes` futures are stored as analysis only.
7. **One-trade/day unbiased?** YES — first qualifying signal by timestamp; replay test proves entry == first qualifying candle. No outcome-based picking (levels don't even know the future).
8. **EOD explains result?** YES — 38/39 + 37/39 exits are EOD; corrected R ≈ session-drift ÷ 1% risk (≈0.5 avg).
9. **Outlier-driven?** NO — removing top-5 keeps total R positive (NIFTY 18.70→13.19, BANKNIFTY 20.77→13.06).
10. **Phase 6 official results changed?** R/MFE/MAE/holding yes (bugfix); win counts essentially identical (37/2, 36/3 FULL). Phase 6 numbers retained in `phase6_*.json` + table below.
11. **Bugs:** B1 R units, B2 TARGET favorable fill, B3 MFE/MAE price-levels, B4 risk-gate eps. All fixed + tested.
12. **Unvalidated:** options execution, net costs, regimes outside Q3-2026, scenario-timing skill, live fill achievability (entry 0.5% below signal close is below the candle low — a model assumption, flagged).

## B. Formula audit

- Before: `R = ((exit−entry)×50) / |entry−stop|` = 50 × true R.
- After: LONG `(exit−entry)/|entry−stop|`, SHORT `(entry−exit)/|entry−stop|` (points/points). `paper_pnl` rupees retained as informational only.
- `win_rate = round(wins/completed, 4)` — verified exact.
- Holding = `exit_time − entry_time` — verified per trade; now flat 370.0 min NIFTY (09:15→15:25), explaining Phase 6's ~363 (B4 scattered entries 09:15–09:45).
- MFE/MAE now favorable/adverse excursions in points (≥0); consistency holds (MFE ≥ realized favorable move on all trades).

## C. Corrected results (official) vs Phase 6

| | Phase 6 (buggy R) | Corrected FULL |
|---|---|---|
| NIFTY | 39 trades, 37W/2L, 94.9%, avgR 24.55, totR 957.56, 39 EOD | 39 trades, 37W/2L, 94.9%, avgR 0.4795, medR 0.56, totR 18.70; 38 EOD + 1 STOP (−1.13R) |
| BANKNIFTY | 39 trades, 36W/3L, 92.3%, avgR 26.90, totR 1049.18, 38 EOD + 1 TGT | 39 trades, 36W/3L, 92.3%, avgR 0.5326, medR 0.45, totR 20.77; 37 EOD + 1 TARGET (exactly 2.00R ✓) + 1 STOP (−1.03R) |

Win counts identical because /50 preserves sign; two sub-period flips (NIFTY 90D +1 STOP, BANKNIFTY 30D/7D ±1 win) come from B4 moving entries to 09:15. Max 1/day, 0 lookahead violations throughout.

## D. R distribution (FULL, corrected)

- NIFTY: min −1.13, p10 0.14, p25 0.32, med 0.56, p75 0.645, p90 0.882, max 1.50, sd 0.41; 37+/2−/0 zero.
- BANKNIFTY: min −1.03, p10 0.026, p25 0.235, med 0.45, p75 0.77, p90 1.13, max 2.00, sd 0.54; 36+/3−/0 zero.
- No outliers removed or adjusted. Full trade tables: `data/generated/phase7_trade_audit.json`.

## E–G. Outliers / MFE-MAE / holding

- Top trades are ordinary EOD drift days (NIFTY 2026-08-03 EOD +1.50R); bottoms are the STOP days (−1.1R/−1.0R, i.e. stops work) plus flat EOD days ≈0R.
- Avg MFE 181 pts vs MAE 11 pts (NIFTY); 496 vs 38 (BANKNIFTY) — consistent with LONG-only in a rising quarter, not with look-ahead (excursions recomputed independently from post-entry candles only).
- Holding now deterministic 370 min (all entries 09:15 after B4); the single 285-min trade is the TARGET exit.

## H–I. Scenario & selection audits

- Detection inputs: prior-session OHLC, session-anchored VWAP/opening ranges, 3-candle trend/momentum — all ≤ signal idx. Confirmation timestamp = signal candle. Future data excluded from status (only stored in evidence `outcomes`).
- Backtest evaluates every candle in window (2925 attempts/FULL); first-qualifying-signal selection proven by replay; scenario-table mutation test proves economics independent of scenario content.

## J. Limitations

39 sessions, Q3-2026 only · options NOT AVAILABLE · NET P&L not modeled · LONG-only sample (hardcoded BULLISH probe state) · entry-fill assumption (limit 0.5% under close) · scenario gate staleness (see A5) · EOD-almost-always exit profile at 1%/2% levels (descriptive, not tuned).

Validation: 74/74 tests (61 + 13 new) · isolation PASS (0/0/0) · APIs 200 · no optimization performed.
