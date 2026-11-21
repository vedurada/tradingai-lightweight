# TradingAI Paper Scanners — Master Documentation

Complete reference for the 8 paper scanners running on the TradingAI VM, plus
the repository-ready `sma9_5min` copy that has not yet been deployed:
7 BUY-only NIFTY option-premium scanners plus `pattern_scanner` are active;
`sma9_5min` is a ninth, staged identity. Five option scanners use a fixed 5%
stop; `sma9_atr`, `sma9_5s_atr`, `sma9_1min_poll` and
`pattern_scanner` use a volatility-scaled **premium** ATR stop and ATR-only trail
(no +5 activation and no breakeven lock). `sma9_atr` also gates entries on a
daily NIFTY spot regime; `sma9_5s_atr` additionally requires a rising SMA9.
`pattern_scanner` detects patterns on NIFTY spot candles but exits on the
bought option's premium ATR. Seven active scanners poll every 5 seconds;
`pattern_scanner` alone polls on an aligned 5-minute cadence and evaluates exits
from completed 5m option OHLC bars so live matches the 5m backtest. The staged
`sma9_5min` uses the same aligned 5m cadence but keeps `sma9`'s sampled-LTP
stop/trail rules.

`green15`, `no_sma` and `no_sma_trail` are retired: stopped, disabled on boot,
removed from the launcher (and `no_sma` / `no_sma_trail` from the performance
report); their slots are not restarted. `green15`'s API namespace returns 404.
The code trees and DBs remain on disk as archives.

> **Paper trading only.** No scanner can place a broker order. There is no
> `place_order` call, no order id, and no broker write path anywhere in this
> stack. Every fill is simulated in SQLite at the sampled option LTP; the
> `pattern_scanner` exit fill is the documented conservative completed-5m OHLC
> proxy shared with its backtest.

---

## 1. What runs on the box

| # | Scanner key | Family | Entry logic | Exit logic |
|---|---|---|---|---|
| 1 | `sma9` | Base SMA | prev close > SMA9 **and** forming open > SMA9 | trail stop, then 5% stop; otherwise hold |
| 2 | `sma9_high` | HIGH | prev close > SMA9 **and** forming open > SMA9 **and** LTP > prev candle high | trail stop, then 5% stop; otherwise hold |
| 3 | `sma9_1min_poll` | SMA9 1-min poll identity | prev close > SMA9 **and** forming open > SMA9, polled every 5s | ATR trail, then ATR-scaled stop (both fill at the live LTP); otherwise hold |
| 4 | `sma9_trail` | Trail | self-contained entry (prev.close>SMA9 & forming.open>SMA9) + trail exit | trail stop, then 5% stop; otherwise hold |
| 5 | `sma9_high_trail` | Trail | self-contained entry (prev.close>SMA9 & forming.open>SMA9 & LTP>prev.high) + trail exit | trail stop, then 5% stop; otherwise hold |
| 6 | `sma9_5s_atr` | SMA9 ATR (5s) | prev close > SMA9 **and** forming open > SMA9 **and** SMA9 > prior SMA9, polled every 5s | ATR trail, then ATR-scaled stop (both fill at the live LTP); otherwise hold |
| 7 | `pattern_scanner` | Pattern | bullish/bearish patterns on NIFTY SPOT 5m candles, polled at 5m boundary +10 s | premium ATR trail, then premium ATR stop, from completed 5m option OHLC bars; otherwise hold |
| 8 | `sma9_atr` | ATR stop + daily regime | prev close > SMA9 **and** forming open > SMA9 **and** regime allows that option | ATR trail, then ATR-scaled stop (both fill at live LTP); otherwise hold |

A ninth identity, `sma9_5min`, is staged in git: it is an isolated copy of
`sma9` whose only behavioural change is an aligned 5-minute poll. It is not part
of the active VM set until deployed.

There is **no time-based exit** on any of the 8 scanners: if neither the trail
nor the stop fires, the position stays open across candles (including overnight)
until one of them does. `pattern_scanner` checks its premium stops once per
completed 5m option OHLC bar; the other 7 check on 5-second sampled LTPs.
`pattern_scanner` uses premium ATR for both the initial stop and the trail (see
§5.5).
`sma9_atr` adds a daily spot-regime entry gate and replaces both the initial
stop and the trail with the frozen ATR distance (see §5.6);
`sma9_5s_atr` scales both the stop and the trail and adds a rising-SMA9
filter (see §5.7). `sma9_1min_poll` keeps its original identity and A+B entry
but now uses the same ATR stop/trail at 5-second cadence (see §5.3). No scanner
has a 60-second poll anymore.

