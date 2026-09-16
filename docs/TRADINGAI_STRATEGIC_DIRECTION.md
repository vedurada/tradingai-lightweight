# TradingAI — Strategic Direction (Locked)

Created: 16 September 2026
Baseline: 3e8f0e2 → v2b5583a-baseline-16-g3e8f0e2
Status: AUTHORITATIVE — guides all future HTML work

---

## Product Definition

TradingAI is a daily, intraday market-intelligence and decision-support terminal for Indian index-options traders, centered on NIFTY, BANKNIFTY, FINNIFTY and SENSEX.

Before and during the trading session, the trader should be able to answer:

1. What is the market doing?
2. Is it trending, ranging or volatile?
3. What are the important levels?
4. What does options positioning/OI/PCR suggest?
5. What conditions are present right now?
6. Is there a tradeable setup or should I wait?
7. If considering a strategy, what is the defined risk?
8. How can I build, size and backtest it?

---

## Core Product Hierarchy

```
TRADINGAI
  INTRADAY MARKET INTELLIGENCE
    MARKET                    OPTIONS
    ├── NIFTY                 ├── PCR
    ├── BANKNIFTY             ├── OI
    ├── FINNIFTY              ├── Max Pain
    └── SENSEX                ├── Expected Move
         │                      ├── Call/Put Walls
         │                      └── Strategy Analysis
         │
         └─────────────────────┘
                    ↓
           AI MARKET OUTLOOK
                    ↓
          INTRADAY CONDITIONS
                    ↓
           STRATEGY ANALYSIS
                    ↓
    ┌──────────────┴──────────────┐
    │              │              │
 Strategy      Position       Backtest
 Builder        Size
    │              │              │
    └──────────────┴──────────────┘
                    ↓
                  LEARN
                   supporting research
```

---

## Primary User Journey

7:30 AM → Open TradingAI → Today: "What is today's market context?"
9:15 AM → Market opens → Market: "NIFTY/BANKNIFTY conditions?"
Options: "Where is OI concentrated? PCR? Expected range? Walls?"
During session → AI Outlook: "Trending/Ranging/Volatile?"
Strategy Analysis: "Which conditions are satisfied?"
Risk: "How much capital to risk?"
Strategy Builder: "What does the payoff look like?"
Backtest: "How has this setup behaved historically?"
Next day → Come back to Today again.

---

## Current Assessment

| Area | Status |
|------|--------|
| Core TradingAI concept | 🟢 Correct |
| AI market outlook | 🟢 Correct |
| Index analysis | 🟢 Correct |
| Options intelligence | 🟢 Correct |
| Strategy Builder | 🟢 Correct |
| Position sizing | 🟢 Correct |
| Backtesting | 🟢 Correct |
| Learn | 🟢 Correct |
| Today terminal | 🔴 Needs correction |
| Homepage architecture | 🟠 Needs consolidation |
| Legacy pages | 🔴 Need cleanup |
| Duplicate cards | 🔴 Need removal |
| Secondary modules | 🟠 Need demotion |
| Live data/runtime | 🔴 Needs Phase 30–32 |
| SEO/crawl architecture | 🔴 Needs cleanup |
| Overall product direction | 🟠 Recoverable, needs tightening |

---

## What NOT to become

These are secondary. Retain only where they provide genuine user/SEO value. Never compete with the core workflow:

- Stock Scanner
- Mutual Funds
- General Stock Research
- ETF Research
- Global Markets
- News
- 52-Week
- Portfolio
- Alerts

---

## Guiding Test for Every Page

For every page, card, link:

**"Does this help an Indian intraday index-options trader understand the market, evaluate options conditions, manage risk, or learn how to use the tools?"**

- Yes → retain, place correctly
- No → secondary, relocate, archive, or remove per PAGE_MANIFEST

---

## H31 Priority Adjustments

Based on this direction, the H31 workstream priority is:

1. **Today terminal cleanup** (remove Market Grid/Scanner/Backtest/Today LIVE cards) — highest priority HTML fix
2. **Homepage consolidation** (single canonical identity at /) — remove competing concepts
3. **Navigation alignment** (Home/Market/Today/Options/Strategies/Tools/Learn per master spec)
4. **BankNIFTY/FINNIFTY/SENSEX restructure** (apply NIFTY template)
5. **Legacy redirect architecture** (prepare /home.html, /index.html, /faq.html for 301)
6. **Secondary page demotion** (Scanner, Mutual Funds — keep but subordinate)

Do NOT proceed to:
- New page creation
- API endpoint creation (Phase 32)
- VM modifications (Phase 30)
- Visual theme redesign

---

## Next Objective

"Turn TradingAI into one coherent daily intraday index-options intelligence terminal, with every page supporting that core workflow."

This supersedes all previous HTML design directions. Every change in H31+ must be judged against the product definition above.
