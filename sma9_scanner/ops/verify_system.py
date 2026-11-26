#!/usr/bin/env python3
"""End-to-end verification for the corrected SMA9 live system."""
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "/opt/tradingai"
CODE_ROOT = os.path.join(BASE, "sma9_scanner")
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)
IST = ZoneInfo("Asia/Kolkata")
SMA9_DB = os.path.join(BASE, "database", "sma9.db")
MAIN_DB = os.path.join(BASE, "database", "tradingai.db")
REPORT = os.path.join(BASE, "reports", f"sma9_verification_{datetime.now(IST):%Y%m%d_%H%M%S}")
os.makedirs(REPORT, exist_ok=True)


def conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def one(c, q, p=()):
    return c.execute(q, p).fetchone()[0]


def http_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:
        return None, {"error": str(e)}


def http_code(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status
    except Exception as e:
        return str(e)


c = conn(SMA9_DB)
m = conn(MAIN_DB)

legacy = one(c, "SELECT COUNT(*) FROM sma9_trades_legacy")
legacy_distinct = one(c, "SELECT COUNT(DISTINCT trade_id) FROM sma9_trades_legacy")
original = one(m, "SELECT COUNT(*) FROM sma9_trades")
corrected = one(c, "SELECT COUNT(*) FROM sma9_trades WHERE dataset='HISTORICAL_CORRECTED'")
live = one(c, "SELECT COUNT(*) FROM sma9_trades WHERE dataset='LIVE'")
audit = one(c, "SELECT COUNT(*) FROM sma9_audit")
compliant = one(c, "SELECT COUNT(*) FROM sma9_audit WHERE compliant=1")
open_pos = one(c, "SELECT COUNT(*) FROM sma9_open_positions")

dup_live = [dict(r) for r in c.execute(
    "SELECT option_type, entry_candle_start, COUNT(*) n FROM sma9_trades "
    "WHERE dataset='LIVE' GROUP BY option_type, entry_candle_start HAVING n>1"
)]
bad_exit = [dict(r) for r in c.execute(
    "SELECT trade_id, entry_timestamp, exit_timestamp, entry_candle_end, "
    "exit_price, candle_close FROM sma9_trades WHERE dataset='LIVE' AND "
    "(exit_timestamp != entry_candle_end OR ABS(exit_price - candle_close) > 0.011)"
)]
bad_pnl = [dict(r) for r in c.execute(
    "SELECT trade_id, entry_price, exit_price, pnl_points FROM sma9_trades "
    "WHERE dataset='LIVE' AND ABS(pnl_points - ROUND(exit_price-entry_price,2)) > 0.011"
)]
short_pnl = [dict(r) for r in c.execute(
    "SELECT trade_id, entry_price, exit_price, pnl_points FROM sma9_trades "
    "WHERE dataset='LIVE' AND ABS(pnl_points - ROUND(entry_price-exit_price,2)) < 0.011 "
    "AND ABS(pnl_points - ROUND(exit_price-entry_price,2)) > 0.011"
)]
missing = [dict(r) for r in c.execute(
    "SELECT trade_id FROM sma9_trades WHERE dataset='LIVE' AND "
    "(sma9_value IS NULL OR condition_a IS NULL OR condition_b IS NULL OR entry_candle_start IS NULL)"
)]
live_rows = [dict(r) for r in c.execute(
    "SELECT trade_id, option_type, entry_timestamp, entry_price, exit_timestamp, "
    "exit_price, pnl_points, sma9_value, candle_open, candle_close, status, "
    "exit_reason, dataset FROM sma9_trades WHERE dataset='LIVE' ORDER BY entry_timestamp"
)]
open_rows = [dict(r) for r in c.execute("SELECT * FROM sma9_open_positions")]
c.close()
m.close()

api_checks = {}
for path in [
    "/api/sma9/scanner-status", "/api/sma9/live-status", "/api/sma9/today",
    "/api/sma9/recent-trades?limit=2", "/api/sma9/daily-summary",
    "/api/sma9/legacy-audit", "/api/sma9/trades?limit=2",
]:
    code, body = http_json("http://127.0.0.1:8000" + path)
    api_checks[path] = {
        "status": code,
        "success": body.get("success"),
        "keys": sorted(body.keys())[:12],
    }

public = {
    "dashboard": http_code("https://tradingai.in/live/index.html"),
    "scanner_status": http_code("https://tradingai.in/api/sma9/scanner-status"),
    "today": http_code("https://tradingai.in/api/sma9/today"),
}

services = {}
for svc in ["tradingai-sma9-scanner.service", "tradingai-api.service"]:
    try:
        active = subprocess.check_output(
            ["systemctl", "is-active", svc], text=True).strip()
        enabled = subprocess.check_output(
            ["systemctl", "is-enabled", svc], text=True).strip()
    except Exception as e:
        active, enabled = "error", str(e)
    services[svc] = {"active": active, "enabled": enabled}

# Ensure no broker order API is referenced by the SMA9 engine/scanner.
src = ""
for f in ["sma9_scanner/app/sma9_engine.py", "sma9_scanner/app/live_sma9_scanner.py"]:
    src += open(os.path.join(BASE, f)).read()
no_orders = ("place_order" not in src and "place_order" not in src
             and "order_id" not in src)

# The legacy sma9_only package must be importable and BUY-only, and the old
# historical runner must be a no-write deprecation shim.
legacy_pkg = {}
try:
    import sma9_only as legacy_mod
    legacy_pkg["import_ok"] = True
    legacy_pkg["strategy_type"] = legacy_mod.STRATEGY_TYPE
    legacy_pkg["strategy_version"] = legacy_mod.STRATEGY_VERSION
    legacy_pkg["max_positions"] = legacy_mod.MAX_POSITIONS
    legacy_pkg["scanner_info_type"] = legacy_mod.Sma9Scanner().info.strategy_type
except Exception as e:
    legacy_pkg = {"import_ok": False, "error": str(e)}

legacy_src = open(os.path.join(BASE, "sma9_scanner/sma9_only/scanner.py")).read()
legacy_pkg["no_pe_short_logic"] = (
    "SMA9_BEAR" not in legacy_src and "entry >= sma9" not in legacy_src
    and "signal_direction = \"BEAR\"" not in legacy_src
)
runner_src = open(os.path.join(BASE, "sma9_scanner/app/sma9_scan_runner.py")).read()
legacy_pkg["runner_is_shim_no_writes"] = (
    "INSERT OR REPLACE INTO sma9_trades" not in runner_src
    and "DEPRECATED" in runner_src
)
legacy_pkg_ok = (
    legacy_pkg.get("import_ok") is True
    and legacy_pkg.get("strategy_type") == "SMA9_BUY_ONLY"
    and legacy_pkg.get("scanner_info_type") == "SMA9_BUY_ONLY"
    and legacy_pkg.get("max_positions") == 2
    and legacy_pkg.get("no_pe_short_logic") is True
    and legacy_pkg.get("runner_is_shim_no_writes") is True
)

# ---- Code lock / integrity ------------------------------------------------
import pwd  # noqa: E402

LOCK_ROOT = os.path.join(BASE, "sma9_scanner")
MANIFEST = os.path.join(LOCK_ROOT, "MANIFEST.sha256")
try:
    manifest_proc = subprocess.run(
        ["sha256sum", "-c", "--quiet", MANIFEST],
        cwd=LOCK_ROOT, text=True, capture_output=True)
    manifest_ok = manifest_proc.returncode == 0
    manifest_output = (manifest_proc.stdout + manifest_proc.stderr).strip()
except Exception as e:
    manifest_ok = False
    manifest_output = str(e)


def _locked(path):
    try:
        out = subprocess.check_output(["lsattr", path], text=True)
        return "i" in out.split()[0]
    except Exception:
        return False


def _owner(path):
    try:
        return pwd.getpwuid(os.stat(path).st_uid).pw_name
    except Exception:
        return None


key_files = [
    "app/sma9_engine.py",
    "app/live_sma9_scanner.py",
    "sma9_only/scanner.py",
]
code_lock = {
    "root": LOCK_ROOT,
    "manifest_ok": manifest_ok,
    "manifest_output": manifest_output,
    "immutable": all(_locked(os.path.join(LOCK_ROOT, f)) for f in key_files),
    "root_owned": all(_owner(os.path.join(LOCK_ROOT, f)) == "root"
                      for f in key_files),
    "file_modes": {
        f: oct(os.stat(os.path.join(LOCK_ROOT, f)).st_mode & 0o777)
        for f in key_files
    },
}
try:
    code_lock["service_user"] = subprocess.check_output(
        ["systemctl", "show", "tradingai-sma9-scanner.service",
         "-p", "User", "--value"], text=True).strip()
except Exception as e:
    code_lock["service_user"] = f"error: {e}"
code_lock["ok"] = (
    code_lock["manifest_ok"]
    and code_lock["immutable"]
    and code_lock["root_owned"]
    and code_lock["service_user"] == "sma9"
)

state = {}
try:
    code, body = http_json("http://127.0.0.1:8000/api/sma9/live-status")
    state = body.get("data", {})
except Exception:
    pass

result = {
    "verified_at": datetime.now(IST).isoformat(),
    "database": {
        "dedicated_db": SMA9_DB,
        "main_db": MAIN_DB,
        "legacy_rows_preserved": legacy,
        "legacy_distinct_ids": legacy_distinct,
        "original_main_db_rows_untouched": original,
        "corrected_historical_rows": corrected,
        "live_rows": live,
        "audit_rows": audit,
        "audit_compliant": compliant,
        "audit_discrepant": audit - compliant,
        "open_positions": open_pos,
        "duplicate_live_entries_same_candle": dup_live,
        "live_bad_same_candle_exit": bad_exit,
        "live_bad_buy_pnl": bad_pnl,
        "live_short_pnl_rows": short_pnl,
        "live_missing_required_fields": missing,
        "live_rows_detail": live_rows,
        "open_positions_detail": open_rows,
    },
    "scanner_state": {
        "status": state.get("status"),
        "last_scan_at": state.get("last_scan_at"),
        "poll_seconds": state.get("poll_seconds"),
        "actual_interval_seconds": state.get("actual_interval_seconds"),
        "market_open": state.get("market_open"),
        "spot": state.get("spot"),
        "atm_strike": state.get("atm_strike"),
        "expiry": state.get("expiry"),
        "today": state.get("today"),
        "errors": state.get("errors"),
        "ce": (state.get("options") or {}).get("CE"),
        "pe": (state.get("options") or {}).get("PE"),
    },
    "api_checks": api_checks,
    "public_checks": public,
    "services": services,
    "no_broker_order_calls_in_sma9_code": no_orders,
    "legacy_package": legacy_pkg,
    "legacy_package_ok": legacy_pkg_ok,
    "code_lock": code_lock,
}

passed = (
    legacy == 339 and legacy_distinct == 339 and original == 339
    and audit == 339 and compliant == 0
    and not dup_live and not bad_exit and not bad_pnl and not short_pnl and not missing
    and all(v.get("status") == 200 for v in api_checks.values())
    and all(v == 200 for v in public.values())
    and all(v["active"] == "active" for v in services.values())
    and no_orders
    and legacy_pkg_ok
    and code_lock["ok"]
)
result["overall_pass"] = passed

with open(os.path.join(REPORT, "verification.json"), "w") as f:
    json.dump(result, f, indent=2, default=str)

lines = [
    "# SMA9 Live System Verification",
    "",
    f"- Verified at: {result['verified_at']}",
    f"- Overall: **{'PASS' if passed else 'FAIL'}**",
    "",
    "## Database",
    "",
    f"- Dedicated DB: `{SMA9_DB}`",
    f"- Legacy records preserved: **{legacy}** (distinct IDs {legacy_distinct})",
    f"- Original `tradingai.db` rows (untouched): **{original}**",
    f"- Corrected historical rows: **{corrected}**",
    f"- Live paper trades: **{live}**",
    f"- Audit rows: **{audit}**, compliant **{compliant}**, discrepant **{audit-compliant}**",
    f"- Open positions: **{open_pos}**",
    f"- Duplicate live entries in same candle: **{len(dup_live)}**",
    f"- Live rows not exiting at entry-candle close: **{len(bad_exit)}**",
    f"- Live rows with non-BUY P&L: **{len(bad_pnl) + len(short_pnl)}**",
    f"- Live rows missing required fields: **{len(missing)}**",
    "",
    "## Scanner",
    "",
    f"- Status: **{state.get('status')}**",
    f"- Configured poll: **{state.get('poll_seconds')}s**, actual measured: **{state.get('actual_interval_seconds')}s**",
    f"- Last scan: {state.get('last_scan_at')}",
    f"- Market open: {state.get('market_open')}",
    f"- Spot / ATM / expiry: {state.get('spot')} / {state.get('atm_strike')} / {state.get('expiry')}",
    f"- Errors: {state.get('errors')}",
    f"- No broker order calls in SMA9 code: **{no_orders}**",
    "",
    "## Legacy package / deprecated runner",
    "",
    f"- `sma9_only` package importable: **{legacy_pkg.get('import_ok')}**",
    f"- Legacy strategy type: **{legacy_pkg.get('strategy_type')}** (expected SMA9_BUY_ONLY)",
    f"- Legacy max long positions: **{legacy_pkg.get('max_positions')}**",
    f"- No PE-short / SMA9_BEAR logic in legacy scanner: **{legacy_pkg.get('no_pe_short_logic')}**",
    f"- `sma9_scanner/app/sma9_scan_runner.py` is a no-write shim: **{legacy_pkg.get('runner_is_shim_no_writes')}**",
    "",
    "## Code lock / integrity",
    "",
    f"- Lock root: `{code_lock['root']}`",
    f"- SHA256 manifest verified: **{code_lock['manifest_ok']}**",
    f"- Key files immutable (`chattr +i`): **{code_lock['immutable']}**",
    f"- Key files owned by root: **{code_lock['root_owned']}**",
    f"- File modes: {code_lock['file_modes']}",
    f"- Scanner service user: **{code_lock['service_user']}** (expected sma9)",
    f"- Lock OK: **{code_lock['ok']}**",
    "",
    "## Services",
    "",
]
for svc, v in services.items():
    lines.append(f"- `{svc}`: active={v['active']}, enabled={v['enabled']}")
lines += ["", "## Public endpoints", ""]
for k, v in public.items():
    lines.append(f"- {k}: HTTP {v}")
lines += ["", "## API endpoints", ""]
for k, v in api_checks.items():
    lines.append(f"- `{k}`: HTTP {v['status']}, success={v['success']}")
lines += ["", "## Live trades", "", "| Trade | Opt | Entry time | Entry | Exit time | Exit | P&L | SMA9 | Status |", "|---|---|---|---|---|---|---|---|---|"]
for r in live_rows:
    lines.append(
        f"| {r['trade_id']} | {r['option_type']} | {r['entry_timestamp']} | {r['entry_price']} | "
        f"{r['exit_timestamp']} | {r['exit_price']} | {r['pnl_points']} | {r['sma9_value']} | {r['status']} |"
    )
with open(os.path.join(REPORT, "VERIFICATION.md"), "w") as f:
    f.write("\n".join(lines) + "\n")

print(json.dumps({
    "overall_pass": passed,
    "report_dir": REPORT,
    "legacy": legacy,
    "original": original,
    "corrected": corrected,
    "live": live,
    "audit": audit,
    "compliant": compliant,
    "open_positions": open_pos,
    "dup_live": len(dup_live),
    "bad_exit": len(bad_exit),
    "bad_pnl": len(bad_pnl) + len(short_pnl),
    "missing": len(missing),
    "services": services,
    "public": public,
    "api_statuses": {k: v["status"] for k, v in api_checks.items()},
    "actual_interval": state.get("actual_interval_seconds"),
    "no_orders": no_orders,
    "legacy_package": legacy_pkg,
    "legacy_package_ok": legacy_pkg_ok,
    "code_lock": code_lock,
}, indent=2))
