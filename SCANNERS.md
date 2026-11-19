# TradingAI Paper Scanners — Master Documentation

Complete reference for the 8 paper scanners running on the TradingAI VM:
7 BUY-only NIFTY option-premium scanners plus `pattern_scanner`, all sharing
the same trail exit model. Six option scanners use a fixed 5% stop; the
standalone `sma9_atr` scanner uses a volatility-scaled (ATR) stop.
`sma9_1min_poll` runs the SMA9 entry and exit rules at a 60-second poll
instead of every 5 seconds.

`green15` and `no_sma` are retired: stopped, disabled on boot, removed from
the launcher (and `no_sma` from the performance report); their slots are not
restarted. `green15`'s API namespace returns 404. The code trees and DBs
remain on disk as archives.

> **Paper trading only.** No scanner can place a broker order. There is no
> `place_order` call, no order id, and no broker write path anywhere in this
> stack. Every fill is simulated in SQLite at the sampled option LTP.

---

## 1. What runs on the box

| # | Scanner key | Family | Entry logic | Exit logic |
|---|---|---|---|---|
| 1 | `sma9` | Base SMA | prev close > SMA9 **and** forming open > SMA9 | trail stop, then 5% stop; otherwise hold |
| 2 | `sma9_high` | HIGH | prev close > SMA9 **and** forming open > SMA9 **and** LTP > prev candle high | trail stop, then 5% stop; otherwise hold |
| 3 | `sma9_1min_poll` | SMA9 1-min | prev close > SMA9 **and** forming open > SMA9, polled once per minute | trail stop, then 5% stop; otherwise hold |
| 4 | `sma9_trail` | Trail | self-contained entry (prev.close>SMA9 & forming.open>SMA9) + trail exit | trail stop, then 5% stop; otherwise hold |
| 5 | `sma9_high_trail` | Trail | self-contained entry (prev.close>SMA9 & forming.open>SMA9 & LTP>prev.high) + trail exit | trail stop, then 5% stop; otherwise hold |
| 6 | `no_sma_trail` | Trail | self-contained entry (LTP>prev.high) + trail exit | trail stop, then 5% stop; otherwise hold |
| 7 | `pattern_scanner` | Pattern | bullish/bearish patterns on NIFTY SPOT 5m candles | trail stop, then fixed 12-point spot stop; otherwise hold |
| 8 | `sma9_atr` | ATR stop | prev close > SMA9 **and** forming open > SMA9 | trail stop, then ATR-scaled stop (fills at live LTP); otherwise hold |

There is **no time-based or candle-close exit** on any of the 8 scanners:
if neither the trail nor the fixed stop fires, the position stays open
across candles (including overnight) until one of them does. `pattern_scanner`
uses the same trail mechanics but a fixed 12-point spot stop (see §5.5).
`sma9_atr` replaces only the initial stop distance (see §5.6).
`sma9_1min_poll` is the only scanner that does not poll every 5 seconds: it
samples the forming candle once per minute, so a spike between two polls is
not seen (see §5.3).

Each of the 7 trail/SL scanners is a **fully independent stack**: own code
directory, own Python library directory, own SQLite database, own unprivileged
service user, own systemd unit, own API namespace and own dashboard page.
Nothing is shared except the host, the Kite credentials, the Flask API process
and nginx. `pattern_scanner` shares the main `app/` tree and the `ubuntu` user
but has its own service, status file, DB tables and dashboard.

---

## 2. Requirements

### 2.1 Host

| Item | Current value / requirement |
|---|---|
| OS | Ubuntu 22.04.5 LTS (systemd, `chattr`, `logrotate`) |
| Kernel | 6.8.x |
| CPU | 2 vCPU (AMD EPYC) |
| RAM | 956 MB — tight but sufficient for 7 scanner processes + API workers |
| Swap | 2 GB swapfile (used as headroom, not steady state) |
| Disk | 45 GB, ~21 GB free |
| Python | 3.10.12 (`/usr/bin/python3`) |
| SQLite | 3.37.2 (library + CLI for inspection) |
| Network | outbound HTTPS to `api.kite.trade`; inbound HTTPS via nginx + Cloudflare |
| Database server | **none required** — MySQL/PostgreSQL are not used or installed for this stack |

### 2.2 Zerodha / Kite Connect

| Item | Detail |
|---|---|
| Product | Kite Connect (market data) |
| API key / secret | stored in `/opt/tradingai/.env.zerodha` (mode `640 ubuntu:ubuntu`) |
| Access token | **expires every day**; must be refreshed before 09:15 IST |
| Rate limits | quotes ≈ 1 request/second per API key; historical ≈ 3 requests/second per API key |
| Instruments | NIFTY options (nearest expiry), NIFTY spot quote |

Token refresh runbook: `/opt/tradingai/TOKEN_REFRESH.md`.
Automatic check: `tradingai-token-check.timer` at **08:45 IST, Mon–Fri**.

### 2.3 Python packages

**Runtime third-party dependency (all 8 scanners):**

```
kiteconnect==5.2.2
```

`kiteconnect` is imported lazily inside the broker connection method. The
scanner process starts without it, but cannot load instruments or quotes.

Transitive dependencies are already present in the system Python 3.10
`dist-packages`:

