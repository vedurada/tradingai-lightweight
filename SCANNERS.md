# TradingAI Paper Scanners — Master Documentation

Complete reference for the 7 paper scanners running on the TradingAI VM:
7 BUY-only NIFTY option-premium scanners are active. `sma9_5min` is deployed at
`/live/sma9-5min/`, and `sma9_adx` is deployed at `/live/sma9-adx/`. Five option scanners use a fixed 5%
stop; `sma9_adx` also uses a fixed 5% HWM trail; `sma9_atr`
uses a volatility-scaled **premium** ATR stop and ATR-only trail
(no +5 activation and no breakeven lock). `sma9_atr` also gates entries on a
daily NIFTY spot regime.
Six active scanners poll every 5 seconds; the staged
`sma9_5min` uses an aligned 5m cadence but keeps `sma9`'s sampled-LTP
stop/trail rules.

`green15`, `no_sma`, `no_sma_trail`, `sma9_slope_atr` and `sma9_1min_poll` are
retired: stopped, disabled on boot, removed from the launcher (and from the
performance report); their slots are not restarted. Their API namespaces
return 404. Code trees and DBs remain on disk as archives; the
`sma9_slope_atr` paper position was closed at the sampled LTP before
retirement and its archive is `archives/sma9_slope_atr_20261124/`. The
`sma9_1min_poll` archive is `archives/sma9_1min_poll_20261124/`.

> **Paper trading only (seven scanners).** None of the seven paper scanners can
> place a broker order. There is no `place_order` call, no order id, and no
> broker write path in any paper scanner. Every fill is simulated in SQLite at
> the sampled option LTP. The separate `sma9_live` execution service described
> in §9 is not part of this paper fleet and is dry-run by default.

---

## 1. What runs on the box

| # | Scanner key | Family | Entry logic | Exit logic |
|---|---|---|---|---|
| 1 | `sma9` | Base SMA | prev close > SMA9 **and** forming open > SMA9 | trail stop, then 5% stop; otherwise hold |
| 2 | `sma9_high` | HIGH | prev close > SMA9 **and** forming open > SMA9 **and** LTP > prev candle high | trail stop, then 5% stop; otherwise hold |
| 4 | `sma9_trail` | Trail | self-contained entry (prev.close>SMA9 & forming.open>SMA9) + trail exit | trail stop, then 5% stop; otherwise hold |
| 5 | `sma9_high_trail` | Trail | self-contained entry (prev.close>SMA9 & forming.open>SMA9 & LTP>prev.high) + trail exit | trail stop, then 5% stop; otherwise hold |
| 7 | `sma9_atr` | ATR stop + daily regime | prev close > SMA9 **and** forming open > SMA9 **and** regime allows that option | ATR trail, then ATR-scaled stop (both fill at live LTP); otherwise hold |
| 8 | `sma9_adx` | SMA9 + ADX | prev completed close > SMA9 **and** ADX(14) > 30 **and** +DI > -DI on completed option 5m candles | HWM-5% trail, then 5% initial stop (fixed, no time exit) |

The `sma9_5min` identity is deployed: it is an isolated copy of `sma9`
whose only behavioural change is an aligned 5-minute poll. `sma9_adx`
adds a Wilder ADX(14) > 30 and +DI > -DI trend filter and a 5% HWM trailing stop (see §5.8).

There is **no time-based exit** on any of the 7 scanners: if neither the trail
nor the stop fires, the position stays open across candles (including overnight)
until one of them does.
`sma9_atr` adds a daily spot-regime entry gate and replaces both the initial
stop and the trail with the frozen ATR distance (see §5.6). No scanner
has a 60-second poll anymore.

Each of the 7 premium scanners is a **fully independent stack**: own code
directory, own Python library directory, own SQLite database, own unprivileged
service user, own systemd unit, own API namespace and own dashboard page.
Nothing is shared except the host, the Kite credentials, the Flask API process
and nginx.

---

## 2. Requirements

### 2.1 Host

| Item | Current value / requirement |
|---|---|
| OS | Ubuntu 22.04.5 LTS (systemd, `chattr`, `logrotate`) |
| Kernel | 6.8.x |
| CPU | 2 vCPU (AMD EPYC) |
| RAM | 956 MB — tight but sufficient for 8 scanner processes + API workers |
| Swap | 2 GB swapfile (used as headroom, not steady state) |
| Disk | 45 GB, ~21 GB free |
| Python | 3.10.12 (`/usr/bin/python3`) |
| SQLite | 3.37.2 (library + CLI for inspection) |
| Network | outbound HTTPS to `api.kite.trade`; inbound HTTPS via nginx + Cloudflare |
| Database server | **none required** — MySQL/PostgreSQL are not used or installed for this stack |

### 2.2 Market data (read-only broker gateway)

