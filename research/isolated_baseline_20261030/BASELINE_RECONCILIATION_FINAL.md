BASELINE RECONCILIATION FINAL — ISOLATED BASELINE
Phase: TradingAI — Reconcile Isolated Baseline Test Discrepancy
Host gate: PASS (webserver / Ubuntu 22.04.5 LTS / x86_64 / ubuntu / /opt/tradingai)
Workspace: /opt/tradingai/research/isolated_paper_safety_fix_20261030/

FINAL STATUS: BASELINE_PARTIAL

SUMMARY:
- Individual and combined results were reproduced.
- Discrepancy identified: 3 failures disappeared in combined run.
- Missing from combined: hlc::test_backtest_and_live_signal_parity; exit_atomicity::test_second_close_is_rejected_and_does_not_overwrite; exit_atomicity::test_concurrent_closes_yield_exactly_one_winner.
- Root cause of discrepancy NOT yet fully determined within this phase (ordering/shared-state/missing-module hypotheses remain).

STOP CONDITION:
- Do not begin the seven fixes.