Each of the 7 premium scanners is a **fully independent stack**: own code
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
| Active broker | selected by `BROKER_GATEWAY_SCANNER` / `broker-gateway use` (VM deployment maps all 8 scanners, the API and `pattern_scanner` to `mstock`; `zerodha` remains the code default) |
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
| `PATTERN_POLL_SECONDS` | `300` | `pattern_scanner` only: aligned 5m poll at boundary + 10 s |
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
a pre-open quote can never fire a trail or stop. `pattern_scanner` ignores all
ticks before 09:15 in its candle buffer and ignores option bars starting before
09:15 in its premium exit manager, so no synthetic pre-open candles are created
and no pre-open exit can fire.

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
`pattern_scanner` is the exception: its **entry signals** come from completed
NIFTY spot 5-minute candles, while **all exits** are managed on the bought
option's premium. NIFTY spot is also used to select the ATM strike.

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
that carry their engine in the tree: `sma9_atr`, `sma9_5s_atr` and
`sma9_1min_poll` use only that path (they rely on the system Python for
`kiteconnect`).

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
the API at the same instant. `pattern_scanner` does not use this offset; its
runner polls once per 5m boundary +10 s (`POLL_INTERVAL_SEC = 300`,
`POLL_OFFSET_SEC = 10`). The staged `sma9_5min` copy uses the same boundary
offset with `POLL_SECONDS = 300` and `POLL_OFFSET_SEC = 10`.

| Key | Strategy id | Strategy type | Ver | SMA | Trail / activate | off | User | systemd unit |
|---|---|---|---|---|---|---|---|---|
| `sma9` | `sma9_only` | `SMA9_BUY_ONLY` | 2.7.0 | 9 | — | 0 | `sma9` | `tradingai-sma9-scanner` |
| `sma9_5min` (staged) | `sma9_5min` | `SMA9_5MIN_BUY_ONLY` | 1.0.0 | 9 | — | 5m +10 s | `sma95min` | `tradingai-sma9-5min-scanner` |
| `sma9_atr` | `sma9_atr` | `SMA9_ATR_STOP_BUY_ONLY` | 1.1.0 | 9 | ATR / none | 0 | `sma9` | `tradingai-sma9-atr-scanner` |
| `sma9_high` | `sma9_high` | `SMA9_HIGH_BUY_ONLY` | 1.8.0 | 9 | — | 2.4 | `sma9high` | `tradingai-sma9-high-scanner` |
| `sma9_1min_poll` | `sma9_1min_poll` | `SMA9_1MIN_POLL_BUY_ONLY` | 1.1.0 | 9 | ATR / none | 0 | `sma91m` | `tradingai-sma9-1min-poll-scanner` |
| `sma9_trail` | `sma9_trail` | `SMA_BUY_ONLY` | 2.1.0 | 9 | 5.0 / 5.0 | 1.2 | `sma9trail` | `tradingai-sma9_trail-scanner` |
| `sma9_high_trail` | `sma9_high_trail` | `SMA_HIGH_BUY_ONLY` | 2.1.0 | 9 | 5.0 / 5.0 | 3.0 | `sma9trailhigh` | `tradingai-sma9_high_trail-scanner` |
| `sma9_5s_atr` | `sma9_5s_atr` | `SMA9_5S_ATR_STOP_BUY_ONLY` | 1.1.0 | 9 | ATR / ATR | — (5s) | `sma95satr` | `tradingai-sma9-5s-atr-scanner` |
| `pattern_scanner` | — | — | — | — | ATR / none | 5m +10 s | `ubuntu` | `pattern-scanner-live` |

Seven scanners poll every 5 seconds; `pattern_scanner` polls once per 5-minute
boundary +10 s and uses completed 5m option OHLC bars for exits. The staged
`sma9_5min` also polls once per 5-minute boundary +10 s, but keeps `sma9`'s
LTP-sampled stop/trail. No scanner uses a 60-second cadence anymore.