| Package | Installed |
|---|---|
| requests | 2.32.5 |
| six | 1.16.0 |
| pyOpenSSL | 21.0.0 |
| python-dateutil | 2.9.0.post0 |
| twisted | 22.1.0 |
| service_identity | present |
| autobahn | 19.11.2 |

**Standard library only** for all strategy logic: `json`, `logging`, `os`,
`sqlite3`, `sys`, `time`, `traceback`, `random`, `datetime`, `zoneinfo`,
`collections`, `csv`, `dataclasses`, `hashlib`, `subprocess`, `typing`.

**Isolation model:** each unit sets `PYTHONPATH=/opt/tradingai/<key>_lib`.
That directory is searched first, then the system `dist-packages`. Each lib
directory is a full 328 MB site-packages copy (≈2.0 GB total for 6); at
runtime only `kiteconnect` (and its system-wide deps) is actually used. The
extra packages (pytest, pandas, numpy, flask, gunicorn, groq, playwright, …)
are leftovers from the build environment and are not imported by scanners.

Canonical requirements file: [`docs/requirements.txt`](requirements.txt).

### 2.4 Services and routing

| Component | Detail |
|---|---|
| API | `tradingai-api.service` — gunicorn, 2 workers × 4 threads, `127.0.0.1:8092`, Flask `app.api.app:app` |
| Reverse proxy | nginx `tradingai.in`, TLS via Let's Encrypt, Cloudflare origin lock, `/api/` → gunicorn |
| Dashboards | static files under `/opt/tradingai/frontend/live/<slug>/` |
| Process supervision | systemd, `Restart=always`, `RestartSec=5` (scanners) / `10` (API) |

---

## 3. Basic configuration (common to all scanners)

### 3.1 Market and timing

| Constant | Value | Meaning |
|---|---|---|
| `IST` | `Asia/Kolkata` | all timestamps |
| `MARKET_OPEN` | `09:15` | session open (status reporting) |
| `MARKET_CLOSE` | `15:30` | session close (status reporting) |
| `ENTRY_START` | `09:20` | first allowed entry |
| `ENTRY_END` | `15:15` | entry cutoff (exclusive) |
| `POLL_SECONDS` | `5` | decision cadence |
| `CANDLE_MINUTES` | `5` | candle size |
| `MUHURAT_SESSIONS` | date → (open, close) | special-session override |

Entry window rule:

```python
ENTRY_START <= now.time() < ENTRY_END
```

Consequences:

- The **09:15 candle is never entered**.
- The **last entry candle is 15:10** (no new entries at/after 15:15).
- Nothing opens at or after **15:15:00**.
- **Exits and trail stops are not gated** — open positions still exit normally
  after 15:15 (all 8 scanners hold indefinitely until the trail or stop
  fires; there is no session-end square-off).
- The window is fixed wall-clock, so on a special session (e.g. 14:00–17:00)
  entries are still limited to 09:20–15:15.

`market_is_open()` remains 09:15–15:30 and is used only for status/IDLE
reporting, not for entry permission.

### 3.2 Contract selection

| Item | Value |
|---|---|
| Underlying | `NIFTY` |
| Timeframe | `5m` |
| ATM strike | `round(spot / 50) * 50` (50-point step) |
| Expiry | nearest NIFTY expiry ≥ today |
| Option types | CE and PE evaluated independently, both BUY-only |
| Lot size (reference) | 65 |

All logic is based on the **option premium candles/LTP**, never on the NIFTY
index price. The index is used only to select the ATM strike.

### 3.3 Credentials

| File | Purpose |
|---|---|
| `/opt/tradingai/.env.zerodha` | `ZERODHA_MODE`, `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN`, `REDIRECT_URL` |
| `/opt/tradingai/zerodha_credentials.py` | loader used by token exchange and scanners |
| `/opt/tradingai/refresh_token.sh` | exchange + persist + restart + verify |
| `/opt/tradingai/premarket_token_check.sh` | read-only 08:45 validity check |

Never commit `.env.zerodha`, `zerodha_credentials.py`, or any token to git.

### 3.4 Per-scanner environment (systemd)

Each of the 7 trail/SL scanner units sets:

```ini
Environment=<KEY>_DB_PATH=/opt/tradingai/database/<key>.db
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONPATH=/opt/tradingai/<key>_lib
```

and runs:

```ini
ExecStart=/usr/bin/python3 /opt/tradingai/<key>_scanner/app/live_<key>_scanner.py
Restart=always
RestartSec=5
StandardOutput=append:/opt/tradingai/logs/live_<key>_scanner.log
```

`pattern-scanner-live.service` differs: user `ubuntu`, `WorkingDirectory=/opt/tradingai`,
`PYTHONPATH=/opt/tradingai`, `ExecStart=/usr/bin/python3
/opt/tradingai/scripts/pattern_scanner_live.py`, log
`/opt/tradingai/logs/pattern_scanner_live.log`, `RestartSec=10`.

### 3.5 Paths

