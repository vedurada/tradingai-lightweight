# Phase 5.15 — Performance Impact of Expiry Policy

## Comparison

| Metric | Original (729) | With Expiry (723) | Change |
|--------|----------------|-------------------|--------|
| Trades | 729 | 723 | -6 (-0.8%) |
| Win rate | 72.43% | 72.20% | -0.23 pp |
| Total points | 19,210.95 | 17,857.91 | -1,353.04 (-7.0%) |
| Profit factor | 3.47 | 3.30 | -0.17 |
| Expectancy (R) | 0.794 | 0.792 | -0.002 |
| Max drawdown | 442.40 | 442.40 | 0 |

## Rejected Trades (6)

All 6 rejected trades were overnight carries (signal on day D, entry on day D+1). All 6 were winners (+1,353.04 points total). Removing them reduces total points by 7.0% but has minimal impact on win rate and expectancy.

## Out-of-Sample Impact

Test set (161 trades): UNCHANGED. No cross-session trades in the test period (Oct 6-29). All 161 trades accepted under expiry policy.

## Conclusion

The expiry policy has minimal impact on overall performance (-0.8% trades, -0.23 pp WR) but improves safety by preventing overnight signal carry. The out-of-sample results are unaffected.
