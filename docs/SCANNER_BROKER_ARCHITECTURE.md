# Scanner & Broker Connectivity Architecture

This document describes how the eight live paper scanners reach a broker without
any scanner source changes. The broker gateway is the only component that holds
broker credentials; scanners see a read-only, Kite-shaped API.

## Design goals

- **Paper only.** No `place_order`, `order_id`, or broker write path exists.
- **Broker = config.** Switching brokers is a CLI command plus a scanner restart.
- **Secrets stay root-only.** Scanner users never read broker credential files.
- **Stable identities.** Scanner names, DBs, services, API routes, 5 s polling,
  09:00 IST start, 09:20–15:15 entries, 09:00–09:15 warm-up, ATR-only exits and
  A+B entry gating are unchanged.

## 1. End-to-end view

```mermaid
flowchart TB
    subgraph SCANNERS["8 paper scanners - source unchanged"]
        SMA["7 x SMA scanners<br/>live_sma9*.py<br/>poll = 5 s"]
        PAT["pattern_scanner_live.py<br/>poll = 5 s"]
    end

    subgraph SHIMLAYER["Per-process Kite-compatible shim"]
        KC["kiteconnect.KiteConnect<br/>set_access_token / instruments / quote<br/>historical_data / profile"]
        CL["broker_gateway.client.call<br/>JSON over Unix socket"]
        KC --> CL
    end

    SOCK["/run/tradingai/broker_gateway.sock<br/>dir 750 root:ubuntu, socket 660 root:ubuntu"]

    subgraph GW["tradingai-broker-gateway.service - runs as root"]
        DISP["dispatch(): broker allowlist + method allowlist<br/>max 4 concurrent broker calls"]
        ZA["ZerodhaAdapter"]
        MA["MStockAdapter"]
        DISP --> ZA
        DISP --> MA
    end

    SEC["/opt/tradingai/secrets/*.env<br/>0600 root:root<br/>never exposed to scanner users"]

    ZAPI["Zerodha KiteConnect REST<br/>read-only methods"]
    MAPI["mStock Type A REST<br/>read-only endpoints"]

    STATE["State: 8 SQLite DBs<br/>/opt/tradingai/database/*.db<br/>+ pattern_scanner_status.json"]
    API["Flask app via gunicorn<br/>127.0.0.1:8092<br/>/api/{scanner}/scanner-status"]
    UI["Dashboard / pages"]

    SMA --> KC
    PAT --> KC
    CL --> SOCK --> DISP
    SEC -. read by root only .-> ZA
    SEC -. read by root only .-> MA
    ZA --> ZAPI
    MA --> MAPI
    SMA --> STATE
    PAT --> STATE
    STATE --> API --> UI
```

## 2. Scanner inventory

| Alias (CLI) | Script | systemd service | Run user | State file | API status route |
|---|---|---|---|---|---|
| `sma9` | `live_sma9_scanner.py` | `tradingai-sma9-scanner` | `sma9` | `/opt/tradingai/database/sma9.db` | `/api/sma9/scanner-status` |
| `sma9_atr` | `live_sma9_atr_scanner.py` | `tradingai-sma9-atr-scanner` | `sma9` | `/opt/tradingai/database/sma9_atr.db` | `/api/sma9-atr/scanner-status` |
| `sma9_high` | `live_sma9_high_scanner.py` | `tradingai-sma9-high-scanner` | `sma9high` | `/opt/tradingai/database/sma9_high.db` | `/api/sma9-high/scanner-status` |
| `sma9_trail` | `live_sma9_trail_scanner.py` | `tradingai-sma9_trail-scanner` | `sma9trail` | `/opt/tradingai/database/sma9_trail.db` | `/api/sma9-trail/scanner-status` |
| `sma9_high_trail` | `live_sma9_high_trail_scanner.py` | `tradingai-sma9_high_trail-scanner` | `sma9trailhigh` | `/opt/tradingai/database/sma9_high_trail.db` | `/api/sma9-high-trail/scanner-status` |
| `sma9_5s_atr` | `live_sma9_5s_atr_scanner.py` | `tradingai-sma9-5s-atr-scanner` | `sma95satr` | `/opt/tradingai/database/sma9_5s_atr.db` | `/api/sma9-5s-atr/scanner-status` |
| `sma9_1min_poll` | `live_sma9_1min_poll_scanner.py` | `tradingai-sma9-1min-poll-scanner` | `sma91m` | `/opt/tradingai/database/sma9_1min_poll.db` | `/api/sma9-1min-poll/scanner-status` |
| `pattern` | `pattern_scanner_live.py` | `pattern-scanner-live` | `ubuntu` | `/opt/tradingai/data/pattern_scanner_status.json` | no dedicated route; dashboard reads JSON |

