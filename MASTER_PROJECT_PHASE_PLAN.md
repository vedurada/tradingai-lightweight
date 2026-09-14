# TradingAI.in — Master Project Phase Plan

(Canonical lifecycle: original build → current Phase 7 Track A. All cited freeze
commits verified present in this repository. Doc-only.)

## Project objective

TradingAI.in is an India-focused AI-Assisted Market Intelligence Platform for options traders, built around:

NIFTY / BANKNIFTY / SENSEX and other market instruments
live and historical market data
technical indicators
market regime classification
options intelligence
deterministic strategy selection
AI-generated explanations
backtesting
market/outlook pages
educational content
portfolio/P&L functionality
production monitoring and self-healing
AdSense/SEO readiness

The fundamental architecture is:

                    MARKET DATA
                        │
              ┌─────────┴─────────┐
              │                   │
          NSE / APIs          Yahoo fallback
              │                   │
              └─────────┬─────────┘
                        ↓
                 DATA / DATABASE
                        ↓
                  INDICATORS
                        ↓
                 REGIME ENGINE
                        ↓
                MARKET REGIME
                        ↓
                STRATEGY ENGINE
                        ↓
              OPTIONS INTELLIGENCE
                        ↓
                  API LAYER
                        ↓
                     UI
                        │
                        ↓
                 USER EXPERIENCE

              LLM / AI EXPLANATION
                        ↑
              deterministic outputs only

The governing rule is:

Server decides. LLM explains. UI displays.

## PHASE 1 — Foundation, Layout & Initial Product

Objective: create the lightweight foundation without unnecessary infrastructure complexity.

Technology direction: Static HTML + CSS / JavaScript + Python + Flask + SQLite.
Explicitly avoiding: Docker, Node-heavy architecture, PostgreSQL, complicated cloud infrastructure.

The original project began as a lightweight static HTML + Python + SQLite application.
Initial commit: `7c4c088`. Early work: initial static site, HTML structure, Python data
processing, SQLite, market pages, navigation, basic market data, strategy concepts.

Major early evolution `b7aad05` introduced the early free LLM/Mistral direction. Later the
project deliberately moved away from depending on external LLMs for quantitative decisions.

Phase 1 principle: the site should be fast, lightweight, understandable, deployable on a
single VM. Output: a functioning lightweight TradingAI website foundation.

## PHASE 2 — Product Audit, Architecture Cleanup & Foundation Stabilization

Objective: audit the initial implementation and remove structural problems before adding
sophisticated intelligence. Primary audit: `PHASE2_AUDIT.md`.

The project evolved toward: independent HTML pages, common visual language, API-driven
market data, better timestamps, option expiry handling, NIFTY/BANKNIFTY support, strategy
presentation, data generation, deployment improvements (`a0b8c02`, `6623f07`, `40bf528`, `40442db`).

Key architectural transition `c5574e3`: database-first architecture with Flask API,
comprehensive data fetcher and layered data pipeline, followed by `17b4830` for database
initialization/deployment.

Phase 2 output: the project became Frontend → Flask API → SQLite → Data Fetcher.

## PHASE 3 — Market Intelligence Product Integration

Objective: connect the frontend to deterministic market intelligence. Key milestone: `7cd3813`
(homepage connected to API, market outlook, regime/strategy/AI outlook/index intelligence;
earlier combined rework `803ded2`).

Product expansion: NIFTY, BANKNIFTY, SENSEX, scanner, strategies, market, history, P&L,
stock analysis, stock options, learning pages, position sizing, strategy builder, P&L system.
Introduced `83ad943` (9:30 entry, 3:20 exit, WIN/LOSS, P&L history) and direction-aware
calculations `fe54e7a`. Production/self-healing foundations `7438b93`, `9294b81` (VM backup,
restore runbook, self-healing API, watchdog, deployment recovery). UI iterations: Strategy
Intelligence hub, live IST clock, consistent navigation, light theme, hero cards, ticker,
modern cards (`9fc60b7`, `a56d2f8`, `97f8f79`, `a1aabaf4`, `8a768e6`).

Data architecture: NSE-first quotes + Yahoo fallback (`763d01e`, `d7053cd`) with a formal
data catalog. Current data rule: NSE first, yfinance fallback, never empty where a truthful
fallback exists; otherwise UNAVAILABLE rather than invented.

## PHASE 4 — Options Intelligence (frozen at `cf851b4`)