**Stop loss:** the four active fixed-stop premium scanners (`sma9`,
`sma9_high`, `sma9_trail`, `sma9_high_trail`) and the staged `sma9_5min` copy
use a fixed stop at **entry premium × 0.95**
for both CE and PE — 5% below the entry price, because every leg is bought long
and a falling premium is the loss (`STOP_LOSS_5PCT`). They share the same trail:
activate at +5 pts (stop → entry), ratchet `peak − 5` on the premium high-water
mark (the same rule for CE and PE, because both are bought long and profit when
premium rises), one-time breakeven lock at +6 (stop ≥ entry + 2). The trail exit
is evaluated first; the 5% stop is the additional floor. `sma9_atr`,
`sma9_5s_atr` and `sma9_1min_poll` replace the 5% floor with an ATR-scaled stop
(`STOP_LOSS_ATR`, filled at the live LTP). All three v1.1.0 ATR scanners drop
the fixed +5 activation / BE lock and trail by the frozen ATR distance.
`sma9_atr` gates new entries on the 15-minute-refreshed NIFTY spot regime
(§5.6); `sma9_5s_atr` has no regime gate but requires a rising SMA9 (§5.7);
`sma9_1min_poll` keeps A+B only (§5.3).

**`pattern_scanner` exception:** its *entry signal* comes from NIFTY SPOT pattern
detection, but its stop/trail levels are derived from the **bought option's
premium ATR(14)**, exactly like the ATR premium scanners. Initial stop =
`0.70 × ATR`, clamped to 5–30% of the entry premium (10% fallback when ATR is
unavailable). The trail uses the same frozen distance and ratchets only upward.
Exits are managed from the position's own completed 5m option OHLC bars via the
shared `evaluate_bar()` helper, so live matches the backtest proxy; NIFTY spot
no longer drives exits.

The seven premium scanners use `/opt/tradingai/database/<key>.db`,
`/api/<slug>/` (slug = key with `_` → `-`) and
`https://tradingai.in/live/<slug>/`. The staged `sma9_5min` follows the same
isolation contract with slug `sma9-5min`, DB `sma9_5min.db` and service user
`sma95min`. `pattern_scanner` is the exception: it
persists to `/opt/tradingai/database/tradingai.db` in its own
`pattern_scanner_*` tables and publishes status through its service/status file
rather than a per-scanner namespace.

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

### 5.3 SMA9 5s poll identity (`sma9_1min_poll`)

```
signal = prev.close > SMA9 AND forming.open > SMA9
poll   = every 5 seconds, aligned to the 5-second boundary
entry  = paper BUY at round(LTP, 2)
exit   = ATR trail, then ATR-scaled stop (`STOP_LOSS_ATR`),
         both filled at the ACTUAL live LTP;
         no candle-close or time-based exit
```

The identity (id, DB, service, user, API and page) is unchanged from the
original 60-second scanner. v1.1.0 only changes cadence and exits: the ATR stop
is `clamp(0.70 × ATR14, 5%, 30% of entry)` and the trail is `peak − distance`
with no fixed +5 activation and no breakeven lock. Entry is still A+B only: no
LTP gate, no rising-SMA9 filter and no regime gate. The scanner refuses to
treat the previous completed candle as forming when the exchange has not
published the current 5-minute candle yet. At most one entry per 5-minute
candle; entry window 09:20–15:15.

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

Pattern-based entries on NIFTY SPOT 5m candles with **premium ATR(14) exits**
(no fixed spot stop, no spot trail, no 15:15 square-off). This is the only
scanner on an aligned 5-minute live cadence, and its exits use the same completed
5m option OHLC bars as the backtest.

- **Signal source:** NIFTY SPOT 5-minute candles (completed candles only).
- **Live cadence:** one poll at each 5m boundary +10 s (`:00:10`, `:05:10`, …);
  `POLL_INTERVAL_SEC = 300`, `POLL_OFFSET_SEC = 10`. The other seven scanners
  keep their 5s cadence.
- **Entry:** any of ~37 bullish or ~37 bearish candlestick patterns on the completed SPOT candle.
  - **Bullish** pattern → **LONG ATM CE** (buy CE, weekly expiry)
  - **Bearish** pattern → **LONG ATM PE** (buy PE, weekly expiry)
- **Position type:** long-only on both sides — there is **no short CE and no short PE**.
  A bullish SPOT signal goes long CE; a bearish SPOT signal goes long PE.