| Item | Path |
|---|---|
| Code | `/opt/tradingai/<key>_scanner/` |
| Live entrypoint | `/opt/tradingai/<key>_scanner/app/live_<key>_scanner.py` |
| Strategy engine | `/opt/tradingai/<key>_scanner/app/<key>_engine.py` |
| Python libs | `/opt/tradingai/<key>_lib/` |
| Database | `/opt/tradingai/database/<key>.db` |
| Log | `/opt/tradingai/logs/live_<key>_scanner.log` |
| Pre-patch backups | `/opt/tradingai/backups/` |
| Dashboard files | `/opt/tradingai/frontend/live/<slug>/` |
| API routes | `/opt/tradingai/app/api/app.py` |
| Pattern live runner | `/opt/tradingai/scripts/pattern_scanner_live.py` |
| Pattern engine | `/opt/tradingai/app/research/pattern_scanner.py` |
| Pattern status file | `/opt/tradingai/data/pattern_scanner_status.json` |

---

## 4. Scanner configuration matrix

`off` = `POLL_OFFSET_SECONDS`, the per-scanner phase offset inside the 5-second
tick. It staggers Kite quote/historical calls so the scanners do not all hit
the API at the same instant.

| Key | Strategy id | Strategy type | Ver | SMA | Trail / activate | off | User | systemd unit |
|---|---|---|---|---|---|---|---|---|
| `sma9` | `sma9_only` | `SMA9_BUY_ONLY` | 2.7.0 | 9 | — | 0 | `sma9` | `tradingai-sma9-scanner` |
| `sma9_high` | `sma9_high` | `SMA9_HIGH_BUY_ONLY` | 1.8.0 | 9 | — | 2.4 | `sma9high` | `tradingai-sma9-high-scanner` |
| `sma9_1min_poll` | `sma9_1min_poll` | `SMA9_1MIN_POLL_BUY_ONLY` | 1.0.0 | 9 | — | — (60s) | `sma91m` | `tradingai-sma9-1min-poll-scanner` |
| `sma9_trail` | `sma9_trail` | `SMA_BUY_ONLY` | 2.1.0 | 9 | 5.0 / 5.0 | 1.2 | `sma9trail` | `tradingai-sma9_trail-scanner` |
| `sma9_high_trail` | `sma9_high_trail` | `SMA_HIGH_BUY_ONLY` | 2.1.0 | 9 | 5.0 / 5.0 | 3.0 | `sma9trailhigh` | `tradingai-sma9_high_trail-scanner` |
| `no_sma_trail` | `no_sma_trail` | `PREV_HIGH_BUY_ONLY` | 2.1.0 | — | 5.0 / 5.0 | 4.2 | `nosmatrail` | `tradingai-no_sma_trail-scanner` |
| `pattern_scanner` | — | — | — | — | 5.0 / 5.0 | — | `ubuntu` | `pattern-scanner-live` |

All scanners poll every 5 seconds except `sma9_1min_poll`, which wakes once
per wall-clock minute and has no phase offset.

**Stop loss:** the six premium-based scanners use a fixed stop at **entry premium × 0.95** for CE (or × 1.05 for PE) — 5% of the entry price, `STOP_LOSS_5PCT` — and the same trail: activate at +5 pts (stop → entry), ratchet `peak − 5` (or `trough + 5` for PE), one-time breakeven lock at +6 (stop ≥ entry + 2, or ≤ entry − 2 for PE). The trail exit is evaluated first; the 5% stop is the additional floor. `sma9_1min_poll` evaluates both on its 60-second cadence.

**`pattern_scanner` exception:** its stop/trail levels are derived from **NIFTY SPOT price** (not option premium). Initial SL = a **fixed 12 NIFTY points** from the entry spot (no percentage scaling — the same 12-point distance at 18,000, 25,000 or 30,000); trail mechanics identical but applied to spot. The option is exited at its current LTP when spot breaches the stop.

DB path is always `/opt/tradingai/database/<key>.db`.
API namespace is always `/api/<slug>/` (slug = key with `_` → `-`).
Dashboard is always `https://tradingai.in/live/<slug>/`.

---

## 5. Strategy rules in detail

Candles are 5-minute option-premium candles. `completed` = all candles except
the still-forming last one. `prev` = last completed candle. `SMA_N` = mean of
the last *N* completed closes.

### 5.1 Base SMA (`sma9`)

```
condition_a = prev.close > SMA_N
condition_b = forming.open > SMA_N
signal      = condition_a AND condition_b
entry       = paper BUY at round(LTP, 2)
exit        = trail stop (TRAIL_STOP_EXIT) first,
              then fixed stop at entry × 0.95 (`STOP_LOSS_5PCT`);
              no candle-close or time-based exit
```

Both conditions must be true; there is **no separate LTP > SMA confirmation
gate**. Entry may fire on any 5-second poll while the signal holds.

Exit: on every 5-second poll the trail stop is evaluated first (see §5.4 for
the `hwm`/`ACTIVATE`/`TRAIL`/breakeven-lock rules), then the fixed stop. The
position is closed when the live LTP reaches **`round(entry × 0.95, 2)`**
(`STOP_LOSS_5PCT`). If neither fires the position stays open across candles
and overnight until one of them does.

### 5.2 HIGH (`sma9_high`)

```
condition_a = prev.close > SMA_N
condition_c = forming.open > SMA_N
condition_b = LTP > prev.high
signal      = condition_a AND condition_c AND condition_b
entry       = paper BUY at round(LTP, 2)
exit        = trail stop (TRAIL_STOP_EXIT) first,
              then fixed stop at entry × 0.95 (`STOP_LOSS_5PCT`);
              no candle-close or time-based exit
```