All eight currently resolve to broker `mstock`. The seven SMA routes are served
by `app.api.app:app` under gunicorn; the pattern scanner publishes a JSON status
file that is refreshed every 5 s.

## 3. How a scanner picks its broker

Broker resolution happens once, when `KiteConnect(...)` is constructed. It is
config/env only — no scanner code participates.

```mermaid
flowchart LR
    A["scanner starts"] --> B["broker_for()"]
    B --> C{"BROKER_GATEWAY_BROKER<br/>env override set?"}
    C -->|yes| D["use env broker"]
    C -->|no| E["scanner_name()<br/>BROKER_GATEWAY_SCANNER or argv[0] filename"]
    E --> F["read /opt/tradingai/broker_gateway/config/scanners.json"]
    F --> G{"per-scanner entry?"}
    G -->|yes| H["use mapped broker"]
    G -->|no| I["use default: zerodha"]
    D --> J["KiteConnect.broker"]
    H --> J
    I --> J
```

Selection commands:

```bash
sudo broker-gateway adapters
sudo broker-gateway status
sudo broker-gateway use --scanner sma9_1min_poll --broker mstock
sudo systemctl restart tradingai-sma9-1min-poll-scanner
```

Only the restarted scanner picks up the change; the other seven keep running.

## 4. The read-only boundary

```mermaid
flowchart LR
    SC["scanner code"] --> SHIM["KiteConnect shim"]
    SHIM -->|"allowed: instruments, quote,<br/>historical_data, profile"| DAEMON["gateway daemon allowlist"]
    SHIM -. place_*, modify_*, cancel_*, order*, squareoff* .-> BLOCKED["PermissionError<br/>never reaches daemon"]
    DAEMON --> ADAPTER["broker adapter"]
    ADAPTER --> BROKER["read-only broker REST"]
    ADAPTER -. fills simulated locally .-> DB["scanner SQLite DB"]
    BLOCKED -.-> NOORDER["no broker order path"]
```

- The shim's `__getattr__` rejects write-prefixed attributes immediately.
- The daemon independently enforces `METHODS = {instruments, quote,
  historical_data, profile}` and a broker allowlist, so a direct socket client
  cannot widen the surface either.
- `BrokerAdapter` is an ABC with only the three data methods plus `profile()`.
- Every trade remains simulated in the scanner's own SQLite database.

## 5. Lifecycle of one quote call

```mermaid
sequenceDiagram
    participant S as Scanner
    participant K as Kite shim
    participant C as Socket client
    participant G as Gateway daemon (root)
    participant A as MStockAdapter
    participant M as mStock Type A API

    S->>K: quote(["256265", "NFO:NIFTY26NOV25850CE"])
    K->>C: call("mstock", "quote", symbols=[...])
    C->>G: JSON line over Unix socket
    G->>G: allowlist check + acquire call slot (max 4)
    G->>A: quote(symbols)
    A->>A: map 256265 to NSE:NIFTY 50 and keep original key
    A->>M: GET /instruments/quote/ohlc?i=... (batches of 50)
    M-->>A: OHLC payload (retry 429/500/502/503/504)
    A-->>G: Kite-shaped map keyed by requested key
    G-->>C: {"ok": true, "result": {...}}
    C-->>K: dict
    K-->>S: dict
```