Step 1 Max Pain correction `86ab776` (aggregate intrinsic payout methodology).
Step 2 OI concentration/changes `6a00c17` (source-aware).
Step 3 Expected move `db6cd21` (ATM IV × sqrt(DTE/365) × Spot).
Step 4 Market ↔ Options confirmation `e08c3b5`.
Step 5 Options UI `9b6255c` (`/api/options-intelligence/<symbol>`).
Step 6 endpoint correction `cf851b4`.

Phase 4 rule: options calculations centralized and reused; no duplicates across UI/API/LLM.

## PHASE 5 — Analytical Integrity & Model Architecture

- STEP 1 Cleanup `a7d19aa`: dead code, duplicate Max Pain, dead tables/paths/tests.
- STEP 2 Canonical Regime Engine `c615235`: BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY from
  trend/momentum/VIX/breadth/options-confirmation; VIX ≥ 20 → HIGH_VOLATILITY; PCR is
  confirmation not authority; deterministic; UNKNOWN never guessed into a direction.
- STEP 3 Regime Integration `61bd3bf`: regimes through strategies/scenarios/AI outlook/alerts/API.
  BULLISH → bullish, BEARISH → bearish, SIDEWAYS → neutral/iron condor, UNKNOWN → NO TRADE.
- STEP 4A LLM Boundary `c67f288`: LLM explains (narrative/interpretation), never overrides
  regime/bias/confidence/levels/verdict/strategy. STEP 4B chat/alert `a038af1`. STEP 4C pipeline tests `5fdba17`.
- STEP 5 Confidence & Decision Consistency `45f90fc` → **analytical baseline** 🔒:
  RegimeEngine owns regime confidence; Outlook owns final confidence; StrategyEngine is
  strategy authority; scenarios normalize to 1.00; legacy aliases normalized.
- STEP 6 Historical Validation (read-only, `PHASE5_STEP6_PREDICTIVE_INTEGRITY_AUDIT.md`):
  integrity/effectiveness PASS; predictive power/calibration CONDITIONAL PASS.
  Conclusion: identifies current regime; that is not future-direction prediction.
- STEP 7 Predictive Architecture Review (`PHASE5_STEP7_PREDICTIVE_ARCHITECTURE_REVIEW.md`):
  confidence inversely calibrated (agreement ≠ correctness); do not tune blindly.
  Positioning: AI-Assisted Market Intelligence, not aggressive prediction.

PHASE 5 RESULT: 🔒 frozen at `45f90fc`.

## PHASE 6 — Productization & Production Hardening

Initial audit `PHASE6_PRODUCTIZATION_AUDIT.md`: 6.5/10 (confidence interpretation,
monitoring, WAIT/NO TRADE, API reliability, options UX, operations).

- **6A** User-Facing Hardening `51c02f9` 🔒: Signal Confidence ("not probability"), WAIT/NO
  TRADE risk messaging, stale detection, health monitoring. 194/194 tests.
- **6B** Production Hardening audit (`PHASE6B_PRODUCTION_HARDENING_AUDIT.md`): 61 findings.
  - **6B-1** Reliability & DB `63ab095` 🔒: WAL, timeouts, leak prevention, partial-data policy,
    circuit breaker, retry/backoff, unified errors. 220 tests.
  - **6B-2** Abuse Protection & API Security `8bbd4d7` 🔒: rate limiting, size/timeout limits,
    CORS, portfolio validation + auth boundary. 261 tests, 10/10 gates.
  - **6B-3 Phase A** Observability `c39af34` 🔒: latency metrics, failure counters, structured
    logging, correlation IDs, metrics endpoint, alerts. 298/298.
  - **B.1** CI/CD `3ec9473` 🔒: regression gates, commit/PR validation, deploy safety
    (staging operationally deferred).
  - **B.2** Authentication & Security `cdf0f6a` 🔒: portfolio API keys (hashed), user isolation,
    SQL guards, error handling, debug enforcement, nginx cache protection. 350/350.
  - **B.3** Failure Recovery `6596cc7` 🔒: degradation, isolation, DB recovery, stale
    communication, startup verification, shutdown, rollback. 385/385.
  - **B.4** Performance & DB `d4990e4` 🔒 (impl `4cd896a`, fixes `801a5c1`, `8f46b74`, `9a512a4`):
    pooling, caching, async backtest, market perf, pagination, DB optimization, timeout/queue,
    concurrency. 60.9% avg improvement (15/15 endpoints). 421/421.
  - **B.5** Observability & Resilience `4b7260f` 🔒 (impl `f19a010` + VM fixes, record `d629b3d`):
    deep health, freshness validation, process supervisor, deploy logging, crontab/self-heal,
    backup verification, live VM validation. 446/446, `all_healthy: true`, public 200.
  - **B.6** Reliability Core `8c9faff` 🔒: thread-safe timeouts, breaker wiring, scheduled
    cleanup, conn-close hardening, sql_guard coverage, backup verification, unified data
    status, central alert config, live/ready split. 469/469 local + VM.