This is the strict variant: the previous completed candle must close above
the SMA, the forming candle must open above the SMA, and the live premium
must break the previous candle high. There is **no separate LTP > SMA
confirmation gate**.

Exit: same trail-first, then fixed 5% stop as the base SMA scanners.

### 5.3 SMA9 1-minute poll (`sma9_1min_poll`)

```
signal = prev.close > SMA9 AND forming.open > SMA9
poll   = every 60 seconds, aligned to the wall-clock minute
entry  = paper BUY at round(LTP, 2)
exit   = trail stop (TRAIL_STOP_EXIT) first,
         then fixed stop at entry × 0.95 (`STOP_LOSS_5PCT`);
         no candle-close or time-based exit
```

Same signal and exits as `sma9`; the only difference is the cadence: stop and
trail are evaluated on the forming candle once per minute instead of every 5
seconds. The scanner refuses to treat the previous completed candle as
forming when the exchange has not published the current 5-minute candle yet.
At most one entry per 5-minute candle; entry window 09:20–15:15.

It replaced the retired `no_sma` (previous-high breakout) scanner on
2026-11-19. `no_sma` history stays in `database/no_sma.db` and its page stays
on disk, but it is no longer on the launcher or the performance report.

### 5.4 Trail (`*_trail`)

Each trail scanner is **fully self-contained**: it evaluates its own entry
signals from live 5-minute option candles and owns both entry and exit. No
dependency on any base scanner API.

Entry signals (per option, CE and PE evaluated independently):

- `sma9_trail`: `prev.close > SMA9` **and** `forming.open > SMA9`
- `sma9_high_trail`: `prev.close > SMA9` **and** `forming.open > SMA9`
  **and** `LTP > prev.candle.high`
- `no_sma_trail`: `LTP > prev.candle.high`

Each tick the trail scanner fetches the latest 5-minute candles for its ATM
CE and PE contracts, evaluates the entry conditions above, and enters at the
sampled LTP when the signal fires. At most one entry per 5-minute candle per
option.

Exit is evaluated on every poll (trail first, then the 5% stop):

```
hwm  = max(hwm, LTP)
if hwm - entry >= ACTIVATE (5.0):
    stop = entry            # first activation: breakeven
    stop = max(stop, hwm - TRAIL)   # ratchet up only
# One-time breakeven lock: once profit reaches +6, lock in entry + 2 exactly
# once; the normal trail then continues ratcheting from the locked stop.
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)
    be_locked = True
if stop is not None and stop > entry and LTP <= stop:
    exit at round(LTP, 2)   # actual sampled LTP at breach
    reason = TRAIL_STOP_EXIT
elif LTP <= round(entry × 0.95, 2):
    exit at round(entry × 0.95, 2)
    reason = STOP_LOSS_5PCT
else:
    hold (across candles and overnight)
```

- `TRAIL = 5.0`, `ACTIVATE = 5.0`.
- One-time breakeven lock: at +6 pts profit the stop is set to entry + 2 pts
  exactly once (`be_locked`), after which the normal `hwm - TRAIL` trail
  continues ratcheting up only.
- A fixed **5% stop** on the entry premium is the floor: if LTP reaches
  `round(entry × 0.95, 2)` the trade exits with reason `STOP_LOSS_5PCT`. It is
  checked after the trail exit, so a profitable trail lock always wins. The
  trail itself still ignores a breakeven or losing trail stop.
- Exit price is the **actual LTP sampled at the breach**, not the idealized
  stop level (models slippage).
- `hwm`, `stop` and `be_locked` are persisted in the open-position row, so a
  restart resumes the trail correctly.

### 5.5 Pattern scanner (`pattern_scanner`)

Pattern-based entries on NIFTY SPOT 5m candles with the **same trail model as §5.4**, but a **fixed 12-point spot stop** instead of the premium 5% stop.
There is no ATR stop and no 15:15 square-off.

- **Signal source:** NIFTY SPOT 5-minute candles (completed candles only).
- **Entry:** any of ~37 bullish or ~37 bearish candlestick patterns on the completed SPOT candle.
  - **Bullish** pattern → **LONG ATM CE** (buy CE, weekly expiry)
  - **Bearish** pattern → **LONG ATM PE** (buy PE, weekly expiry)
- **Position type:** long-only on both sides — there is **no short CE and no short PE**.
  A bullish SPOT signal goes long CE; a bearish SPOT signal goes long PE.
- **Entry price:** the exact option's live LTP (CE for bullish, PE for bearish) sampled on the tick that closes the spot candle — not the spot close, and never a stale or opposite-leg quote. Quotes older than `MAX_QUOTE_AGE_SEC` (20s) are rejected, so a missed quote skips the entry instead of inventing a price.
- **Entry timestamp:** the actual tick time at which the trade was placed, not the signal candle's start.
- **Entry timing:** no new entries at or after 15:15 IST.
- **One per key:** at most one active position per `pattern_name:instrument`.
- **Entry tick skip:** a position entered at a candle's close is first managed on the following tick, never on its own entry tick.

**Exit:** tick-level on NIFTY SPOT price, trail first, then the fixed 12-point spot stop. Direction-aware:

- **BULLISH (long CE):** `hwm = max(hwm, spot)`; at `hwm − entry_spot ≥ 5` trail activates (`stop = entry_spot`), then `stop = max(stop, hwm − 5)` ratchets up; one-time BE lock at `hwm − entry_spot ≥ 6` → `stop = max(stop, entry_spot + 2)`. Exit `TRAIL_STOP_EXIT` when `stop > entry_spot` and `spot ≤ stop`.
- **BEARISH (long PE):** `lwm = min(lwm, spot)`; at `entry_spot − lwm ≥ 5` trail activates (`stop = entry_spot`), then `stop = min(stop, lwm + 5)` ratchets down; one-time BE lock at `entry_spot − lwm ≥ 6` → `stop = min(stop, entry_spot − 2)`. Exit `TRAIL_STOP_EXIT` when `stop < entry_spot` and `spot ≥ stop`.
- **Fixed 12-point spot stop (`STOP_LOSS_SPOT`):** `sl_spot = round(entry_spot − 12, 2)` for CE; `sl_spot = round(entry_spot + 12, 2)` for PE. The distance is always **12 NIFTY points**, independent of the index level (no percentage scaling). Exit when `spot ≤ sl_spot` (CE) or `spot ≥ sl_spot` (PE). Checked after the trail exit.
- **Exit price:** the position's own option LTP at the moment spot breaches the stop — not the spot level, and never the current ATM's opposite leg. A stale quote (>20s) defers the exit until a fresh one arrives.
- If neither fires the position stays open across candles and overnight. No candle-close or time-based exit.

SL and trail are calculated on NIFTY spot price only — never on option premium.

**Persisted state:** `stop_loss`, `hwm`, `lwm`, `entry_spot`, `be_locked`, `trailing_update_cnt`, `mfe_points` and `mae_points` are written on every trail change (`_persist_trailing`) and again on exit (`_persist_exit`). Each trail change is appended to `pattern_scanner_stop_changes`. Open positions are reloaded on startup (`_load_open_positions`), so a restart resumes the trail correctly. `_ensure_schema` adds the `hwm`/`lwm`/`entry_spot`/`be_locked` columns idempotently.

**Runner quoting:** every 5-second poll quotes the current ATM CE/PE **and** every instrument with an active position, so a position keeps being managed after the ATM band moves. Quotes are fed to the engine **before** the spot tick, so each entry/exit uses this poll's price rather than the previous poll's.

- No target. Paper trading only.

The live runner is `scripts/pattern_scanner_live.py` (systemd
`pattern-scanner-live.service`); the engine is
`app/research/pattern_scanner.py`.

### 5.6 ATR-stop scanner (`sma9_atr`)

Added 2026-11-18, first live day 2026-11-19. It is an isolated clone of
`sma9` with **one** behavioural change: the initial stop is scaled to the
option premium's own volatility instead of a fixed 5%.

**Entry** — identical to `sma9`: previous completed 5m candle close > SMA9
**and** forming candle open > SMA9; paper BUY at the live LTP, ATM CE/PE,
long only, entry window 09:20–15:15.

**Initial stop:**

```
atr      = mean True Range of the option premium over 14 completed 5m candles
distance = clamp(0.70 * atr, 5% * entry, 30% * entry)
stop     = entry - distance
```

If LTP <= stop the trade closes at the **actual live LTP**, not at the
theoretical stop price (`STOP_LOSS_ATR`). If the contract has fewer than 15
completed candles, the stop falls back to 10% of entry
(`stop_source='fallback_pct'`).

**Trail** — unchanged from `sma9`: +5 activates breakeven, then peak − 5;
breakeven lock at +6 moves the stop to entry + 2 (`TRAIL_STOP_EXIT`).
No time-based exit.

**Why:** the fixed 5% stop shrinks in absolute points as premium decays while
ATM option noise stays roughly constant (~11–15 points). On 2026-11-17
(0 DTE) the 5% stop was 2.34 points against ~14 points of 5m noise: 68% of
trades stopped out and 39 of 65 sat inside losing streaks. ATR scaling keeps
the stop outside the noise band on cheap contracts and close to the old 5%
distance on expensive ones.

**Isolation:** own code `/opt/tradingai/sma9_atr_scanner/`, DB
`database/sma9_atr.db`, tables `sma9_atr_trades` / `sma9_atr_open_positions` /
`sma9_atr_scan_state`, systemd `tradingai-sma9-atr-scanner.service`, log
`logs/live_sma9_atr_scanner.log`, report key `sma9_atr`. The service runs as
the existing `sma9` user but shares no code, DB, state or unit with `sma9`.

**Persisted state:** `atr_at_entry`, `stop_price`, `stop_k`,
`stop_distance_pct`, `stop_source`, `hwm`, `trail_stop`, `be_locked`. A
same-day restart resumes the exact stop and high-water mark; a position from
an earlier session is closed at the current LTP (`STALE_RECOVERY_EXIT`) rather
than carried.

**Pre-open operations:** the unit is `enabled` at boot and uses
`Restart=always`, and it is in the `ALL_UNITS` list of
`/opt/tradingai/refresh_token.sh`, so the daily token refresh restarts it with
the new token exactly like the other scanners. The token is read once at
process start, so a refresh without a restart would leave it on the expired
token. Two read-only checks cover the open:

```bash
python3 /opt/tradingai/sma9_atr_scanner/ops/dryrun_market_open.py   # fake clock/feed, temp DB
python3 /opt/tradingai/sma9_atr_scanner/ops/real_feed_check.py      # real Kite data, writes nothing
```

The first drives the deployed runner through pre-market → 09:15 open → 09:20
entry → stop at LTP → re-entry → restart recovery. The second verifies the
real instrument dump, nearest expiry, ATM CE/PE contracts, quotes, candles,
SMA9 evaluation and ATR stop preview.

---

## 6. Data model (SQLite)

Each database has three core tables, prefixed with the scanner key.
Trail databases have a fourth table:

| Table | Purpose |
|---|---|
| `<key>_trades` | closed trades (one row per paper round trip) |
| `<key>_open_positions` | live open position(s), keyed by option type (CE/PE) |
| `<key>_scan_state` | key/value runtime state |

Common `trades` columns: `trade_id`, `strategy_id`, `instrument`,
`trade_date`, `option_type`, `strike`, `expiry`, `signal_timestamp`,
`entry_timestamp`, `entry_price`, `exit_timestamp`, `exit_price`,
`exit_reason`, `pnl_points`, `status`, `candle_open/high/low/close`,
`created_at`, `updated_at`, `dataset`, `ltp_at_entry`, `entry_candle_start`,
`entry_candle_end`.

Family-specific columns:

| Family | Extra columns |
|---|---|
| Base SMA | `sma{n}_value` (`sma9_value`), `prev_close`, `condition_a`, `condition_b` |
| HIGH | `sma_value`, `prev_high`, `condition_a`, `condition_b`, `condition_c` |
| NO-SMA / prev-high | `prev_high`, `breakout` (retired `no_sma`; still used by `no_sma_trail`) |
| Trail | `prev_high`, `breakout`, and `hwm`, `stop`, `be_locked` in `open_positions`; base trade id in `consumed_base_trades` |

`exit_reason` is `STOP_LOSS_5PCT` or `TRAIL_STOP_EXIT` for the six premium-based scanners.
There is no candle-close, minute-10, or session-end reason on any of them.
`pattern_scanner` uses its own tables (`pattern_scanner_positions`,
`pattern_scanner_stop_changes` in `database/tradingai.db`) and reasons
`TRAIL_STOP_EXIT` or `STOP_LOSS_SPOT` (fixed 12-point spot stop; older rows
may still show `STOP_LOSS_5PCT` from the previous percentage model). No `SQUARE_OFF`.
`pnl_points = exit_price - entry_price` (BUY-only, one lot notional is not
applied).

Database ownership must be `<service-user>:ubuntu` with mode `664`; the
service user must be able to `BEGIN IMMEDIATE`.

---

## 7. API and dashboards

### 7.1 API

All 14 trail/SL namespaces expose the same 9 read-only endpoints:

```
GET /api/<slug>/signals
GET /api/<slug>/trades
GET /api/<slug>/daily-summary
GET /api/<slug>/scanner-status
GET /api/<slug>/live-status
GET /api/<slug>/recent-trades
GET /api/<slug>/today
GET /api/<slug>/legacy-audit
GET /api/<slug>/open-positions
```

`<slug>` values: `sma9`, `sma9-high`, `sma9-1min-poll`, `sma9-trail`,
`sma9-high-trail`, `no-sma-trail`. The retired `no-sma` endpoints remain so
the archived page still loads.

`sma9-atr` and `sma9-1min-poll` expose the same set except `legacy-audit`
(8 endpoints): `signals`, `trades`, `daily-summary`, `scanner-status`,
`live-status`, `recent-trades`, `today`, `open-positions`. They read
`database/sma9_atr.db` and `database/sma9_1min_poll.db` respectively; the
scanner is the only writer.

`pattern_scanner` has its own namespace (not the 9-endpoint set):

```
GET  /api/pattern_scanner/status
GET  /api/pattern_scanner/instruments
GET  /api/pattern_scanner/active-trades
GET  /api/pattern_scanner/closed-trades
GET  /api/pattern_scanner/pattern-summary
GET  /api/pattern_scanner/history
POST /api/pattern_scanner/start
POST /api/pattern_scanner/stop
```

The `start`/`stop` POSTs are **ops-only** (they wrap `systemctl start|stop`
on `pattern-scanner-live`). The dashboard has no manual start/stop/refresh
buttons: the service is enabled at boot, runs itself from the 09:15 open, holds
positions until the trail or 5% stop fires, and the page auto-refreshes every
5 s. `stop` halts the service immediately and leaves open rows in the DB; they
are reloaded and managed again on the next start.

`atm`, `sma9_avg`, and `green15` are retired and return **404**.

Quick health check:

```bash
curl -sk -H 'Host: tradingai.in' \
  https://127.0.0.1/api/sma9/scanner-status
curl -sk -H 'Host: tradingai.in' \
  https://127.0.0.1/api/pattern_scanner/status
```

### 7.2 Dashboards

