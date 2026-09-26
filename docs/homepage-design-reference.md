# TradingAI.in — Homepage Design Reference (FROZEN)

> **Status: FROZEN — do not restyle without updating this doc.**
> Frozen on: 2026-09-25 08:10 IST
> Source URL: https://tradingai.in/
> Source file: `/opt/tradingai/frontend/index.html`
> Hash (md5): `d3bbf65ac1ae6705170ed23fb2f2c68a`
> Size: 11705 bytes, single-file HTML (inline `<style>` + tiny clock `<script>`, no external deps)
> Frozen copy: `/opt/tradingai/frontend/index.frozen-2026-09-25.html`
> Mockup ref: `/opt/tradingai/chatgpt-image-sep25-075912-am.png`

## 1. Design principle (decision-first dashboard)

When a trader lands, the first screen must immediately answer:

1. NIFTY 50 — Bullish / Bearish / Neutral
2. BANKNIFTY — Bullish / Bearish / Neutral
3. Current market price (+ change / %)
4. CPR position (CPR High / CPR Low + price vs CPR)
5. S1 / S2 / R1 / R2
6. Recommended strategy
7. Why that strategy (1–2 line rationale)
8. Trade / Wait / No Trade signal

No marketing hero, no tables of raw data above the fold.

## 2. Page structure (top → bottom)

```
1. Topbar (dark navy): brand left, LIVE IST clock right
2. Nav (dark navy): Home | Nifty | BankNifty | Backtest | Methodology
3. .wrap (max-width 1400px)
   3a. Focus banner (light blue): "Today's Focus" + flow
   3b. Today's Market banner (white): NIFTY signal | BANKNIFTY signal
   3c. .grid 2-col: NIFTY card | BANKNIFTY card
       - head: name + INDEX badge + price/chg + day H/L/O + direction pill
       - levels box: R2, R1, CPR High, CPR Low, S1, S2, Current Price
       - strategy box (light green): name + Trade/Wait + Why + View Details btn
   3d. Market Structure strip (white): chips row
   3e. Link cards 4-col: NIFTY Analysis | BANKNIFTY Analysis | Backtest | Methodology
4. Footer (dark navy): tagline + indices + live dot
```

Reference ASCII from owner spec is authoritative for ordering; this file freezes visual styling.

## 3. Tokens

| Token | Value | Usage |
|---|---|---|
| Navy bg | `#0b1e3a` | topbar, nav, footer |
| Navy border | `#1e3a5f` | nav divider |
| Page bg | `#f1f5f9` | body |
| Card bg | `#ffffff` | banner, cards, structure, links |
| Card border | `#e2e8f0` | card outlines |
| Inner box border | `#eef2f7` | levels box |
| Text | `#0f172a` | primary |
| Muted | `#475569` / `#64748b` | sub, hints |
| Accent blue | `#38bdf8` / `#22d3ee` | nav hover, `.in` dot |
| Badge blue bg / fg | `#eff6ff` / `#2563eb` | INDEX badge, CPR lines `#60a5fa` |
| Bull green | `#16a34a` (text `#15803d`, box bg `#f0fdf4`, border `#bbf7d0`) | bullish, TRADE pill, S lines `#86efac` |
| Bear red | `#b91c1c` / `#dc2626`, lines `#fca5a5`/`#fecaca` | bearish, R lines |
| Neutral orange | `#b45309` / WAIT `#d97706` | neutral / WAIT |
| No-trade red | `#dc2626` | NO_TRADE pill |
| Focus bg | `#e8f1fd`, border `#dbeafe` | focus banner |
| Radius | 6 / 8 / 10 / 12px, pills 999px | buttons 6, levels 8, banners 10, cards 12 |
| Font | `-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif` | system stack only |
| Price | 1.8rem/800 | `.price` |
| Signal | 1.25rem/800 | `.banner .sig` |
| Card title | 1.3rem | `.card-head h2` |

Direction → color mapping (MUST keep):
- BULLISH → green (`#15803d` text, `#16a34a` pill)
- BEARISH → red (`#b91c1c`)
- NEUTRAL → orange (`#b45309`)
- TRADE → green pill, WAIT → orange pill, NO_TRADE → red pill

Level-line mapping (MUST keep):
- R2/R1 → red lines; CPR High/Low → blue lines; S1/S2 → green lines; Current Price → dashed top border, dark text.

## 4. Sections & fields

### 4a. Topbar
- Brand: `TradingAI.in` (`.in` in cyan `#22d3ee`), tagline `Market Insights | Smart Setups | Better Trades`
- Right: green pulse dot + `IST HH:MM:SS` (JS, Asia/Kolkata) + `Live` pill

### 4b. Nav
Right-aligned: Home(active) Nifty BankNifty Backtest Methodology → `/index.html`, `/indices/nifty.html`, `/indices/banknifty.html`, `/backtest.html`, `/methodology.html`. Active = white + 2px `#38bdf8` underline.

### 4c. Focus banner
- Left: `🎯 Today's Focus` + `Follow the recommended strategy based on current market structure, CPR levels and price action.`
- Right flow: `Market → Structure → … → Trade / Wait → Risk → Outcome`

### 4d. Today's Market banner
- `TODAY'S MARKET` + `NIFTY 50: BULLISH ▲` | `BANKNIFTY: BULLISH ▲` (color per §3)

### 4e. Instrument card (×2, identical layout)
Fields (frozen example values — replace with live, keep format):
- NIFTY: `24,861.35`, `+182.60 (+0.74%) ▲`, H `24,890.20` L `24,712.15` O `24,730.40`, CPR `24,742 – 24,768`, R2 `24,892` R1 `24,830` S1 `24,680` S2 `24,618`
- BANKNIFTY: `54,321.75`, `+412.30 (+0.77%) ▲`, H `54,608.65` L `53,987.40` O `54,012.20`, CPR `54,112 – 54,268`, R2 `54,742` R1 `54,512` S1 `53,882` S2 `53,652`
- Direction pill `🟢 BULLISH` + `Market Direction ↗`
- Strategy: `Call Credit Spread — Near CPR`, `Trade / Wait: TRADE`, Why 1–2 lines, `View Details →` (outline green btn → hover fill)

### 4f. Market Structure strip
Chips (keep order): Price vs CPR | VWAP | ATR | VIX | OI | PCR | Gap | 5m Price Action. Frozen values: Above, Bullish, Normal, `12.48 (-2.85%)`, Call writing high, `1.12`, Up +0.4%, Higher highs.

### 4g. Link cards
4 cards → NIFTY Analysis / BANKNIFTY Analysis / Backtest / Methodology with 1-line sub. Hover border `#38bdf8`.

### 4h. Footer
`TradingAI.in · Smarter Analysis. Disciplined Trading. · NIFTY 50 | BANKNIFTY | SENSEX · ● Live Market Data`

## 5. Responsive (frozen breakpoints)

- `≤900px`: `.grid` 2col → 1col; `.links` 4col → 2col (stack further on narrow via wrap)
- topbar/focus/banner wrap with flex-wrap; no hamburger (nav stays inline, wraps)

## 6. What is frozen vs live data

Frozen = layout, tokens, ordering, component styles, copy tone.
NOT frozen = numeric values (prices, levels, signals, strategy, rationale, chips). Those must be wired to `/api/*` later using the same DOM/CSS.

## 7. Change rules

1. Content-only (prices/levels/strategy text): edit values, keep classes.
2. New page (nifty/banknifty/backtest/methodology): reuse `.card/.levels/.strat/.chip/.btn` — do not invent new palette.
3. Restyle: update this doc + take new frozen copy + record new hash.