- **Entry price:** the exact option's LTP sampled at the poll that closes the spot
  candle — not the spot close, and never a stale or opposite-leg quote. Quotes
  older than `MAX_QUOTE_AGE_SEC` (20s) are rejected, so a missed quote skips the
  entry instead of inventing a price.
- **Entry timestamp:** the actual poll time at which the trade was placed, not
  the signal candle's start.
- **Entry timing:** no new entries at or after 15:15 IST.
- **One per key:** at most one active position per `pattern_name:instrument`.
- **Entry bar skip:** a position entered at a bar-close poll is first managed on
  the next poll's completed bar, never on its own entry bar.

**Exit:** premium ATR only, evaluated once per aligned poll from the **previous
completed 5-minute OHLC bar** of the position's own option. `evaluate_bar()` is
shared by the live runner and backtest replay. Sampled option LTPs are used for
entries only; NIFTY spot ticks never manage an exit. Both long CE and long PE
profit when the premium rises, so direction does not change the arithmetic.

- **ATR at entry:** ATR(14) of completed 5m bars of the exact bought option;
  the forming bar is excluded. With fewer than 15 completed bars the fallback
  10% distance is used.
- **Initial ATR stop (`STOP_LOSS_ATR`):** `distance = 0.70 × ATR`, clamped to
  `[0.05 × entry, 0.30 × entry]`; `stop_price = round(entry − distance, 2)`.
  Breach is detected from the completed bar's low.
- **ATR trail (`TRAIL_STOP_EXIT`):** once premium makes a new high above entry,
  `trail_stop = max(current_stop, hwm − distance)`, ratcheted on the bar high and
  checked against the bar high/low. There is no +5 activation and no breakeven
  lock; the stop can never ratchet down.
- **Exit price:** the shared helper chooses the lower of the completed bar's low
  (initial-stop fill) and the ratcheted trail level. This conservative OHLC
  proxy replaces sampled-LTP exits so live matches the 5-minute backtest.
- If neither fires the position stays open across candles and overnight. No
  time-based exit and no close-only exit rule.

**Persisted state:** `atr_at_entry`, `stop_price`, `stop_loss`, `hwm`, `lwm`,
`trail_distance`, `stop_distance_pct`, `stop_source`, `trailing_update_cnt`,
`mfe_points` and `mae_points` are written on every trail/MFE change
(`_persist_trailing`) and again on exit (`_persist_exit`). Initial stops are
logged as `ATR_STOP` and ratchets as `ATR_TRAIL` in
`pattern_scanner_stop_changes`. `_ensure_schema` adds the new columns
idempotently. Legacy spot-stop rows are migrated on load: their spot-valued
`hwm`/`lwm`/`stop_loss` are discarded and replaced with a premium fallback stop
derived from `entry_price`.

**Runner quoting:** every 5m poll quotes the current ATM CE/PE **and** every
instrument with an active position, so an older strike still gets its own
completed bar after the ATM band moves. Quotes are recorded before the spot tick
for entry pricing; each symbol's previous completed 5m OHLC bar is appended and
evaluated via `evaluate_bar()` before spot candle completion triggers a new
entry. Status reports `poll_interval_sec = 300`,
`poll_alignment = 5m_boundary_plus_10s` and
`exit_data = completed_5m_option_ohlc`.

- No target. Paper trading only.

The live runner is `scripts/pattern_scanner_live.py` (systemd
`pattern-scanner-live.service`); the engine is
`app/research/pattern_scanner.py`.

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

### 5.7 SMA9 ATR scanner, 5-second poll (`sma9_5s_atr`)

Added 2026-11-19, first live day 2026-11-19. It combines the SMA9 entry with
the ATR stop and ATR-only trail of `sma9_atr`. v1.1.0 switched the poll from 60
seconds to **5 seconds**, made the trail ATR-only, and added a rising-SMA9
entry filter. On 2026-11-20 it was renamed from `sma9_1min_atr` to `sma9_5s_atr`;
the DB history was copied into the new identity and the old service/API/page
were retired as archives. It replaces the retired `no_sma_trail`.