| Item | Detail |
|---|---|
| Product | Kite-compatible **read-only** broker gateway (`instruments`, `quote`, `historical_data`, `profile` only); scanners never see keys or tokens |
| Active broker | selected by `BROKER_GATEWAY_SCANNER` / `broker-gateway use` (VM deployment maps all 8 scanners and the API to `mstock`; `zerodha` remains the code default) |
| Credentials | root-only on the VM, loaded by the gateway daemon; never read by a scanner process |
| Access token | broker-specific and short-lived; refreshed with the broker's own session tool before 09:00 IST, guarded by a per-call freshness check |
| Rate limits | quotes ≈ 1 request/second per broker key; historical ≈ 3 requests/second per broker key |
| Instruments | NIFTY options (nearest expiry), NIFTY spot quote |

Broker session checklist: `docs/zerodha/CREDENTIAL_SETUP_CHECKLIST.md`. Gateway
operations are root-only: `sudo broker-gateway status|adapters|probe|use`.
Automatic validity check: `tradingai-token-check.timer` at **08:45 IST, Mon–Fri**.

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

Canonical requirements file: [`requirements.txt`](requirements.txt).

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
| `MARKET_OPEN` | `09:00` | scanning/status start (exchange opens 09:15) |
| `MARKET_CLOSE` | `15:30` | session close (status reporting) |
| `ENTRY_START` | `09:20` | first allowed entry |
| `ENTRY_END` | `15:15` | entry cutoff (exclusive) |
| `POLL_SECONDS` | `5` | decision cadence for the seven active premium scanners |
| `POLL_SECONDS` (`sma9_5min`) | `300` | staged `sma9_5min`: aligned 5m poll at boundary + 10 s |
| `CANDLE_MINUTES` | `5` | candle size |
| `MUHURAT_SESSIONS` | date → (open, close) | special-session override |

Entry window rule:

```python
ENTRY_START <= now.time() < ENTRY_END
```

Consequences:

- **Scanning starts at 09:00 IST**, before the exchange opens, so the feed,
  token and status heartbeat are warm before the first candle. **09:00–09:15 is
  warm-up only:** the scanners poll and refresh quotes/status, but they do not
  evaluate entries and **do not manage exits**. `EXCHANGE_OPEN = 09:15` gates
  position management in every premium runner.
- The **09:15 candle is never entered**.
- The **last entry candle is 15:10** (no new entries at/after 15:15).
- Nothing opens at or after **15:15:00**.
- **Exits and trail stops are not gated** — open positions still exit normally
  after 15:15 (all 8 scanners hold indefinitely until the trail or stop
  fires; there is no session-end square-off).
- The window is fixed wall-clock, so on a special session (e.g. 14:00–17:00)
  entries are still limited to 09:20–15:15.

`market_is_open()` now runs 09:00–15:30, matching the scan start. Entry
permission still comes only from the 09:20–15:15 window above; the 09:00–09:15
warm-up cannot open a position because the current 5-minute candle is not yet
published. Exit management is additionally gated on `EXCHANGE_OPEN = 09:15`, so
a pre-open quote can never fire a trail or stop.

### 3.2 Contract selection

| Item | Value |
|---|---|
| Underlying | `NIFTY` |
| Timeframe | `5m` |
| ATM strike | `round(spot / 50) * 50` (50-point step) |
| Expiry | nearest NIFTY expiry ≥ today |
| Option types | CE and PE evaluated independently, both BUY-only |
| Lot size (reference) | 65 |

The seven premium scanners use **option-premium candles/LTP** for both entries
and exits (`sma9_atr` additionally gates entries on a daily NIFTY spot regime).
NIFTY spot is used to select the ATM strike.

### 3.3 Credentials

Broker credentials live **only** in root-owned files on the VM and are read by
the broker gateway daemon, never by a scanner process. Scanners select a broker
by name (`BROKER_GATEWAY_SCANNER` or `broker-gateway use`), not by embedding keys.

| Component | Purpose |
|---|---|
| gateway adapter credential file | per-broker API key/secret/token, root-only (`0600`) |
| `broker-gateway use` | root-only broker selection (`mstock` on the VM; `zerodha` is the code default) |
| broker session tool | mStock TOTP/OTP session; Zerodha request-token exchange via `refresh_token.sh` |
| `premarket_token_check.sh` | read-only 08:45 validity probe |

Never commit a broker credential file or any token to git. No scanner has a
write path to broker credentials.

### 3.4 Per-scanner environment (systemd)

Each of the 7 premium scanner units sets:

```ini
Environment=<KEY>_DB_PATH=/opt/tradingai/database/<key>.db
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONPATH=/opt/tradingai/<key>_lib
```

`PYTHONPATH` is `<key>_scanner` (not `_lib`) for the self-contained scanners
that carry their engine in the tree: `sma9_atr` uses only
that path (it relies on the system Python for `kiteconnect`).

and runs:

```ini
ExecStart=/usr/bin/python3 /opt/tradingai/<key>_scanner/app/live_<key>_scanner.py
Restart=always
RestartSec=5
StandardOutput=append:/opt/tradingai/logs/live_<key>_scanner.log
```

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

---

## 4. Scanner configuration matrix

`off` = `POLL_OFFSET_SECONDS`, the per-scanner phase offset inside the 5-second
tick. It staggers Kite quote/historical calls so the scanners do not all hit
the API at the same instant. The staged `sma9_5min` copy polls once per 5m
boundary +10 s with `POLL_SECONDS = 300` and `POLL_OFFSET_SEC = 10`.

| Key | Strategy id | Strategy type | Ver | SMA | Trail / activate | off | User | systemd unit |
|---|---|---|---|---|---|---|---|---|
| `sma9` | `sma9_only` | `SMA9_BUY_ONLY` | 2.7.0 | 9 | — | 0 | `sma9` | `tradingai-sma9-scanner` |
| `sma9_5min` (staged) | `sma9_5min` | `SMA9_5MIN_BUY_ONLY` | 1.0.0 | 9 | — | 5m +10 s | `sma95min` | `tradingai-sma9-5min-scanner` |
| `sma9_atr` | `sma9_atr` | `SMA9_ATR_STOP_BUY_ONLY` | 1.1.0 | 9 | ATR / none | 0 | `sma9` | `tradingai-sma9-atr-scanner` |
| `sma9_high` | `sma9_high` | `SMA9_HIGH_BUY_ONLY` | 1.8.0 | 9 | — | 2.4 | `sma9high` | `tradingai-sma9-high-scanner` |
| `sma9_trail` | `sma9_trail` | `SMA_BUY_ONLY` | 2.1.0 | 9 | 5.0 / 5.0 | 1.2 | `sma9trail` | `tradingai-sma9_trail-scanner` |
| `sma9_high_trail` | `sma9_high_trail` | `SMA_HIGH_BUY_ONLY` | 2.1.0 | 9 | 5.0 / 5.0 | 3.0 | `sma9trailhigh` | `tradingai-sma9_high_trail-scanner` |

Seven scanners poll every 5 seconds. The staged
`sma9_5min` polls once per 5-minute boundary +10 s, but keeps `sma9`'s
LTP-sampled stop/trail. No scanner uses a 60-second cadence anymore.

**Stop loss:** the four active fixed-stop premium scanners (`sma9`,
`sma9_high`, `sma9_trail`, `sma9_high_trail`) and the staged `sma9_5min` copy
use a fixed stop at **entry premium × 0.95**
for both CE and PE — 5% below the entry price, because every leg is bought long
and a falling premium is the loss (`STOP_LOSS_5PCT`). They share the same trail:
activate at +5 pts (stop → entry), ratchet `peak − 5` on the premium high-water
mark (the same rule for CE and PE, because both are bought long and profit when
premium rises), one-time breakeven lock at +6 (stop ≥ entry + 2). The trail exit
is evaluated first; the 5% stop is the additional floor. `sma9_atr`
replaces the 5% floor with an ATR-scaled stop
(`STOP_LOSS_ATR`, filled at the live LTP). The v1.1.0 ATR scanner drops
the fixed +5 activation / BE lock and trails by the frozen ATR distance.
`sma9_atr` gates new entries on the 15-minute-refreshed NIFTY spot regime
(§5.6).

The seven premium scanners use `/opt/tradingai/database/<key>.db`,
`/api/<slug>/` (slug = key with `_` → `-`) and
`https://tradingai.in/live/<slug>/`. The staged `sma9_5min` follows the same
isolation contract with slug `sma9-5min`, DB `sma9_5min.db` and service user
`sma95min`.

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

### 5.1a 5-minute poll copy (`sma9_5min`, staged)

```
signal = prev.close > SMA9 AND forming.open > SMA9
poll   = aligned 5m boundary +10 s
entry  = paper BUY at round(LTP, 2)
exit   = same trail-first, then 5% stop as sma9, sampled once per 5m poll
```

This is an exact rule copy of `sma9` apart from cadence and identity.
The entry signal, 5% floor, 5-point trail activation/ratchet, one-time BE lock,
09:20–15:15 window, one-entry-per-candle guard, nearest-expiry ATM selection,
CE/PE independence and SQLite state model are unchanged. Only the runner's
sleep target changes: it waits until the next 5-minute boundary plus a 10-second
publication offset. Consequently the stop and trail are observed once per bar
instead of every 5 seconds; intrabar breaches are filled at the next sampled
LTP.

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

### 5.4 Trail (`*_trail`)

Each trail scanner is **fully self-contained**: it evaluates its own entry
signals from live 5-minute option candles and owns both entry and exit. No
dependency on any base scanner API.

Entry signals (per option, CE and PE evaluated independently):

- `sma9_trail`: `prev.close > SMA9` **and** `forming.open > SMA9`
- `sma9_high_trail`: `prev.close > SMA9` **and** `forming.open > SMA9`
  **and** `LTP > prev.candle.high`

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