| Scanner | Dashboard |
|---|---|
| sma9 | https://tradingai.in/live/sma9/ |
| sma9_atr | https://tradingai.in/live/sma9-atr/ |
| sma9_high | https://tradingai.in/live/sma9-high/ |
| sma9_1min_poll | https://tradingai.in/live/sma9-1min-poll/ |
| sma9_trail | https://tradingai.in/live/sma9-trail/ |
| sma9_high_trail | https://tradingai.in/live/sma9-high-trail/ |
| no_sma_trail | https://tradingai.in/live/no-sma-trail/ |
| pattern_scanner | https://tradingai.in/live/pattern_scanner/ |

Every active scanner has a button on `https://tradingai.in/live/scalp/` (the
base three, `sma9_atr`, `sma9_1min_poll`, the three trail scanners, and
`pattern_scanner`). All 8 active pages share the same dark theme, badge/table
styling, a `Back to Launcher` link, and auto-refresh without a page reload
(5 s for the 5-second scanners, 15 s for `sma9-1min-poll`). The `sma9-atr`
page additionally shows the entry ATR(14), the fixed ATR stop, the live trail
stop and BE lock, plus an ATR stop preview for each ATM option. The retired
`green15` and `no-sma` pages remain on disk but are unlinked from the
launcher.

---

## 8. Operations runbook

### 8.1 Daily pre-open

```bash
# 1. Token validity (read-only)
cat /opt/tradingai/logs/token_status.txt
systemctl list-timers tradingai-token-check.timer

# 2. If TOKEN_INVALID, refresh before 09:15
sudo /opt/tradingai/refresh_token.sh <REQUEST_TOKEN>

# 3. All 8 scanners + API active
systemctl is-active tradingai-api \
  tradingai-sma9-scanner tradingai-sma9-high-scanner \
  tradingai-sma9-1min-poll-scanner \
  tradingai-sma9_trail-scanner \
  tradingai-sma9_high_trail-scanner \
  tradingai-no_sma_trail-scanner pattern-scanner-live

# 4. Instrument load completed ("ready" in each log)
for f in /opt/tradingai/logs/live_*scanner.log; do
  printf '%-40s %s\n' "$(basename "$f")" "$(grep 'ready$' "$f" | tail -1)"
done
```

### 8.2 Restart

Restart scanners in staggered waves (3 s apart) so 7 instrument downloads do
not hit Kite at once:

```bash
for u in tradingai-sma9-scanner tradingai-sma9-high-scanner \
         tradingai-sma9-1min-poll-scanner \
         tradingai-sma9_trail-scanner \
         tradingai-sma9_high_trail-scanner \
         tradingai-no_sma_trail-scanner pattern-scanner-live; do
  sudo systemctl restart "$u"
  sleep 3
done
```

### 8.3 Health checks

```bash
# service state / restart count
systemctl show tradingai-sma9-scanner -p ActiveState -p NRestarts

# errors (auth, rate limit, DB, TLS, tracebacks)
sudo journalctl --since '09:15' --no-pager \
  | grep -iE 'Incorrect api_key|Too many requests|readonly database|SSLEOF|Traceback'

# all 14 trail/SL APIs return 200
for k in sma9 sma9-high sma9-1min-poll \
         sma9-trail sma9-high-trail no-sma-trail; do
  printf '%s=%s ' "$k" "$(curl -sk -o /dev/null -w '%{http_code}' \
    -H 'Host: tradingai.in' "https://127.0.0.1/api/$k/scanner-status")"
done; echo

# pattern scanner API
curl -sk -o /dev/null -w 'pattern_scanner=%{http_code}\n' \
  -H 'Host: tradingai.in' https://127.0.0.1/api/pattern_scanner/status

# DB writability as the service user
sudo runuser -u sma9 -g ubuntu -- python3 -c \
  'import sqlite3;c=sqlite3.connect("/opt/tradingai/database/sma9.db");c.execute("BEGIN IMMEDIATE");c.rollback();print("OK")'
```

### 8.4 Log rotation

Logrotate uses `copytruncate`; the copied file must be readable by the
rotating user. Files are `root:ubuntu 660`, and the logrotate stanza includes
`su ubuntu ubuntu`. After changing log ownership run:

```bash
sudo chown root:ubuntu /opt/tradingai/logs/*.log
```

### 8.5 Code locks (6 active trail/SL scanners)

The 6 active trail/SL scanner directories are protected: `root:root`, files mode
`444`, directories `555`, `chattr +i` on every file and directory, with a
SHA256 `MANIFEST.sha256` and an integrity timer for the original base/HIGH
families. `sma9_1min_poll` is installed `root:root`, files `444`, directories
`555` (no integrity timer).

```bash
# verify
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
# trail copies are mode 644 inside the locked tree; run them via bash
sudo bash /opt/tradingai/sma9_trail_scanner/ops/verify_integrity.sh

# approved change cycle
sudo /opt/tradingai/sma9_scanner/ops/unlock_code.sh
# edit + test
sudo /opt/tradingai/sma9_scanner/ops/lock_code.sh   # rebuilds manifest + relocks
sudo systemctl restart tradingai-sma9-scanner
```

Because the directories are immutable, `python3 -m py_compile` cannot write
`__pycache__` there; compile in-memory instead:

```bash
python3 -c "compile(open('/opt/tradingai/sma9_scanner/app/sma9_engine.py').read(), 'e', 'exec')"
```