## PHASE 6 — Production Rebuild (validated, `b3bc5cf`)

Rebuilt from Git (not in-place upgrade): GitHub → fresh clone → fresh dependencies → DB
init → production DB restore (17,372 daily rows) → secrets → systemd → nginx → health gate.
469/469, deep health `all_healthy: true`, public HTTP 200, safety copies preserved.
Deployment record `163f4e5` (documentation-only).

## PHASE 7 — Trust & Product Readiness (authorized)

Audit: `PHASE7_SCOPE_REVIEW.md`. Five genuine risks: R1 nginx header inheritance, R2 chat
alert spoofing, R3 no HSTS, R4 silent stale data, R5 options-intelligence correctness
(default bias → except:pass → CONFIRMED/DIVERGENCE — most user-harmful finding).

Tracks (independently shippable, sequential review → freeze):
- **Track A — Security** (authorized; spec `PHASE7_TRACK_A_SPECIFICATION.md`): A1 header
  snippet, A2 Bearer-gated alert/system kinds, A3 HSTS + server_tokens off (no CSP),
  A4 metrics lockdown, A5 CORS + prod origins, A6 key CLI/runbook. Target ≈483 tests + VM validation.
- **Track B — Product Readiness** (⏸️ waiting Track A freeze): AdSense unblock, sitemap/IndexNow,
  OG/dates/slugs, STALE banner + as-of + max-age cutoff, publisher identity.
- **Track C — Intelligence Reliability** (⏸️ waiting Track B freeze): R5 default-bias fix first;
  missing/invalid bias → UNKNOWN/UNAVAILABLE, never CONFIRMED/DIVERGENCE. May touch
  `options.py`/presentation; RegimeEngine/StrategyEngine/confidence/thresholds/backtest frozen.

## Master governance model

AUDIT → SCOPE REVIEW → APPROVAL → SPECIFICATION → AUTHORIZATION → IMPLEMENTATION →
TESTS → INDEPENDENT REVIEW → FREEZE → DEPLOYMENT → VM VALIDATION → DOCUMENTATION → STOP.

Immutable analytical boundary: RegimeEngine, StrategyEngine, confidence mathematics, regime
thresholds, backtest methodology, analytical output semantics frozen. LLM EXPLAINS, never
DECIDES. UI DISPLAYS, never calculates authoritative signals. Data: every displayed number's
origin documented; unavailable data distinguished from invented values.

## Current status

| Phase | State |
|---|---|
| 1 Foundation | ✅ |
| 2 Architecture | ✅ |
| 3 Market intelligence | ✅ |
| 4 Options Intelligence | 🔒 |
| 5 Analytical integrity | 🔒 `45f90fc` |
| 6A Productization | 🔒 `51c02f9` |
| 6B-1 Reliability | 🔒 `63ab095` |
| 6B-2 Security | 🔒 `8bbd4d7` |
| 6B-3 A Observability | 🔒 `c39af34` |
| 6B-3 B.1 CI/CD | 🔒 `3ec9473` |
| 6B-3 B.2 Auth/security | 🔒 `cdf0f6a` |
| 6B-3 B.3 Failure recovery | 🔒 `6596cc7` |
| 6B-3 B.4 Performance/DB | 🔒 `d4990e4` |
| 6B-3 B.5 Operational resilience | 🔒 `4b7260f` |
| 6B-3 B.6 Reliability Core | 🔒 `8c9faff` |
| Production rebuild | ✅ `b3bc5cf` |
| 7 Trust & Product | 🟢 authorized |
| Track A Security | 🟢 authorized / implementation stage |
| Track B Product | ⏸️ waiting |
| Track C Intelligence | ⏸️ waiting |

Strategic endpoint: four generations (static site → API+DB platform → deterministic
intelligence → production-grade AI-Assisted Market Intelligence). Next objective is not more
features: make existing intelligence trustworthy, secure, transparent, monetizable and
operationally dependable. Hence A → B → C.