### 5.6 ATR-stop scanner (`sma9_atr`)

Added 2026-11-18, first live day 2026-11-19; upgraded to **v1.1.0** on
2026-11-20. It is an isolated clone of `sma9` with three changes: a daily
spot-regime entry gate, an ATR-scaled initial stop, and an ATR-width trail with
the fixed +5 activation and BE lock removed.

**Entry** — SMA9 signal as `sma9`: previous completed 5m candle close > SMA9
**and** forming candle open > SMA9; paper BUY at the live LTP, ATM CE/PE,
long only, entry window 09:20–15:15. In v1.1.0 the signal is additionally
gated by the daily regime:

```
regime from COMPLETED 5m NIFTY spot candles, refreshed every 15 minutes:
  BULLISH: price > vwap and price > ema9 and ema9 rising  -> CE entries only
  BEARISH: price < vwap and price < ema9 and ema9 falling -> PE entries only
  NEUTRAL: mixed / insufficient data / spot-candle error  -> no entries
```

`vwap` uses candle volume when present and the typical-price average when the
index candles carry zero volume. `ema9` uses all completed spot history. The
gate is never applied to exits, and `/api/sma9-atr/status` reports `regime`,
`entry_allowed` and `gate_reason`.

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

**Trail (v1.1.0):** the `distance` fixed at entry is reused as the only trail
width. It activates once `hwm > entry` (no fixed +5 threshold), ratchets only
upward as `hwm - distance`, and has **no breakeven lock**. The exit still fills
at the live LTP (`TRAIL_STOP_EXIT`). Before price is above entry the initial
ATR stop is the only exit, so a loss is never mislabelled as a trail exit.
No time-based exit.

**Why:** on 19–20 Nov 2026 CE PnL across the fleet was strongly positive while
PE PnL was negative every day, and 89–95% of fixed 5-point trail exits were
small winners averaging only 4–6 points. The gate removes the wrong side of the
day; the ATR trail lets winners run at the option's own volatility width.

**Isolation:** own code `/opt/tradingai/sma9_atr_scanner/`, DB
`database/sma9_atr.db`, tables `sma9_atr_trades` / `sma9_atr_open_positions` /
`sma9_atr_scan_state`, systemd `tradingai-sma9-atr-scanner.service`, log
`logs/live_sma9_atr_scanner.log`, report key `sma9_atr`. The service runs as
the existing `sma9` user but shares no code, DB, state or unit with `sma9`.
No other scanner was changed by v1.1.0.

**Persisted state:** `atr_at_entry`, `stop_price`, `stop_k`,
`stop_distance_pct`, `stop_source`, `trail_distance`, `hwm`, `trail_stop`,
`be_locked`. `be_locked` is retained only for v1.0.0 restore compatibility; it
is no longer used. `init_db()` adds `trail_distance` to existing tables
idempotently. A same-day restart resumes the exact stop, trail distance and
high-water mark; a position from an earlier session is closed at the current
LTP (`STALE_RECOVERY_EXIT`) rather than carried.

**Pre-open operations:** the unit is `enabled` at boot and uses
`Restart=always`, and it is in the `ALL_UNITS` list of
`/opt/tradingai/refresh_token.sh`, so the daily token refresh restarts it with
the new token exactly like the other scanners. The token is read once at
process start, so a refresh without a restart would leave it on the expired
token. Three checks cover the change:

```bash
python3 /opt/tradingai/sma9_atr_scanner/tests/test_sma9_atr_engine.py  # offline engine + regime
python3 /opt/tradingai/sma9_atr_scanner/ops/dryrun_market_open.py      # fake clock/feed, temp DB
python3 /opt/tradingai/sma9_atr_scanner/ops/real_feed_check.py         # real Kite data, writes nothing
```

The tests cover the ATR trail and regime classification; the dry run drives the
deployed runner through pre-market → 09:00 scan start → BULLISH gate at 09:20 →
CE entry → stop at LTP → re-entry → restart recovery; the real-feed check
verifies the instrument dump, nearest expiry, ATM CE/PE contracts, quotes,
candles, SMA9 evaluation, ATR stop preview and spot regime.

### 5.7 SMA9 ATR scanner, 5-second poll (`sma9_slope_atr`) — retired

Retired on 2026-11-24. Its only open paper position was closed at the sampled
LTP (`RETIREMENT_PAPER_CLOSE`, P&L 0.00) before the service, code, DB, API
namespace and page were removed. The archive is
`/opt/tradingai/archives/sma9_slope_atr_20261124/`; `/api/sma9-slope-atr/*`
and `/live/sma9-slope-atr/` now return 404. See `docs/scanners/retired.md`.

### 5.8 SMA9 + ADX scanner (`sma9_adx`)

`sma9_adx` is an isolated copy of the 5-second SMA9 premium scanner with two
behavioural changes, both evaluated on the bought option's own **completed**
5-minute candles (the forming bar is always excluded):