The retired `green15_scanner/` tree is still `root:root` + `chattr +i` on
disk (it just no longer runs). The `pattern_scanner` files (`app/research/pattern_scanner.py`,
`scripts/pattern_scanner_live.py`) are **not** locked and have no manifest;
edit and restart `pattern-scanner-live.service` normally.

### 8.6 Rate-limit hygiene

- Base plain scanners (`sma9`, `sma9_1min_poll`): **2 quote calls per
  tick** — one spot-only refresh for ATM selection, plus one batched
  spot+CE+PE quote. Offset 0. `sma9_1min_poll` ticks once per minute, so its
  Kite call rate is 1/12th of the 5-second scanners.
- Base HIGH scanners: same **2-call** pattern, offsets 1.2 / 2.4 / 3.6 s.
- Trail scanners: **1 local base-status HTTP call + 1 batched spot+CE+PE quote
  per tick** (extra quote calls only on a failed batch or a newly missing
  contract), offsets 0.6–4.2 s. The base-status call is local and does not use
  Kite quota.
- Historical candles are fetched only when a new 5-minute candle appears (or
  at exit), never on every poll.
- Kite limits: quotes ≈1 req/s, historical ≈3 req/s per API key.
- If `Too many requests` appears in logs, check for overlapping restarts or a
  runaway historical fetch before changing offsets.

---

## 9. Safety guarantees

- **Paper only.** No broker order path exists. Verify with:

  ```bash
  sudo grep -rn 'place_order\|order_id' /opt/tradingai/*_scanner/app/ \
    /opt/tradingai/app/research/pattern_scanner.py \
    /opt/tradingai/scripts/pattern_scanner_live.py \
    && echo 'FOUND — investigate' || echo 'clean: no broker orders'
  ```

- **BUY only.** CE and PE are long-only; there is no short/sell-to-open path.
- **Fixed 5% stop on the six base scanners.** Every position exits at
  `round(entry × 0.95, 2)` if LTP falls that far (`STOP_LOSS_5PCT`); the trail
  stop is the preferred, higher exit and is evaluated first. `sma9_atr` uses
  an ATR-scaled stop instead (see §5.6), filled at the live LTP.
- **`pattern_scanner`** uses the same trail + 5% stop model (5-pt trail,
  +5 activate, +6 breakeven lock at +2). It has no ATR stop and no time exit.
- **No time-based exit** on any scanner; positions hold across candles and
  overnight until the trail or 5% stop fires.
- **Secrets** live only in `/opt/tradingai/.env.zerodha` and the local git
  config; they are never committed.
- **State survives restarts** via `open_positions` and `scan_state`, including
  trail `hwm`/`stop`.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Incorrect api_key or access_token`, zero trades | daily token expired | `sudo /opt/tradingai/refresh_token.sh <REQUEST_TOKEN>` |
| `Too many requests` | quote/historical burst, overlapping restarts | stagger restarts; check offsets; wait for the 1 s / 3 s window |
| `attempt to write a readonly database` | DB ownership/mode after redeploy | `chown <user>:ubuntu <db> && chmod 664 <db>` |
| `SSLEOFError` / `UNEXPECTED_EOF_WHILE_READING` during startup | transient Kite TLS reset | self-heals via `Restart=always` (~5 s); no action unless repeated |
| Service active but no entries | outside 09:20–15:15, no signal, or market closed | check `scanner-status`, `live-status`, and log reason strings |
| API 502/503 | gunicorn down or restarting | `systemctl status tradingai-api`, `journalctl -u tradingai-api` |
| Dashboard blank / iframe blocked | missing `X-Frame-Options: SAMEORIGIN` | check nginx security-headers snippet |
| Integrity timer failing | code changed without relock | `unlock_code.sh` → change → `lock_code.sh` |

---

## 11. Source sync and GitHub

| Item | Location |
|---|---|
| GitHub repo | `trail_build/out` (branches: `main` + 7 trail branches) |
| Trail branches | `sma9-trail`, `sma9-high-trail`, `no-sma-trail` |
| Local base sources | `/Users/satya/sma9_work/high_build/` (+ `out_nosma/`) |
| Local trail sources | `/Users/satya/sma9_work/trail_build/out/<key>_scanner/app/` |
| Trail template | `/Users/satya/sma9_work/trail_build/build_trail.py` (keeps the 09:20–15:15 window) |
| Base HIGH/NO-SMA builders | `high_build/build_high.py`, `high_build/build_nosma.py` |
| Local mirror of this doc | `/Users/satya/sma9_work/docs_build/` |

The base seven scanners do not have their own GitHub branches; their sources
are kept in sync locally and on the VM. The entry-window change is present in
all 6 active deployed files and in the trail build template.

---

## 12. Document map

| Document | Covers |
|---|---|
| `SCANNERS.md` (this file) | everything: requirements, dependencies, common config, matrix, operations |
| `docs/requirements.txt` | canonical Python requirements |
| `docs/scanners/<key>.md` | per-scanner entry/exit rules, constants, runtime, commands |
| `/opt/tradingai/TOKEN_REFRESH.md` | daily Kite token runbook |
| `<key>_scanner/docs/SECURITY_AND_OPERATIONS.md` | base-scanner lock policy (base 7 only) |
