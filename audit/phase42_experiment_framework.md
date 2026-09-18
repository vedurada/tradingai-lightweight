# Phase 42 — Experiment Framework

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Design controlled experiment framework for Phase 42 research

---

## Principle

Every experiment must define its hypothesis, variables, and acceptance criteria. Do not run dozens of random parameter combinations. Avoid multiple-testing/data-mining bias.

## Experiment Template

Every future experiment must define:

| Field | Description |
|-------|-------------|
| **Hypothesis** | Clear, testable statement |
| **Independent Variable** | What is being changed |
| **Dependent Variables** | What is being measured |
| **Dataset** | Which data is used |
| **Training Period** | Where parameters are discovered |
| **Validation Period** | Where parameters are confirmed |
| **Holdout Period** | Where performance is evaluated |
| **Transaction Costs** | Cost assumptions |
| **Slippage** | Slippage assumptions |
| **Evaluation Metrics** | How success is measured |
| **Acceptance Criteria** | What constitutes success |

## Controlled Baselines

### Baseline A: Phase 37 Deterministic EMA Crossover
- Pure EMA crossover signal
- No qualification engine
- Historical baseline reference point

### Baseline B: Phase 41 Qualification Engine
- Current frozen qualification engine
- Full 6-layer checklist
- Current production behavior

### Baseline C: Phase 41 with Proposed Setup/Re-entry Control
- Phase 41 + independent setup definition
- Phase 41 + re-entry cooldown (if tested)
- Research question: Does trade count reduction improve quality?

### Baseline D: Evidence-Only Without AI
- Qualification engine without AI outlook influence
- Deterministic evidence only
- Future comparison point for AI attribution

### Baseline E: Evidence + AI (Future)
- Full pipeline with AI outlook
- Requires sufficient historical AI data
- Future comparison point for AI attribution

## Experiment Design Rules

### Rule 1: One Variable At a Time
Each experiment changes exactly ONE thing from a baseline. This isolates cause and effect.

### Rule 2: Same Data, Same Period
All baselines compared on identical data and time periods.

### Rule 3: Same Cost Assumptions
All baselines evaluated with identical transaction costs and slippage.

### Rule 4: Same Metrics
All baselines evaluated with identical metrics (expectancy, PnL, PF, drawdown, etc.).

### Rule 5: Multiple Testing Correction
If testing N hypotheses, adjust significance threshold (Bonferroni or similar).

## Experiment Categories

### Category 1: Trade Frequency Research
- Question: Does reducing trade count improve quality?
- Independent: Setup persistence definition, re-entry cooldown
- Dependent: Expectancy, net PnL, drawdown
- NOT: "Reduce trades" — measure WHY

### Category 2: Directional Asymmetry Research
- Question: Why is BULLISH win rate 0.7%?
- Independent: Regime, time, market state, evidence alignment
- Dependent: BULLISH win rate breakdown
- NOT: "Fix BULLISH rules" — understand the cause first

### Category 3: Evidence Independence Research
- Question: Are evidence groups independent?
- Independent: Evidence group combinations
- Dependent: Win rate with different evidence subsets
- NOT: "Tune evidence weights" — understand correlation first

### Category 4: AI Attribution Research (Future)
- Question: Does AI add value?
- Independent: With/without AI outlook
- Dependent: All performance metrics
- Requires: Sufficient historical AI data

## NO-TRADE Value Metric

Design metrics to evaluate whether NO_TRADE decisions improve overall quality:

| Metric | Formula | Purpose |
|--------|---------|---------|
| NO_TRADE rate | NO_TRADE / Total signals | How often system says wait |
| NO_TRADE impact | WR_with_NO_TRADE vs WR_without | Does filtering help? |
| NO_TRADE quality | Win rate of remaining trades | Are remaining trades better? |

## NOT IMPLEMENTED IN PHASE 42

- No experiments will be run
- No parameter combinations will be tested
- No hypotheses will be evaluated
- This is framework documentation only
