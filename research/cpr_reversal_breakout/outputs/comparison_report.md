# CPR reversal & breakout candidate - baseline vs candidate report

Generated: 2026-10-19T19:51:44.695051+05:30
Range: 2026-07-06 .. 2026-10-19  
Instruments: NIFTY, BANKNIFTY  
Primary candidate variant: **combined_parity** (pre-registered)  
Baseline: `app.research.cpr_trigger_engine.run_opens_range` variant `plain`

> Underlying (spot) signal study. This deployment holds no historical option premiums, so no credit-spread premium P&L is claimed anywhere; G7 (credit-spread economics) is evaluated separately.

## 1. Methodology

- **Baseline** = the production backtest function imported and called unmodified, read-only, against a SQLite `Connection.backup` snapshot.
- **Candidate** = research-only signal generator with the SAME entry rule (open of the candle after the trigger, inside [09:20,15:20)), the SAME exit walk (subsequent opens, stop before target, flat 15:20), the SAME lot sizes, costs and win/loss labelling.
- **Only signal selection differs.** Levels use production `calculate_cpr`/`pivot_levels` from the strictly prior session (point-in-time verified).
- Periods are chronological: in-sample 2026-07-06..2026-08-31, validation 2026-09-01..2026-09-30, out-of-sample 2026-10-01..2026-10-19.
- All parameters and all variants were registered in `strategy_config.json` before any result was produced.

## 2. Data coverage

- NIFTY: 74 sessions (2026-07-06 .. 2026-10-19); short sessions 2; missing session days 0; data on non-session days 0
- BANKNIFTY: 74 sessions (2026-07-06 .. 2026-10-19); short sessions 2; missing session days 0; data on non-session days 0
- option premiums: UNAVAILABLE -> this run is an UNDERLYING (spot) signal study only; credit-spread P&L cannot be claimed from these inputs
- data-quality status: **PASS_WITH_LIMITATIONS**
  - NIFTY: short sessions {'2026-09-21': 73, '2026-10-15': 73}
  - BANKNIFTY: short sessions {'2026-09-21': 73, '2026-10-15': 73}
  - point-in-time level check FAILED
  - NO historical option premiums -> credit-spread P&L test not executable (labelled limitation)

## 3. Baseline reproduction

