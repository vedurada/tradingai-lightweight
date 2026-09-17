# Phase 40 — Architecture Document

## 1. Overview

Phase 40 adds a deterministic **Market Evidence Engine** between the 5-minute market snapshot and the AI outlook interpreter. The architecture is:

```text
5-MINUTE CANDLE CLOSE
        ↓
MARKET SNAPSHOT (Phase 39)
        ↓
MARKET EVIDENCE ENGINE (Phase 40)
        ↓
DETERMINISTIC EVIDENCE (6 groups)
        ↓
AI OUTLOOK INTERPRETER (Phase 39/40)
        ↓
TRADE / WAIT / NO-TRADE (Strategy, separate)
```

## 2. Evidence Engine Module

### `backend/market_evidence_engine.py`

The `MarketEvidenceEngine` class transforms a 5-minute market snapshot into structured evidence.

### Constructor

```python
engine = MarketEvidenceEngine(config: dict = None)
```

Configurable thresholds (all documented, none optimized against datasets):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ema.fast` | 20 | Fast EMA period |
| `ema.slow` | 50 | Slow EMA period |
| `rsi.oversold` | 30 | RSI oversold threshold |
| `rsi.overbought` | 70 | RSI overbought threshold |
| `adx.trend_threshold` | 20 | ADX trend threshold |
| `adx.strong_threshold` | 30 | ADX strong trend threshold |
| `vwap.distance_pct` | 0.5 | Price/VWAP distance threshold |
| `volatility.high_vix` | 20 | VIX high threshold |
| `volatility.normal_vix` | 15 | VIX normal threshold |
| `atr.high_ratio` | 1.5 | ATR/close ratio for high volatility |
| `atr.normal_ratio` | 0.8 | ATR/close ratio for low volatility |

## 3. Evidence Groups (6)

### 3.1 Trend Evidence (`trend`)

**Available data**: EMA9, EMA20, EMA50, EMA200, VWAP, ADX, close price

**Rules**:
- `price_above_vwap` — close > VWAP + 0.5%
- `price_below_vwap` — close < VWAP - 0.5%
- `ema9_above_ema20` — fast EMA above slow EMA
- `ema9_below_ema20` — fast EMA below slow EMA
- `ema20_above_ema50` — mid-term trend confirmation
- `ema20_below_ema50` — mid-term trend reversal
- `close_above_ema200` — long-term trend alignment
- `close_below_ema200` — long-term trend alignment
- `adx_strong` — ADX > 30 (strong trend)
- `adx_trending` — ADX > 20 (trending)
- `adx_weak` — ADX < 20 (weak/range)

**Signals**: BULLISH, BEARISH, NEUTRAL, MIXED, UNAVAILABLE

**Key design**: RSI < 30 is NOT automatically bullish. RSI > 70 is NOT automatically bearish. Context from other groups matters.

### 3.2 Momentum Evidence (`momentum`)

**Available data**: RSI, MACD, MACD signal

**Rules**:
- `rsi_overbought` — RSI > 70 (bearish momentum, not auto-bullish)
- `rsi_oversold` — RSI < 30 (bearish momentum, flagged as context-dependent)
- `rsi_neutral` — RSI between 30-70
- `macd_above_signal` — MACD line above signal line (bullish momentum)
- `macd_below_signal` — MACD line below signal line (bearish momentum)

**Key design note**: RSI oversold in a strong downtrend may still be bearish momentum. The notes field preserves this distinction.

### 3.3 Structure Evidence (`structure`)

**Available data**: Previous day high/low/close, opening range, CPR, support/resistance levels

**Rules**:
- `above_prev_day_high` — breakout detection
- `below_prev_day_high` — below yesterday's high
- `above_prev_day_low` — above yesterday's low
- `below_prev_day_low` — breakdown detection
- `above_resistance` — resistance break
- `below_resistance` — resistance rejection
- `above_support` — support hold
- `below_support` — support break
- `above_cpr_upper` — CPR breakout
- `range_between_support_resistance` — range detection

**Key design**: Price between support and resistance → RANGE signal (when directional signals are weak).

### 3.4 Volatility Evidence (`volatility`)

**Available data**: VIX, ATR, intraday range

**Rules**:
- `vix_high` — VIX >= 20
- `vix_low` — VIX <= 15
- `vix_normal` — VIX between 15-20
- `atr_high` — ATR/close >= 1.5%
- `atr_low` — ATR/close <= 0.8%

**Signals**: HIGH_VOLATILITY, NORMAL, LOW_VOLATILITY

**Key design**: Volatility is DIRECTION-NEUTRAL. VIX measures fear, not direction. High VIX does not mean bullish or bearish.

### 3.5 Options Evidence (`options`)

**Available data**: PCR, Call OI, Put OI

**Rules**:
- `pcr_bullish` — PCR < 0.8 (call OI dominant)
- `pcr_bearish` — PCR > 1.2 (put OI dominant)
- `pcr_neutral` — PCR between 0.8-1.2
- `call_oi_dominant` — Call OI > Put OI
- `put_oi_dominant` — Put OI > Call OI

**Key design**: If no live option data → UNAVAILABLE, NOT inferred. AI explicitly knows options evidence is unavailable.

### 3.6 Confirmation Evidence (`confirmation`)

**Available data**: Market breadth, VIX (cross-instrument confirmation)

**Rules**:
- `breadth_positive` — advances > declines
- `breadth_negative` — advances < declines
- `vix_low` — VIX < 15
- `vix_high` — VIX > 20

**Key design**: NIFTY bullish + BANKNIFTY bearish → MIXED confirmation, NOT forced directional.

## 4. Normalized Evidence Model

Every evidence group produces:

```json
{
  "group": "trend",
  "availability": "LIVE|DELAYED|EOD|HISTORICAL|UNAVAILABLE",
  "signal": "BULLISH|BEARISH|RANGE|MIXED|NEUTRAL|UNAVAILABLE",
  "strength": "WEAK|MODERATE|STRONG",
  "confidence": "WEAK|MODERATE|STRONG",
  "rules_triggered": [],
  "rules_not_triggered": [],
  "data_used": {},
  "reason": "",
  "notes": "",
  "timestamp": "ISO"
}
```

`availability` is distinct from `data_state`:
- `LIVE` — fresh data, just processed
- `DELAYED` — data from a recent closed session
- `EOD` — end-of-day data
- `HISTORICAL` — backfilled historical data
- `UNAVAILABLE` — no data available

## 5. Overall Evidence Summary

```json
{
  "overall_signal": "BULLISH|BEARISH|RANGE|MIXED|INSUFFICIENT_DATA",
  "overall_strength": "WEAK|MODERATE|STRONG|NONE",
  "bullish_groups": 4,
  "bearish_groups": 1,
  "neutral_groups": 1,
  "unavailable_groups": 0,
  "total_groups": 6,
  "conflict_level": "NONE|MODERATE|HIGH"
}
```

## 6. Conflict Detection

```json
{
  "detected": true,
  "groups": ["momentum", "options"],
  "severity": "MODERATE|HIGH|NONE",
  "signals": {"trend": "BULLISH", "momentum": "BEARISH"}
}
```

Detected when 2+ groups have opposing directional signals (BULLISH vs BEARISH).

## 7. Data Availability Rules

- Missing indicator → UNAVAILABLE signal, NOT zero or neutral assumption
- No options data → UNAVAILABLE, AI receives explicit "options evidence unavailable"
- Stale data → DELAYED, AI may still interpret but data_state reflects staleness
- Partial data → Evaluate with available data, mark UNAVAILABLE for missing groups

## 8. Database Table: market_evidence_5m

```sql
CREATE TABLE market_evidence_5m (
    evidence_id TEXT NOT NULL UNIQUE,
    instrument TEXT NOT NULL,
    candle_timestamp TEXT NOT NULL,
    generated_at TEXT,
    snapshot_id TEXT,
    trend_json TEXT DEFAULT '{}',
    momentum_json TEXT DEFAULT '{}',
    structure_json TEXT DEFAULT '{}',
    volatility_json TEXT DEFAULT '{}',
    options_json TEXT DEFAULT '{}',
    confirmation_json TEXT DEFAULT '{}',
    overall_signal TEXT DEFAULT 'INSUFFICIENT_DATA',
    overall_strength TEXT DEFAULT 'NONE',
    conflict_json TEXT DEFAULT '{}',
    data_quality TEXT DEFAULT 'UNAVAILABLE',
    data_state TEXT DEFAULT 'UNAVAILABLE',
    engine_version TEXT,
    created_at TEXT,
    UNIQUE(instrument, candle_timestamp)
);
```

## 9. API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/market-evidence/{symbol} | GET | Current evidence + recent snapshots |
| /api/market-evidence/timeline/{symbol} | GET | Historical evidence (paginated) |

## 10. AI Integration

The AI outlook prompt was updated to receive structured evidence instead of raw indicators. The AI output schema includes:
- `conflicting_evidence` field
- `data_availability` field (per group)
- `evidence_summary` in the outlook record

## 11. Look-Ahead Protection

Evidence engine uses only data available at or before candle timestamp. Verified by:
- No future candle references in rules
- All indicators calculated from historical/current data
- `candle_timestamp` preserved in output

## 12. Configurable Thresholds

All thresholds are configurable via `MarketEvidenceEngine(config)` constructor. Documented in the config section above. No threshold optimization against historical data.