## 6. mStock adapter internals

```mermaid
flowchart TB
    SEC["__init__: read /opt/tradingai/secrets/mstock.env<br/>MSTOCK_API_KEY + daily MSTOCK_ACCESS_TOKEN"]

    subgraph T["_http_get transport"]
        HDR["X-Mirae-Version: 1<br/>Authorization: token KEY:TOKEN"]
        RETRY["3 attempts max<br/>backoff 0.6 s then 1.2 s<br/>429/500/502/503/504 + URLError/timeout"]
        HDR --> RETRY
    end

    subgraph EP["Type A endpoints"]
        SM["GET /instruments/scriptmaster"]
        QT["GET /instruments/quote/ohlc<br/>batches of 50 symbols"]
        HS["GET /instruments/historical/{exchange}/{token}/{interval}<br/>chunked to <= 10 days"]
    end

    subgraph C["In-process caches - root daemon only"]
        TM["token -> exchange map"]
        QK["token -> EXCHANGE:SYMBOL map<br/>256265 -> NSE:NIFTY 50"]
        HC["history: TTL 300 s, max 64 entries<br/>serialized by _history_lock"]
    end

    SEC --> HDR
    RETRY --> SM --> TM --> QK
    RETRY --> QT
    RETRY --> HS --> HC
    SM -. on disk .-> CSV["cache/mstock_scriptmaster.csv"]
```

Notable mappings and guards:

- `OPTIDX`/`CE`/`PE` and `OPT*` segments map to `NFO-OPT`; futures to `NFO-FUT`.
- Numeric quote tokens are translated for the broker but results are keyed by the
  original requested key, so scanner lookups keep working.
- Raw history requests over 10 days return HTTP 400 from mStock, so the adapter
  chunks ranges and merges candles.
- The 5-minute history cache plus the shared lock prevents eight scanners from
  refetching the same option candles concurrently.

## 7. Deployment map

| Layer | Location | Owner / mode |
|---|---|---|
| Source of truth | `/Users/satya/tradingai_sync` | repo on `feature/zerodha-paper-trading` |
| Gateway code | `/opt/tradingai/broker_gateway/` | root, 644 |
| Gateway config | `config/scanners.json` | root, 644; no secrets |
| Gateway cache | `cache/mstock_scriptmaster.csv` | root:ubuntu, 750 dir |
| Secrets | `/opt/tradingai/secrets/*.env` | root, 600 |
| Daemon unit | `/etc/systemd/system/tradingai-broker-gateway.service` | root, runs as root |
| CLI | `/usr/local/sbin/broker-gateway` | root, 700 |
| Python bootstrap | `broker_gateway.pth` in site-packages | puts shim on every Python path |
| Scanner services | `/etc/systemd/system/tradingai-*-scanner.service`, `pattern-scanner-live.service` | dedicated users, group `ubuntu` |
| Logs | `/opt/tradingai/logs/*.log` | written by each service |
| API | gunicorn `app.api.app:app` on `127.0.0.1:8092` | Flask, 2 workers |

Installer: `scripts/ops/install_broker_gateway.sh` installs code, config, CLI,
systemd unit and the `.pth` bootstrap. It does **not** restart scanners.

Secret lifecycle (no secret is ever passed as an argument or logged):

```bash
sudo /usr/local/sbin/rotate_mstock_key.sh       # hidden prompt, local key replacement only
sudo /usr/local/sbin/mstock_session.py --mode totp   # daily access token, OTP/TOTP never stored
sudo /usr/local/sbin/mstock_session.py --check  # verify stored token
```

## 8. Token lifecycle and live-market readiness

