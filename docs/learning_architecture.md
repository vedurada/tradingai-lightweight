"""Personal Trading Learning Architecture.

Two distinct learning systems:

A. TradingAI Market Intelligence
   Learns from: historical market data → regimes → setups → backtests →
               out-of-sample → forward/paper trading
   Purpose: Determine what market conditions suit strategies
   Caution: Must NOT auto-modify based on handful of user trades
   Evaluation: Untouched chronological data or paper results

B. User Personal Trading Intelligence
   Learns from: user's trades → decisions → outcomes → market conditions
               → mistakes → behavior patterns → personal statistics
   Purpose: Personalized coaching ("You perform better with credit spreads")
   Caution: No self-modifying model based on wins/losses (overfitting risk)
   Evaluation: Historical comparison only, never real-time strategy changes

Phase 1: Documents architecture and data boundaries.
Phase 2+: Will implement user-specific trade journal analysis.
Phase 3+: Will implement setup performance analysis and personal coaching.

Key distinction:
- Market intelligence serves ALL users with evidence-based patterns
- Personal intelligence serves ONE user with their own history
- Neither automatically changes trading rules based on recent results
"""

# Data tables needed (Phase 2+)
REQUIRED_TABLES = """
user_journal:
  - date, instrument, direction, entry, exit, quantity, SL, target, strategy
  - TradingAI setup used, reason, regime, confidence, result, mistake, notes

user_strategy_stats:
  - strategy_name, total_trades, win_rate, avg_r, best_regime, worst_regime
  - best_time, worst_time

user_behavior_stats:
  - repeated_mistakes, risk_adherence, time_patterns, entry_patterns

user_setup_performance:
  - setup_type, total_used, wins, losses, win_rate, avg_result

market_setup_history:
  - market_condition, setup_type, count, win_rate, avg_r

ai_prediction_outcomes:
  - prediction, actual_outcome, prediction_accuracy, strategy_outcome
"""

# Learning engine data flow
DATA_FLOW = """
TRADINGAI
    │
    ▼
Today's Outlook
    │
    ▼
Trade Setup
    │
├─────────┴─────────┐
▼                   ▼
User takes        User skips
trade
    │
    ▼
Trade Journal
    │
    ▼
Trade Outcome
    │
    ▼
Outcome Engine
    │
├───────────────┐
▼               ▼
Strategy      User Statistics
Statistics
│               │
└───────┬───────┘
        ▼
  Learning Engine
        │
┌───────┴───────┐
▼               ▼
Market        Personal Coach
Intelligence  (User improvement)
"""

# Safety rules (NEVER violate)
SAFETY_RULES = """
1. NEVER auto-change strategy rules based on recent wins/losses
2. NEVER optimize against same historical trades until out-of-sample
3. ALWAYS validate on untouched chronological data
4. ALWAYS use forward/paper results before accepting changes
5. NEVER confuse market intelligence with personal intelligence
6. ALWAYS separate TradingAI learning from user learning
7. NEVER expose one user's data to another user
8. ALWAYS maintain immutable audit trail for learning decisions
"""