```
signal    = prev.close > SMA9 AND forming.open > SMA9 AND SMA9 > prev_SMA9
poll      = every 5 seconds, aligned to the 5-second wall-clock boundary
entry     = paper BUY at round(LTP, 2), 09:20–15:15, one per 5m candle
atr       = mean True Range of the option premium over 14 completed 5m candles
distance  = clamp(0.70 * atr, 5% * entry, 30% * entry)   # fixed at entry
stop      = entry - distance
```

- **Entry** needs conditions A, B **and C**. C is `SMA9 > prev_SMA9`, where
  `prev_SMA9` is the 9-candle average ending one completed candle earlier
  (10 completed candles are required). There is no previous-high breakout and
  no separate LTP > SMA9 gate; LTP > SMA9 is reported for information only.
  C is a genuine extra filter: when the window rolls, the average changes by
  `(new close − dropped close) / 9`, so a close above the average (A) does not
  guarantee a rising average. Real-feed checks found A/B true with C false.
- **Initial stop** is identical to `sma9_atr`. When LTP <= stop the trade
  closes at the **actual live LTP**, not the theoretical stop
  (`STOP_LOSS_ATR`). With fewer than 15 completed candles the distance falls
  back to 10% of entry (`stop_source='fallback_pct'`).
- **ATR trail only** — no fixed +5 activation and no breakeven lock:

  ```
  hwm = max(hwm, LTP)
  if hwm > entry:
      stop = max(stop, hwm - distance)   # same ATR distance, frozen at entry
  exit when LTP <= stop                  # TRAIL_STOP_EXIT at the LTP
  ```

  The stop never ratchets down. Before price moves above entry the initial ATR
  stop is the only exit, so a losing trade is never labelled as a trail exit.
- No time-based or candle-close exit.

**Isolation:** own code `/opt/tradingai/sma9_5s_atr_scanner/`, DB
`database/sma9_5s_atr.db`, tables `sma9_5s_atr_trades` /
`sma9_5s_atr_open_positions` / `sma9_5s_atr_scan_state`, systemd
`tradingai-sma9-5s-atr-scanner.service`, log
`logs/live_sma9_5s_atr_scanner.log`, user `sma95satr`, API
`/api/sma9-5s-atr/*`, page `/live/sma9-5s-atr/`, report key
`sma9_5s_atr` (label `SMA9 5S ATR`, from 2026-11-19). v1.1.0 added
`prev_sma9` / `condition_c` to the trade and open-position tables, plus an
idempotent column migration for the existing DB.

**Persisted state:** `atr_at_entry`, `stop_price`, `stop_k`,
`stop_distance_pct`, `stop_source`, `trail_distance`, `hwm`, `trail_stop`,
`prev_sma9`, `condition_c` (and legacy `be_locked`, always false after restore).
The ratchet is written on every poll, so a restart resumes the same stop; a
v1.0.0 position is rebuilt from the frozen ATR distance under the ATR-only
rule. A position from an earlier session is closed at the current LTP
(`STALE_RECOVERY_EXIT`).

**Pre-open operations:**

```bash
python3 /opt/tradingai/sma9_5s_atr_scanner/ops/dryrun_market_open.py
```

It drives the deployed runner through pre-market → 09:00 scan start → 09:20 entry →
ATR stop at the LTP → re-entry → ATR trail ratchet → restart recovery →
stale prior-day position, with a throw-away DB and a fake feed. The unit is
`enabled`, `Restart=always`, and listed in `ALL_UNITS` in
`/opt/tradingai/refresh_token.sh`.

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
| ATR stop (`sma9_atr`, `sma9_5s_atr`, `sma9_1min_poll`) | `atr_at_entry`, `stop_price`, `stop_k`, `stop_distance_pct`, `stop_source`, `trail_distance` (all three ATR scanners). `sma9_5s_atr` v1.1.0 also stores `prev_sma9` / `condition_c` and added `trail_distance` to its trades table. |