### NIFTY
- reproduced trades: 64 over 74 sessions
- production summary: signals=64, win_rate=78.1%, total_R=26.86, net_R=20.46, skipped={'no_signal': 0, 'short_day': 0, 'missing_eod': 1, 'gate_missing': 0, 'bad_data': 1, 'skip_friday': 8, 'no_chase': 0}
- **journal cross-check**: 68 rows, 59 shared dates, 12 exact matches (rate 0.2034), 47 mismatches
- paper-book cross-check: {"paper_rows": 73, "shared_dates": 64, "exact_matches": 15, "match_rate_on_shared": 0.2344, "examples": [{"date": "2026-07-07", "paper_entry": 24460.2, "reproduced_entry": 24460.2, "paper_r": 0.446, "reproduced_r": 0.582}, {"date": "2026-07-08", "paper_entry": 24285.5, "reproduced_entry": 24285.5, "paper_r": 3.492, "reproduced_r": 3.15}, {"date": "2026-07-09", "paper_entry": 24065.3, "reproduced_e

### BANKNIFTY
- reproduced trades: 63 over 74 sessions
- production summary: signals=63, win_rate=73.0%, total_R=24.04, net_R=17.74, skipped={'no_signal': 0, 'short_day': 0, 'missing_eod': 1, 'gate_missing': 0, 'bad_data': 1, 'skip_friday': 9, 'no_chase': 0}
- **journal cross-check**: 68 rows, 58 shared dates, 14 exact matches (rate 0.2414), 44 mismatches
- paper-book cross-check: {"paper_rows": 73, "shared_dates": 63, "exact_matches": 16, "match_rate_on_shared": 0.254, "examples": [{"date": "2026-07-07", "paper_entry": 58446.5, "reproduced_entry": 58446.5, "paper_r": 0.74, "reproduced_r": 0.877}, {"date": "2026-07-09", "paper_entry": 57328.4, "reproduced_entry": 57328.4, "paper_r": -0.335, "reproduced_r": -0.189}, {"date": "2026-07-10", "paper_entry": 57735.35, "reproduced

> The journal covers 2026-07-07..2026-10-12 and predates the 2026-10-17 gates (SHORT_ONLY / SKIP_FRIDAY / BREAKOUT_ADDON). Where it disagrees, the reproduced baseline is the CURRENT production code, which is the correct comparison target.

## Comparison - FULL RANGE

| metric | baseline | candidate | diff |
|---|---:|---:|---:|
| total_trades | 127 | 132 | 5 |
| win_rate | 0.7559 | 0.6136 | -0.1423 |
| net_pnl_rs | 394884.5 | 38113.5 | -356771.0 |
| total_R | 50.896 | 7.986 | -42.91 |
| avg_net_per_trade_rs | 3109.33 | 288.74 | -2820.59 |
| avg_R_per_trade | 0.4008 | 0.0605 | -0.3403 |
| profit_factor | 3.12 | 1.124 | -1.996 |
| max_drawdown_rs | 26370.5 | 81112.75 | 54742.25 |
| max_drawdown_R | 3.07 | 9.15 | 6.08 |
| largest_loss_rs | -11206.0 | -11786.5 | -580.5 |
| max_consecutive_losses | 4 | 4 | 0 |
| return_on_capital_pct | 23.882 | 2.305 | -21.577 |
| expectancy_daily_rs | 3109.33 | 288.74 | -2820.59 |
| sessions_traded | 127 | 132 | 5 |
| reversal_trades | 115 | 22 | -93 |
| breakout_trades | 12 | 110 | 98 |

## Comparison - OUT-OF-SAMPLE

| metric | baseline | candidate | diff |
|---|---:|---:|---:|
| total_trades | 24 | 23 | -1 |
| win_rate | 0.7083 | 0.6957 | -0.0126 |
| net_pnl_rs | 92303.5 | 60870.75 | -31432.75 |
| total_R | 12.689 | 8.944 | -3.745 |
| avg_net_per_trade_rs | 3845.98 | 2646.55 | -1199.43 |
| avg_R_per_trade | 0.5287 | 0.3889 | -0.1398 |
| profit_factor | 2.91 | 2.068 | -0.842 |
| max_drawdown_rs | 20486.0 | 17296.75 | -3189.25 |
| max_drawdown_R | 2.44 | 2.0 | -0.44 |
| largest_loss_rs | -9823.0 | -10510.0 | -687.0 |
| max_consecutive_losses | 2 | 2 | 0 |
| return_on_capital_pct | 5.582 | 3.681 | -1.901 |
| expectancy_daily_rs | 3845.98 | 2646.55 | -1199.43 |
| sessions_traded | 24 | 23 | -1 |
| reversal_trades | 20 | 5 | -15 |
| breakout_trades | 4 | 18 | 14 |

## Comparison - VALIDATION

| metric | baseline | candidate | diff |
|---|---:|---:|---:|
| total_trades | 34 | 35 | 1 |
| win_rate | 0.7941 | 0.6 | -0.1941 |
| net_pnl_rs | 129220.5 | -38242.0 | -167462.5 |
| total_R | 16.489 | -4.413 | -20.902 |
| avg_net_per_trade_rs | 3800.6 | -1092.63 | -4893.23 |
| avg_R_per_trade | 0.485 | -0.1261 | -0.6111 |
| profit_factor | 4.2 | 0.613 | -3.587 |
| max_drawdown_rs | 17315.5 | 42815.5 | 25500.0 |
| max_drawdown_R | 2.08 | 5.01 | 2.93 |
| largest_loss_rs | -8716.0 | -8731.0 | -15.0 |
| max_consecutive_losses | 2 | 3 | 1 |
| return_on_capital_pct | 7.815 | -2.313 | -10.128 |
| expectancy_daily_rs | 3800.6 | -1092.63 | -4893.23 |
| sessions_traded | 34 | 35 | 1 |
| reversal_trades | 32 | 6 | -26 |
| breakout_trades | 2 | 29 | 27 |

## Comparison - IN-SAMPLE

| metric | baseline | candidate | diff |
|---|---:|---:|---:|
| total_trades | 69 | 74 | 5 |
| win_rate | 0.7536 | 0.5946 | -0.159 |
| net_pnl_rs | 173360.5 | 15484.75 | -157875.75 |
| total_R | 21.718 | 3.455 | -18.263 |
| avg_net_per_trade_rs | 2512.47 | 209.25 | -2303.22 |
| avg_R_per_trade | 0.3148 | 0.0467 | -0.2681 |
| profit_factor | 2.777 | 1.101 | -1.676 |
| max_drawdown_rs | 26370.5 | 29566.25 | 3195.75 |
| max_drawdown_R | 3.07 | 3.14 | 0.07 |
| largest_loss_rs | -11206.0 | -11786.5 | -580.5 |
| max_consecutive_losses | 4 | 4 | 0 |
| return_on_capital_pct | 10.484 | 0.936 | -9.548 |
| expectancy_daily_rs | 2512.47 | 209.25 | -2303.22 |
| sessions_traded | 69 | 74 | 5 |
| reversal_trades | 63 | 11 | -52 |
| breakout_trades | 6 | 63 | 57 |

## Per-instrument out-of-sample

### NIFTY

| metric | baseline | candidate | diff |
|---|---:|---:|---:|
| total_trades | 24 | 23 | -1 |
| win_rate | 0.7083 | 0.6957 | -0.0126 |
| net_pnl_rs | 92303.5 | 60870.75 | -31432.75 |
| total_R | 12.689 | 8.944 | -3.745 |
| profit_factor | 2.91 | 2.068 | -0.842 |
| max_drawdown_rs | 20486.0 | 17296.75 | -3189.25 |
| largest_loss_rs | -9823.0 | -10510.0 | -687.0 |

### BANKNIFTY

| metric | baseline | candidate | diff |
|---|---:|---:|---:|
| total_trades | 24 | 23 | -1 |
| win_rate | 0.7083 | 0.6957 | -0.0126 |
| net_pnl_rs | 92303.5 | 60870.75 | -31432.75 |
| total_R | 12.689 | 8.944 | -3.745 |
| profit_factor | 2.91 | 2.068 | -0.842 |
| max_drawdown_rs | 20486.0 | 17296.75 | -3189.25 |
| largest_loss_rs | -9823.0 | -10510.0 | -687.0 |

## All candidate variants (full range, pooled)

| variant | role | trades | win% | net Rs | net R | PF | maxDD Rs | OOS net Rs | OOS trades |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **baseline** | - | 127 | 75.6 | 394884.5 | 50.896 | 3.12 | 26370.5 | 92303.5 | 24 |
| reversal_A4 | level_family | 25 | 76.0 | 81454.0 | 10.404 | 3.865 | 16898.75 | 27774.25 | 7 |
| reversal_only | ablation | 121 | 62.8 | 68537.5 | 11.418 | 1.232 | 71528.0 | 18555.25 | 22 |
| reversal_A3 | level_family | 37 | 78.4 | 57196.0 | 7.642 | 2.303 | 18272.5 | -1495.75 | 7 |
| combined_structure | secondary | 131 | 76.3 | 52000.25 | 140.695 | 1.354 | 46764.0 | 50884.75 | 23 |
| combined_retest | secondary | 132 | 62.1 | 46105.5 | 8.924 | 1.151 | 80686.75 | 68436.75 | 23 |
| reversal_A1 | level_family | 29 | 72.4 | 45996.0 | 6.001 | 2.131 | 12661.5 | 2619.5 | 6 |
| combined_parity | PRIMARY | 132 | 61.4 | 38113.5 | 7.986 | 1.124 | 81112.75 | 60870.75 | 23 |
| combined_trigger_close | threshold_sensitivity | 131 | 61.8 | 29986.25 | 7.036 | 1.096 | 85790.25 | 57704.25 | 23 |
| reversal_B2 | level_family | 22 | 77.3 | 18583.75 | 3.369 | 1.429 | 15166.5 | 0 | 0 |
| breakout_dn | level_family | 69 | 68.1 | 9979.5 | 3.194 | 1.065 | 31811.0 | 8663.5 | 8 |
| reversal_B4 | level_family | 36 | 58.3 | 6765.5 | 1.58 | 1.086 | 43545.5 | 19785.75 | 6 |
| reversal_A2 | level_family | 12 | 75.0 | 4383.0 | 0.86 | 1.17 | 18896.25 | 6685.0 | 2 |
| combined_shadow_400 | threshold_sensitivity | 132 | 60.6 | -1411.0 | 3.263 | 0.996 | 82006.5 | 41529.25 | 23 |
| combined_shadow_000 | threshold_sensitivity | 136 | 60.3 | -6946.75 | 2.451 | 0.979 | 93086.25 | 42095.5 | 24 |
| breakout_retest | ablation | 110 | 61.8 | -16867.5 | 0.994 | 0.938 | 93491.25 | 49709.5 | 18 |
| combined_conflict_reject | ablation | 125 | 60.0 | -20933.0 | 0.725 | 0.931 | 87737.5 | 30624.75 | 20 |
| breakout_only | ablation | 110 | 60.9 | -24859.5 | 0.056 | 0.909 | 93917.25 | 42143.5 | 18 |
| reversal_B3 | level_family | 39 | 64.1 | -33856.75 | -3.061 | 0.696 | 81815.0 | 19754.5 | 7 |
| breakout_up | level_family | 55 | 54.5 | -43960.5 | -3.545 | 0.711 | 73854.75 | 20386.0 | 13 |
| reversal_B1 | level_family | 37 | 48.6 | -104903.0 | -11.807 | 0.226 | 97467.75 | -30769.25 | 5 |

### Most / least successful variants

- best OOS net: **combined_retest** (68436.75 Rs, 23 trades)
- worst OOS net: **reversal_B1** (-30769.25 Rs)
- primary (pre-registered) variant: combined_parity -> OOS net 60870.75 Rs

## Rejection counters & session buckets (primary variant)

### Rejected by filter

- duplicate_suppressed: 214
- no_confirmation: 12
- rejected_conflict: 0
- rejected_entry_window: 6
- rejected_failed_break: 103
- rejected_no_trigger: 14
- rejected_reward_filter: 34
- rejected_short_day: 0

### Sessions

- invalid_stop: 0
- missing_eod: 2
- no_levels: 2
- no_signal: 12
- short_day: 0

### Baseline skip buckets

- NIFTY: {'no_signal': 0, 'short_day': 0, 'missing_eod': 1, 'gate_missing': 0, 'bad_data': 1, 'skip_friday': 8, 'no_chase': 0}
- BANKNIFTY: {'no_signal': 0, 'short_day': 0, 'missing_eod': 1, 'gate_missing': 0, 'bad_data': 1, 'skip_friday': 9, 'no_chase': 0}

## Walk-forward blocks

| block | sessions | baseline net R | primary net R | baseline net Rs | primary net Rs |
|---|---:|---:|---:|---:|---:|
| 1 (2026-07-06..2026-07-21) | 24 | 13.294 | 3.151 | 110774.5 | 18818.75 |
| 2 (2026-07-22..2026-08-06) | 24 | 3.662 | 1.955 | 29007.0 | 12971.75 |
| 3 (2026-08-07..2026-08-24) | 24 | 3.231 | 0.742 | 21293.5 | 3840.5 |
| 4 (2026-08-25..2026-09-09) | 24 | 6.046 | -4.009 | 48473.5 | -34896.75 |
| 5 (2026-09-10..2026-09-28) | 24 | 12.199 | -3.394 | 96544.5 | -29095.75 |
| 6 (2026-09-29..2026-10-19) | 28 | 12.464 | 9.541 | 88791.5 | 66475.0 |

### Expanding selection track

| block | selection data | selected | selected net R | baseline net R |
|---|---|---|---:|---:|
| 1 | none | combined_parity | 3.151 | 13.294 |
| 2 | all prior blocks | combined_structure | -2.092 | 3.662 |
| 3 | all prior blocks | combined_structure | 8.586 | 3.231 |
| 4 | all prior blocks | combined_structure | -1.916 | 6.046 |
| 5 | all prior blocks | combined_structure | 23.429 | 12.199 |
| 6 | all prior blocks | combined_structure | 68.845 | 12.464 |

## Gates

| gate | status | detail |
|---|---|---|
| G1_oos_expectancy | **FAIL** | `{"definition": "candidate OOS net expectancy per trade > baseline OOS net expectancy per trade", "baseline_oos_avg_net_rs": 3845.98, "candidate_oos_avg_net_rs": 2646.55, "baseline_oos_trades": 24, "candidate_oos_trades": 23}` |
| G2_survives_costs | **FAIL** | `{"definition": "candidate advantage still > 0 on the reported cost grid (at least at the production 0.10R cost)", "oos_net_R_by_cost": {"baseline": {"0.00R": 12.69, "0.10R": 10.29, "0.20R": 7.89, "0.30R": 5.49}, "candidate": {"0.00R": 8.94, "0.10R": 6.64, "0.20R": 4.34, "0.30R": 2.04}}, "beats_baseline_at_0.10R": false, "never_worse_any_c` |
| G3_drawdown_within_limits | **FAIL** | `{"definition": "G3a max drawdown <= max_drawdown_pct_of_capital; G3b <= 1.5x baseline; G3c largest single loss <= max_single_loss_pct_of_capital", "candidate_max_dd_rs": 81112.75, "candidate_dd_pct_capital": 4.91, "limit_dd_pct_capital": 20.0, "baseline_max_dd_rs": 26370.5, "ratio_vs_baseline": 3.076, "ratio_effective_limit_rs": 39555.75,` |
| G4_trade_quality | **PASS** | `{"definition": "profit factor >= 1.0 (total and OOS)", "profit_factor_total": 1.124, "profit_factor_oos": 2.068, "oos_trades_total": 23, "oos_trades_by_instrument": {"NIFTY": 23, "BANKNIFTY": 23}, "min_oos_trades_total": 15, "min_oos_trades_per_instrument": 5, "sample_sufficient": true}` |
| G5_no_bias | **FAIL** | `{"definition": "unit tests + data-quality + PIT/look-ahead tests all PASS and the cost/execution model is identical", "tests_total": 33, "tests_failed": 0, "failed_tests": [], "pit_levels_pass": false, "structure_clean": true, "identical_execution_cost_model": true}` |
| G6_robustness | **PASS** | `{"definition": "net expectancy positive in >= 2 of 3 periods and >= 2 of 3 walk-forward blocks per instrument; both instruments not materially negative", "positive_periods": "2/3", "positive_walkforward_blocks": "4/6", "instruments_positive_oos": "2/2"}` |
| G7_credit_spread_economics | **BLOCKED** | `{"definition": "requires real historical option premiums; BLOCKED if option history is absent", "option_history_available": false, "note": "UNAVAILABLE -> this run is an UNDERLYING (spot) signal study only; credit-spread P&L cannot be claimed from these inputs"}` |

**FINAL DETERMINATION: FAIL** - any FAIL -> FAIL; else any BLOCKED/INCONCLUSIVE -> INCONCLUSIVE; else PASS (review only, never auto-deploy)

## Unit tests

- total 33, failed 0

## Production safety confirmation

- production files modified: none (see run_manifest.json checksums and git status)
- live engine / API / frontend / database schema / scheduled jobs / Telegram alerts: untouched
- no live trading cycle, no broker connection, no notifications: confirmed by design (read-only connections, no write paths called)

> A passing determination authorises **human review only**. It does not authorise deployment.