mStock Type A issues **daily** access tokens. `mstock_session.py` writes them to
`/opt/tradingai/secrets/mstock.env` with an atomic `os.replace`. The stored
`MSTOCK_REFRESH_TOKEN` is not used by any current automation, so a fresh session
must be created interactively before each trading day:

```bash
sudo /usr/local/sbin/mstock_session.py --mode totp   # or --mode otp
sudo /usr/local/sbin/mstock_session.py --check       # confirm before market open
```

The gateway daemon is long-running, so `MStockAdapter` re-reads the secret file
whenever its `(mtime, size)` signature changes. `_headers()` performs that check
on every HTTP request, so a pre-market token refresh becomes active on the next
broker call **without restarting the daemon**. An empty or partial refresh is
ignored and the previous working credentials are retained.

There is no mStock refresh timer. The existing `tradingai-token-check.timer`
(08:45 Mon–Fri IST) is a read-only **Zerodha** check and does not refresh or
restart anything; it is not part of the mStock path.

Broker selection itself is separate from tokens:

- `config/scanners.json` has `default: zerodha` but all eight scanners carry an
  explicit `mstock` entry, so every running scanner uses mstock.
- Any scanner key not present in that mapping would fall back to the Zerodha
  default. Set `default` to `mstock` if that fallback is not wanted.

## 9. Failure modes and mitigations

| Failure | Mitigation |
|---|---|
| mStock HTTP 500/429 on quote | 3 attempts with 0.6 s / 1.2 s backoff |
| mStock `Something went wrong. Please try again.` | transient-message retry in `_get_json` |
| >10 day history request | 10-day chunking and merge |
| Duplicate history fetches from 8 scanners | 300 s cache + `_history_lock` serialization |
| Memory pressure / OOM | 4-call concurrency cap; cached scriptmaster and candles |
| Socket `Connection refused` / `BrokenPipe` during gateway restart | systemd `Restart=always`; transient scanner errors are skipped on next 5 s poll |
| Daily mStock token expires overnight | Run `mstock_session.py --mode totp` before market open; daemon adopts the new token on the next call |
| Stale Zerodha token | Refresh that scanner's token before switching back; avoid fleet-wide refresh |
| Broker write attempted | Shim `PermissionError` + daemon method allowlist |

## 10. Extending to another broker

1. Add `broker_gateway/adapters/<name>.py` implementing `instruments`, `quote`,
   `historical_data` (optionally `profile`) on `BrokerAdapter`.
2. Register it in `broker_gateway/adapters/__init__.py`.
3. Store credentials in `/opt/tradingai/secrets/<name>.env` (`0600 root:root`).
4. Run `sudo broker-gateway probe --broker <name>`.
5. Select per scanner with `sudo broker-gateway use --scanner <alias> --broker <name>`
   and restart only that service.

No scanner file changes are needed.

## 11. Verified production state (2026-11-21)

- All 8 scanners configured to `mstock`; default remains `zerodha`.
- All 9 services (gateway + 8 scanners) active with zero systemd restarts.
- Gateway log clean; `probe --broker mstock` reports profile ok, 94089 NFO
  instruments, NIFTY quote ok.
- Seven SMA APIs: `IDLE_MARKET_CLOSED`, `poll=5`, fresh scan ages, errors only
  `['weekend']`.
- Pattern scanner: `MARKET_CLOSED`, polling every 5 s, spot and ATM strike
  updating through mStock, no broker orders.
- Memory stable at roughly 430 MB used of 956 MB total.
- `mstock_session.py --check` reports `session: valid`; the stored token was
  written at 10:10 IST and the daemon started at 11:23 IST, so the current token
  is the one in use.
- Token auto-reload verified with dummy credentials: an atomic secret-file
  replacement is adopted on the next call, and an invalid refresh is ignored.

Live-market checks (09:00 IST start, entry window, warm-up, ATR exits, A+B gating,
no broker orders) still require a trading session. The current daily token must
be regenerated before Monday's session; the daemon will pick it up automatically.