`exit_reason` is `STOP_LOSS_5PCT` or `TRAIL_STOP_EXIT` for the four fixed-stop
premium scanners, and `STOP_LOSS_ATR` or `TRAIL_STOP_EXIT` for the three ATR
premium scanners.
There is no candle-close, minute-10, or session-end reason on any of them.
`pattern_scanner` uses its own tables (`pattern_scanner_positions`,
`pattern_scanner_stop_changes` in `database/tradingai.db`) and reasons
`TRAIL_STOP_EXIT` or `STOP_LOSS_ATR` (premium ATR stop; older rows may still
show `STOP_LOSS_SPOT` or `STOP_LOSS_5PCT` from previous exit models). No
`SQUARE_OFF`.
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
`sma9-high-trail`. The four newer scanners (`sma9-atr`, `sma9-1min-poll`,
`sma9-5s-atr`, `sma9-5min`) expose the same set **except `legacy-audit`** (8 endpoints):
`signals`, `trades`, `daily-summary`, `scanner-status`, `live-status`,
`recent-trades`, `today`, `open-positions`. They read
`database/sma9_atr.db`, `database/sma9_1min_poll.db` and
`database/sma9_5s_atr.db` respectively; the scanner is the only writer.
The staged `sma9_5min` copy already has the same 8-endpoint set deployed at
`/api/sma9-5min/*`, reading `database/sma9_5min.db` read-only; its scanner
service is still staged and not running.

The retired `no-sma` and `no-sma-trail` endpoints remain so the archived pages
still load.

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
buttons: the service is enabled at boot, runs itself from the 09:00 scan start, holds
positions until its premium ATR trail or stop fires, and the page auto-refreshes
every 5 s. `stop` halts the service immediately and leaves open rows in the DB; they
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
| sma9_5min (scanner staged) | https://tradingai.in/live/sma9-5min/ (page deployed) |
| sma9_atr | https://tradingai.in/live/sma9-atr/ |
| sma9_high | https://tradingai.in/live/sma9-high/ |
| sma9_1min_poll | https://tradingai.in/live/sma9-1min-poll/ |
| sma9_5s_atr | https://tradingai.in/live/sma9-5s-atr/ |
| sma9_trail | https://tradingai.in/live/sma9-trail/ |
| sma9_high_trail | https://tradingai.in/live/sma9-high-trail/ |
| pattern_scanner | https://tradingai.in/live/pattern_scanner/ |

Every active scanner has a button on `https://tradingai.in/live/scalp/` — the
eight buttons are `sma9`, `sma9-atr`, `sma9-high`, `sma9-1min-poll`,
`sma9-5s-atr`, `sma9-trail`, `sma9-high-trail` and `pattern_scanner`. All 8
active pages share the same dark theme,
badge/table styling, a `Back to Launcher` link, and auto-refresh without a page
reload every 5 s. The `sma9-atr`, `sma9-5s-atr` and `sma9-1min-poll` pages show
the entry ATR(14), the fixed ATR stop, the live ATR trail distance and an ATR
stop preview for each ATM option; legacy BE-lock fields remain in the payload
for compatibility but are always false and unused in v1.1.0. `sma9-5s-atr`
additionally shows the rising-SMA9 filter.
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

`refresh_token.sh` (Zerodha path) exchanges the token, then restarts **all 9
units**: the API, the 7 paper scanners, and `pattern-scanner-live`. On the VM the
active broker is mStock, whose session is refreshed with `mstock_session.py`
(TOTP/OTP) instead. Every scanner obtains market data through the long-lived
gateway daemon; a broker-session change must be applied to the gateway, which
validates token freshness on every call and reports an error rather than using
a stale token.

```bash
# 3. All 8 scanners + API active
systemctl is-active tradingai-api \
  tradingai-sma9-scanner tradingai-sma9-atr-scanner \
  tradingai-sma9-high-scanner \
  tradingai-sma9-1min-poll-scanner tradingai-sma9-5s-atr-scanner \
  tradingai-sma9_trail-scanner \
  tradingai-sma9_high_trail-scanner pattern-scanner-live

# 4. Instrument load completed ("ready" in each log)
for f in /opt/tradingai/logs/live_*scanner.log; do
  printf '%-40s %s\n' "$(basename "$f")" "$(grep 'ready$' "$f" | tail -1)"
done
```

### 8.2 Restart

Restart scanners in staggered waves (3 s apart) so 8 instrument downloads do
not hit Kite at once:

```bash
for u in tradingai-sma9-scanner tradingai-sma9-atr-scanner \
         tradingai-sma9-high-scanner \
         tradingai-sma9-1min-poll-scanner tradingai-sma9-5s-atr-scanner \
         tradingai-sma9_trail-scanner \
         tradingai-sma9_high_trail-scanner pattern-scanner-live; do
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

# all 7 premium-scanner APIs return 200
for k in sma9 sma9-atr sma9-high sma9-1min-poll \
         sma9-5s-atr sma9-trail sma9-high-trail; do
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

### 8.5 Code locks (7 active premium scanner trees)

The 7 active premium scanner directories are protected: `root:root`, files mode
`444`, directories `555`. The original base/HIGH families (`sma9`, `sma9_high`)
and their trail copies (`sma9_trail`, `sma9_high_trail`) additionally use
`chattr +i` on every file and directory, with a SHA256 `MANIFEST.sha256` and an
integrity timer. `sma9_atr`, `sma9_1min_poll` and `sma9_5s_atr` are installed
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
disk (it just no longer runs). The `pattern_scanner` files (`app/research/pattern_scanner.py`,
`scripts/pattern_scanner_live.py`) are **not** locked and have no manifest;
edit and restart `pattern-scanner-live.service` normally.

### 8.6 Rate-limit hygiene

- Base plain scanners (`sma9`, `sma9_atr`, `sma9_1min_poll`, `sma9_5s_atr`):
  **2 quote calls per tick** — one spot-only refresh for ATM selection, plus
  one batched spot+CE+PE quote. Offset 0. All four tick once every 5 seconds.
- Base HIGH scanner (`sma9_high`): same **2-call** pattern, offset 2.4 s.
- Trail scanners (`sma9_trail`, `sma9_high_trail`): self-contained since the
  2.1.0 rewrite — **1 batched spot+CE+PE quote per tick** plus historical
  candles only when a new 5-minute candle appears (extra quote calls only on a
  failed batch or a newly missing contract). Offsets 1.2 s / 3.0 s. They no
  longer make a base-status HTTP call.
- Historical candles are fetched only when a new 5-minute candle appears (or
  at exit), never on every poll.
- `pattern_scanner`: **1 batched spot+CE/PE quote call plus 1 read-only
  `historical_data(..., "5minute")` call per quoted option symbol per 5m poll**.
  Symbols include current ATM CE/PE and every open position's option after an
  ATM reband. A completed previous-boundary bar is requested at `:10 s` past
  each 5m boundary, with timestamp validation and a forming-bar guard.
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
for u in sma9 sma95min sma9high sma91m sma95satr sma9trail sma9trailhigh; do
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

- **Paper only.** No broker order path exists. Verify with:

  ```bash
  sudo grep -rn 'place_order\|order_id' /opt/tradingai/*_scanner/app/ \
    /opt/tradingai/app/research/pattern_scanner.py \
    /opt/tradingai/scripts/pattern_scanner_live.py \
    && echo 'FOUND — investigate' || echo 'clean: no broker orders'
  ```

- **BUY only.** CE and PE are long-only; there is no short/sell-to-open path.
- **Fixed 5% stop on the four active fixed-stop scanners and staged
  `sma9_5min`.** Every position exits at `round(entry × 0.95, 2)` if LTP falls
  that far (`STOP_LOSS_5PCT`); the trail stop is the preferred, higher exit and
  is evaluated first. `sma9_atr`,
  `sma9_5s_atr` and `sma9_1min_poll` use an ATR-scaled stop instead (see
  §5.6, §5.7), filled at the live LTP. `sma9_atr` v1.1.0 also trails only at
  that ATR distance and gates entries on the daily spot regime; exits are never
  gated.
- **`pattern_scanner`** uses the same premium ATR(14) exit model as the ATR
  scanners: `0.70 × ATR` initial stop clamped to 5–30% of entry, plus an
  ATR-width trail with no +5 activation and no breakeven lock. It has no spot
  stop and no time exit, and manages exits only from the position's own completed
  5m option OHLC bars on the aligned 5-minute poll.
- **No time-based exit** on any scanner; positions hold across candles and
  overnight until the trail or ATR/5% stop fires.
- **Secrets** live only in root-owned gateway credential files on the VM; they
  are never read by a scanner and are never committed.
- **State survives restarts** via `open_positions` and `scan_state`, including
  trail `hwm`/`stop`.

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
| Newer scanner sources (git-tracked) | `scripts/sma9_atr_scanner/`, `scripts/sma9_1min_poll_scanner/`, `scripts/sma9_5s_atr_scanner/`, `scripts/sma9_5min_scanner/` (staged) |
| Pattern runner (git-tracked) | `scripts/pattern_scanner_live.py`, `app/research/pattern_scanner.py` |
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