- **Entry (both required, CE and PE alike):** previous completed candle close
  > SMA9 **and** Wilder ADX(14) > 30 **and** +DI > -DI. There is no forming-open gate and no
  LTP > SMA9 confirmation gate; `confirmation` is reported as informational
  only.
- **Exit:** initial stop = entry premium - 5%; once the premium rises, the
  stop ratchets to HWM - 5% and never ratchets down. A losing trade always
  exits on the 5% initial stop, never on the trail. There is **no**
  candle-close or time-based exit.

ADX is computed from completed option-premium 5m bars with Wilder smoothing
(+DI/-DI, smoothed TR, smoothed DX, then smoothed ADX). It returns `None` until
at least `2 * ADX_PERIOD` completed bars are available, so no entry is possible
before there is enough history.

**Isolation:** own code `/opt/tradingai/sma9_adx_scanner/`, DB
`database/sma9_adx.db`, tables `sma9_adx_trades` /
`sma9_adx_open_positions` / `sma9_adx_scan_state`, systemd
`tradingai-sma9-adx-scanner.service`, log
`logs/live_sma9_adx_scanner.log`, user `sma9adx`, API
`/api/sma9-adx/*`, page `/live/sma9-adx/`, report key `sma9_adx`
(label `SMA9 ADX`, from 2026-11-22). The status payload carries `adx_period`
and `adx_threshold`, plus per-option `plus_di` / `minus_di`; open positions and closed trades persist `adx` /
`adx_value` so a restart resumes the same signal and stop.

### 5.9 Live dashboard strategy-rules panel

All seven live scanner pages (`sma9`, `sma9-high`, `sma9-trail`,
`sma9-high-trail`, `sma9-atr`, `sma9-5min`, `sma9-adx`) render a
**Strategy rules (live)** panel.
The panel is display-only: it never contains prices, quotes, signals or any
live trading state.

- **Single display source:** `frontend/live/strategy_rules.json`. Each key in
  `scanners` matches the page key above and provides only `entry`, `exit` and
  `scope` lists. The public manifest and the rendered panel contain no file
  paths, service names or other source information. Pages fetch
  `/live/strategy_rules.json` with `cache: 'no-store'` and render the matching
  key.
- **If the file is missing or the key is absent**, the panel shows an explicit
  "Strategy rules unavailable" warning pointing back to this document. It
  never invents or silently reuses another scanner's rules.
- **Change control:** whenever an entry or exit condition (or its constants,
  cadence or instrument selection) changes in a scanner engine, update the
  matching manifest entry **in the same commit and deployment**: correct the
  `entry` / `exit` / `scope` bullets and bump `updated_at`, then verify the
  page shows the new text. The scanner engine remains the authoritative
  definition of the rules; this manifest is its human-readable mirror.
- Deployment path: `/opt/tradingai/frontend/live/strategy_rules.json` (served
  as a static file by nginx with `Cache-Control: no-store`).

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
| NO-SMA / prev-high | `prev_high`, `breakout` (retired `no_sma` and `no_sma_trail`; archive DBs only) |
| Trail | `prev_high`, `breakout`, and `hwm`, `stop`, `be_locked` in `open_positions`; `consumed_base_trades` is a legacy artefact and is not used by current logic |
| ATR stop (`sma9_atr`) | `atr_at_entry`, `stop_price`, `stop_k`, `stop_distance_pct`, `stop_source`, `trail_distance` (ATR scanner). |

`exit_reason` is `STOP_LOSS_5PCT` or `TRAIL_STOP_EXIT` for the four fixed-stop
premium scanners, and `STOP_LOSS_ATR` or `TRAIL_STOP_EXIT` for the two ATR
premium scanners.
There is no candle-close, minute-10, or session-end reason on any of them.
`pnl_points = exit_price - entry_price` (BUY-only, one lot notional is not
applied).

Database ownership must be `<service-user>:ubuntu` with mode `664`; the
service user must be able to `BEGIN IMMEDIATE`.

---

## 7. API and dashboards

### 7.1 API

The premium-scanner namespaces expose the following read-only endpoints
(the four older scanners serve all nine; the three newer ones omit
`legacy-audit`, as detailed below):

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

The full 9-endpoint set is served for `sma9`, `sma9-high`, `sma9-trail` and
`sma9-high-trail`. The two newer scanners (`sma9-atr`, `sma9-5min`) expose the same set
**except `legacy-audit`** (8 endpoints): `signals`, `trades`,
`daily-summary`, `scanner-status`, `live-status`, `recent-trades`, `today`,
`open-positions`. They read `database/sma9_atr.db` and
`database/sma9_5min.db` respectively; the scanner is the only writer. The `sma9_5min` copy has the same 8-endpoint set deployed at
`/api/sma9-5min/*`, reading `database/sma9_5min.db` read-only; its scanner
service is deployed and running.

The retired `no-sma` and `no-sma-trail` endpoints remain so the archived pages
still load.

`atm`, `sma9_avg`, and `green15` are retired and return **404**.

Quick health check:

```bash
curl -sk -H 'Host: tradingai.in' \
  https://127.0.0.1/api/sma9/scanner-status
```

### 7.2 Dashboards

| Scanner | Dashboard |
|---|---|
| sma9 | https://tradingai.in/live/sma9/ |
| sma9_5min | https://tradingai.in/live/sma9-5min/ (deployed, scanner running) |
| sma9_adx | https://tradingai.in/live/sma9-adx/ (deployed, scanner running) |
| sma9_atr | https://tradingai.in/live/sma9-atr/ |
| sma9_high | https://tradingai.in/live/sma9-high/ |
| sma9_trail | https://tradingai.in/live/sma9-trail/ |
| sma9_high_trail | https://tradingai.in/live/sma9-high-trail/ |

All seven dashboards show **Last Closed Spot** and **Closed-Bar ATM** cards in
addition to the live pair, which is labelled **NIFTY LTP (live)** /
**ATM Strike (live)** to distinguish the broker's last-traded index price from
the completed 5m close. These come from the most recent *completed*
NIFTY 5-minute candle, not the current LTP. The read-only gateway serves NIFTY
50 index history on NSE token **26000** (mStock's index token, distinct from
Zerodha's 256265), so every scanner reads the real index bar directly. The API
reports `last_closed_spot_source: nifty_index_5m_close`, with the bar timestamp
in `last_closed_candle_start`. The CE/PE closes are no longer used for this
calculation and are reported as `null`.

The earlier `atm_ce_pe_parity_5m_close` reconstruction was removed because
mStock option history can contain frozen, zero-volume bars. On 2026-11-20 those
bars implied a spot near 25739 while the real index closed at 25800.6, so the
parity cards were wrong. Note also that mStock's live index **quote** can be
stale: on 2026-11-21 its `last_price` was 25461.35 even though its own `ohlc.close`
and the index history both showed 25800.6. While the market is closed, scanners substitute the real index close for the
live pair when the broker quote is more than 50 points away from it, so both
card pairs agree on the actual last traded level. The API exposes this as
`spot_source: index_close_fallback` (normally `broker_quote`); once the market
opens, the live pair reverts to the broker quote.

All eight active dashboards fetch their live ATM strike and both option premiums
from the read-only `GET /api/live-atm?scanner=<key>&expiry=<YYYY-MM-DD>`
endpoint instead of the scanner heartbeat. That endpoint re-quotes NIFTY 50 and
the two ATM option symbols through the broker-agnostic gateway, applies the
same closed-market divergence guard described above, and returns `source`,
`spot_source`, `quote_age_seconds`, per-leg `symbol`/`ltp`/`age_seconds` and a
`stale` flag. The heartbeat row is still used for completed-candle indicators
(SMA9, ADX, ATR, previous close) and for trade history; those are deliberately
bar-based, not live quotes.

Every active scanner has a button on `https://tradingai.in/live/scalp/` — the
buttons are `sma9`, `sma9-5min`, `sma9-adx`, `sma9-atr`, `sma9-high`,
`sma9-trail`, `sma9-high-trail`. All seven
active pages share the same dark theme,
badge/table styling, a `Back to Launcher` link, and auto-refresh without a page
reload every 5 s. The `sma9-atr` page shows
the entry ATR(14), the fixed ATR stop, the live ATR trail distance and an ATR
stop preview for each ATM option; legacy BE-lock fields remain in the payload
for compatibility but are always false and unused in v1.1.0.
The retired
`green15`, `no-sma` and `no-sma-trail` pages remain on disk but are unlinked
from the launcher.

---

## 8. Operations runbook

### 8.1 Daily pre-open

```bash
# 1. Token validity (read-only)
cat /opt/tradingai/logs/token_status.txt
systemctl list-timers tradingai-token-check.timer

# 2. If TOKEN_INVALID, refresh before 09:15
sudo /opt/tradingai/refresh_token.sh <REQUEST_TOKEN>
```

`refresh_token.sh` (Zerodha path) exchanges the token, then restarts **all 8
units**: the API and the 7 paper scanners. On the VM the
active broker is mStock, whose session is refreshed with `mstock_session.py`
(TOTP/OTP) instead. Every scanner obtains market data through the long-lived
gateway daemon; a broker-session change must be applied to the gateway, which
validates token freshness on every call and reports an error rather than using
a stale token.

```bash
# 3. All scanners + API active
systemctl is-active tradingai-api \
  tradingai-sma9-scanner tradingai-sma9-atr-scanner \
  tradingai-sma9-high-scanner \
  tradingai-sma9_trail-scanner \
  tradingai-sma9_high_trail-scanner

# 4. Instrument load completed ("ready" in each log)
for f in /opt/tradingai/logs/live_*scanner.log; do
  printf '%-40s %s\n' "$(basename "$f")" "$(grep 'ready$' "$f" | tail -1)"
done
```

### 8.2 Restart

Restart scanners in staggered waves (3 s apart) so instrument downloads do
not hit Kite at once:

```bash
for u in tradingai-sma9-scanner tradingai-sma9-atr-scanner \
         tradingai-sma9-high-scanner \
         tradingai-sma9_trail-scanner \
         tradingai-sma9_high_trail-scanner; do
  sudo systemctl restart "$u"
  sleep 3
done
```

### 8.3 Health checks

```bash
# service state / restart count
systemctl show tradingai-sma9-scanner -p ActiveState -p NRestarts

# errors (auth, rate limit, DB, TLS, tracebacks)
sudo journalctl --since '09:00' --no-pager \
  | grep -iE 'Incorrect api_key|Too many requests|readonly database|SSLEOF|Traceback'

# all remaining premium-scanner APIs return 200
for k in sma9 sma9-atr sma9-high \
         sma9-trail sma9-high-trail; do
  printf '%s=%s ' "$k" "$(curl -sk -o /dev/null -w '%{http_code}' \
    -H 'Host: tradingai.in' "https://127.0.0.1/api/$k/scanner-status")"
done; echo

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

### 8.5 Code locks (7 active premium scanner trees)

The 7 active premium scanner directories are protected: `root:root`, files mode
`444`, directories `555`. The original base/HIGH families (`sma9`, `sma9_high`)
and their trail copies (`sma9_trail`, `sma9_high_trail`) additionally use
`chattr +i` on every file and directory, with a SHA256 `MANIFEST.sha256` and an
integrity timer. `sma9_atr` is installed
`root:root`, files `444`, directories `555`, without `chattr +i` or an
integrity timer.

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
disk (it just no longer runs).

### 8.6 Rate-limit hygiene

- Base plain scanners (`sma9`, `sma9_atr`):
  **2 quote calls per tick** — one spot-only refresh for ATM selection, plus
  one batched spot+CE+PE quote. Offset 0. Both tick once every 5 seconds.
- Base HIGH scanner (`sma9_high`): same **2-call** pattern, offset 2.4 s.
- Trail scanners (`sma9_trail`, `sma9_high_trail`): self-contained since the
  2.1.0 rewrite — **1 batched spot+CE+PE quote per tick** plus historical
  candles only when a new 5-minute candle appears (extra quote calls only on a
  failed batch or a newly missing contract). Offsets 1.2 s / 3.0 s. They no
  longer make a base-status HTTP call.
- Historical candles are fetched only when a new 5-minute candle appears (or
  at exit), never on every poll.
- Kite limits: quotes ≈1 req/s, historical ≈3 req/s per API key.
- If `Too many requests` appears in logs, check for overlapping restarts or a
  runaway historical fetch before changing offsets.

### 8.7 Zerodha connectivity check

Read-only, writes nothing, places no order:

```bash
# full path: auth -> NFO instruments -> spot + ATM CE/PE quotes -> 5m candles
sudo runuser -u ubuntu -g ubuntu -- \
  python3 /opt/tradingai/scripts/ops/kite_connectivity_probe.py

# every scanner user: credentials file readable + token accepted
for u in sma9 sma95min sma9high sma91m sma9slopeatr sma9trail sma9trailhigh; do
  sudo runuser -u "$u" -g ubuntu -- \
    python3 /opt/tradingai/scripts/ops/kite_connectivity_probe.py --light
done
```

`sma9` covers both `sma9` and `sma9_atr` (same service user). `--light` calls
only `profile()` so the loop stays inside the quote limit. A green probe plus
today's `Loaded <n> NIFTY option instruments` line in each scanner log is the
full connectivity evidence; instrument load alone already requires a valid
token.

---

## 9. Safety guarantees

- **Paper only (seven scanners).** No broker order path exists in any paper
  scanner. Verify with:

  ```bash
  sudo grep -rn 'place_order\|order_id' /opt/tradingai/*_scanner/app/ \
    && echo 'FOUND — investigate' || echo 'clean: no broker orders'
  ```

- **BUY only.** CE and PE are long-only; there is no short/sell-to-open path.
- **Fixed 5% stop on the four active fixed-stop scanners and staged
  `sma9_5min`.** Every position exits at `round(entry × 0.95, 2)` if LTP falls
  that far (`STOP_LOSS_5PCT`); the trail stop is the preferred, higher exit and
  is evaluated first. `sma9_atr` uses an ATR-scaled stop
  instead (see §5.6), filled at the live LTP. `sma9_atr` v1.1.0 also trails only at
  that ATR distance and gates entries on the daily spot regime; exits are never
  gated.
- **No time-based exit** on any scanner; positions hold across candles and
  overnight until the trail or ATR/5% stop fires.
- **Secrets** live only in root-owned gateway credential files on the VM; they
  are never read by a scanner and are never committed.
- **State survives restarts** via `open_positions` and `scan_state`, including
  trail `hwm`/`stop`.

### 9.1 Isolated `sma9_live` execution service (mStock Type A)

`sma9_live` is a **separate service**, not a modified paper scanner. The paper
`sma9` tree, DB (`sma9.db`), service user, API namespace, page and gateway
mapping are unchanged. The local scaffold defaults to `dry_run`; the deployed
armed unit uses the verified mStock Type A order contract.

| Property | Value |
|---|---|
| Code | `scripts/sma9_live_scanner/app/` |
| Strategy id / version | `sma9_live` / `1.0.0` |
| Database | `/opt/tradingai/database/sma9_live.db` (tables `sma9_live_*`) |
| Service user / unit | `sma9live` / `tradingai-sma9-live-scanner` |
| Gateway alias | `broker-gateway use --scanner sma9live --broker mstock` |
| Default executor | `dry_run` — no broker call is made |
| Deployed executor | `mstock` via root-owned gateway (`BROKER_GATEWAY_ORDERS_ENABLED=true`) |
| Order API | Type A `POST /orders/reg`, form-encoded; status via `GET /orders` |

Risk guards enforced before any BUY: kill switch (`SMA9_LIVE_KILLED` or the
kill file), daily order cap (`SMA9_LIVE_MAX_ORDERS_PER_DAY`, default 4),
one open position per leg, and a protective price collar
(`SMA9_LIVE_PRICE_COLLAR_PCT`, default 1%). The default order quantity is one
NIFTY lot (`SMA9_LIVE_LOT_SIZE=75`). Exits are never blocked by these guards.

Every entry and exit writes an append-only `sma9_live_orders` ledger row keyed
by a deterministic `client_order_id`, so a retry cannot duplicate an order.
The executor result (`status`, `broker_order_id`) is written back to that row.
Real execution additionally requires **both**
`SMA9_LIVE_ORDERS_ENABLED=true` and `SMA9_LIVE_ARM_REAL_ORDERS=ARMED`, plus the
daemon opt-in above. The `MStockOrderExecutor` fails closed on any missing
flag, invalid symbol, gateway error or missing broker order id, and posts a
limit order exactly once (no implicit retry that could duplicate a fill).

Read-only API namespace: `/api/sma9-live/*` (including `/orders`); page:
`/live/sma9-live/`. Both are read-only and publish no source paths, keys or
credentials.

No credentials, keys or OTP/TOTP values are handled by the service; token
refresh remains a manual operator step.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Incorrect api_key or access_token`, zero trades | broker session expired or gateway still on a stale token | check `sudo broker-gateway status`; refresh the active broker session (`sudo /usr/local/sbin/mstock_session.py --mode totp`, or `refresh_token.sh <REQUEST_TOKEN>` for Zerodha) and verify with `sudo broker-gateway probe` |
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
| GitHub repo | `vedurada/tradingai-lightweight`, branch `feature/zerodha-paper-trading` |
| Newer scanner sources (git-tracked) | `scripts/sma9_atr_scanner/`, `scripts/sma9_5min_scanner/` (staged) |
| Connectivity probe | `scripts/ops/kite_connectivity_probe.py` |
| Per-scanner docs | `docs/scanners/` (this repo) |
| Master doc | `SCANNERS.md` (this file) |
| Local build workspace | `/Users/satya/sma9_work/` — base/HIGH/ATM/GREEN15 builders, trail build, and analysis scripts |
| Trail template | `/Users/satya/sma9_work/trail_build/build_trail.py` (keeps the 09:20–15:15 window) |
| Base HIGH builder | `/Users/satya/sma9_work/high_build/build_high.py` |
| VM deployment | `/opt/tradingai/<key>_scanner/` + `database/` + `logs/` + systemd units |

The older premium scanner trees (`sma9`, `sma9_high`, `sma9_trail`,
`sma9_high_trail`) are maintained in the local build workspace and deployed to
the VM; only the three newer scanner trees are tracked in this repository. The
retired `sma3`/`sma20` families and their branches are no longer part of the
active source set. The 09:20–15:15 entry window is present in all 7 deployed
premium scanner files and in the trail build template.

---

## 12. Document map

| Document | Covers |
|---|---|
| `SCANNERS.md` (this file) | everything: requirements, dependencies, common config, matrix, operations |
| `requirements.txt` | canonical Python requirements |
| `docs/scanners/README.md` | index + logical one-line description of each active scanner |
| `docs/scanners/<key>.md` | per-scanner entry/exit rules, constants, runtime, commands |
| `docs/scanners/retired.md` | retired scanners, archives and replacement mapping |
| `/opt/tradingai/TOKEN_REFRESH.md` | daily Kite token runbook |
| `<key>_scanner/docs/SECURITY_AND_OPERATIONS.md` | base-scanner lock policy (base 7 only) |
