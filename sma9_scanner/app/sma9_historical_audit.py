#!/usr/bin/env python3
"""Forensic audit of the 339 legacy SMA9 trades + corrected historical dataset.

Audit checks per legacy trade:
  1. option candle exists for the trade's exact timestamp
  2. stored SMA9 equals SMA9 computed from actual option candles
  3. SMA9 did not use the current candle's close (look-ahead)
  4. candle OHLC matches the actual option candle
  5. entry price equals that candle's open
  6. exit is the same candle's close (no later candle substitution)
  7. P&L follows BUY-only arithmetic (exit - entry), not short arithmetic
  8. candle is inside the 09:15-15:25 tradable window
  9. new-rule qualification: prev close > SMA9 OR current open > SMA9
 10. confirmation proxy: entry/open > SMA9

Outputs:
  * sma9.db: sma9_audit, sma9_trades_corrected, sma9_trades (HISTORICAL_CORRECTED)
  * reports/sma9_audit_<timestamp>/audit.csv
  * reports/sma9_audit_<timestamp>/summary.json
  * reports/sma9_audit_<timestamp>/REPORT.md
"""

import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE = "/opt/tradingai"
IST = ZoneInfo("Asia/Kolkata")
SMA9_DB = os.environ.get("SMA9_DB_PATH", os.path.join(BASE, "database", "sma9.db"))
OPT_DB = os.path.join(BASE, "nifty_spot_paper", "database", "nifty_spot.db")
REPORT_DIR = os.path.join(BASE, "reports", f"sma9_audit_{datetime.now(IST):%Y%m%d_%H%M%S}")
SMA_PERIOD = 9
EPS = 0.005
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


def now_iso():
    return datetime.now(IST).isoformat()


def connect(path):
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def load_contract_candles():
    conn = connect(OPT_DB)
    keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT contract_key FROM historical_option_candles"
    )]
    result = {}
    for key in keys:
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM historical_option_candles WHERE contract_key=? ORDER BY timestamp",
            (key,),
        ).fetchall()
        candles = [dict(r) for r in rows]
        result[key] = candles
    conn.close()
    return result


def contract_map(candles_by_key):
    mapping = {}
    for key in candles_by_key:
        parts = key.split("|")
        if len(parts) == 4:
            strike = float(parts[1])
            opt = parts[2]
            mapping[(strike, opt)] = key
    return mapping


def sma_at(candles, idx, period=SMA_PERIOD):
    if idx < period - 1:
        return None
    window = candles[idx - period + 1: idx + 1]
    return sum(float(c["close"]) for c in window) / period


def valid_session(ts):
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return False
    minutes = dt.hour * 60 + dt.minute
    return (MARKET_OPEN[0] * 60 + MARKET_OPEN[1]) <= minutes < (MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1])


def audit_trade(trade, candles, contract_key):
    reasons = []
    d = dict(trade)
    opt = d["option_type"]
    entry_ts = d["entry_timestamp"]
    idx_by_ts = {c["timestamp"]: i for i, c in enumerate(candles)}
    idx = idx_by_ts.get(entry_ts)

    rec = {
        "trade_id": d["trade_id"],
        "option_type": opt,
        "entry_timestamp": entry_ts,
        "entry_price": d["entry_price"],
        "stored_sma9": d["sma9_value"],
        "computed_sma9_current": None,
        "computed_sma9_prev": None,
        "prev_close": None,
        "candle_open": None,
        "candle_close": None,
        "condition_a": 0,
        "condition_b": 0,
        "qualified_new_rule": 0,
        "confirmation_proxy": 0,
        "old_rule_ok": 0,
        "sma9_matches_stored": 0,
        "sma9_no_lookahead": 0,
        "candle_matches": 0,
        "entry_price_matches_open": 0,
        "exit_same_candle": 0,
        "pnl_buy_correct": 0,
        "legacy_short_pnl": 0,
        "valid_session_candle": 1 if valid_session(entry_ts) else 0,
        "compliant": 0,
        "discrepancy_reasons": "",
        "contract_key": contract_key,
    }

    if idx is None:
        reasons.append("missing_option_candle")
        rec["discrepancy_reasons"] = ";".join(reasons)
        return rec

    c = candles[idx]
    sma_cur = sma_at(candles, idx)
    sma_prev = sma_at(candles, idx - 1) if idx >= 1 else None
    prev_close = float(candles[idx - 1]["close"]) if idx >= 1 else None
    open_px = float(c["open"])
    close_px = float(c["close"])

    rec.update({
        "computed_sma9_current": round(sma_cur, 4) if sma_cur is not None else None,
        "computed_sma9_prev": round(sma_prev, 4) if sma_prev is not None else None,
        "prev_close": prev_close,
        "candle_open": open_px,
        "candle_close": close_px,
    })

    if sma_cur is not None:
        # Stored values are rounded to 2 decimals.
        rec["sma9_matches_stored"] = int(
            abs(float(d["sma9_value"]) - round(sma_cur, 2)) <= EPS)
    if sma_prev is not None:
        # Exact 2-decimal equality: stored SMA9 must equal the SMA9 that was
        # actually available at the candle open (previous completed candles).
        rec["sma9_no_lookahead"] = int(
            round(float(d["sma9_value"]), 2) == round(sma_prev, 2))
        rec["condition_a"] = int(prev_close > sma_prev)
        rec["condition_b"] = int(open_px > sma_prev)
        rec["qualified_new_rule"] = int(rec["condition_a"] or rec["condition_b"])
        rec["confirmation_proxy"] = int(open_px > sma_prev)

    rec["candle_matches"] = int(
        abs(float(d["candle_open"]) - open_px) <= EPS
        and abs(float(d["candle_high"]) - float(c["high"])) <= EPS
        and abs(float(d["candle_low"]) - float(c["low"])) <= EPS
        and abs(float(d["candle_close"]) - close_px) <= EPS
    )
    rec["entry_price_matches_open"] = int(abs(float(d["entry_price"]) - open_px) <= EPS)
    rec["exit_same_candle"] = int(
        d["exit_timestamp"] == entry_ts and abs(float(d["exit_price"]) - close_px) <= EPS
    )
    rec["pnl_buy_correct"] = int(abs(float(d["pnl_points"]) - round(close_px - float(d["entry_price"]), 2)) <= EPS)
    rec["legacy_short_pnl"] = int(
        abs(float(d["pnl_points"]) - round(float(d["entry_price"]) - close_px, 2)) <= EPS
    )
    if sma_cur is not None:
        if opt == "CE":
            rec["old_rule_ok"] = int(open_px > sma_cur)
        else:
            rec["old_rule_ok"] = int(open_px < sma_cur)

    if not rec["valid_session_candle"]:
        reasons.append("invalid_session_candle")
    if not rec["qualified_new_rule"]:
        reasons.append("not_qualified_new_rule")
    if not rec["confirmation_proxy"]:
        reasons.append("confirmation_below_sma9")
    if not rec["sma9_matches_stored"]:
        reasons.append("stored_sma9_mismatch")
    if not rec["sma9_no_lookahead"]:
        reasons.append("sma9_lookahead_current_candle")
    if not rec["candle_matches"]:
        reasons.append("candle_ohlc_mismatch")
    if not rec["entry_price_matches_open"]:
        reasons.append("entry_price_not_open")
    if not rec["exit_same_candle"]:
        reasons.append("exit_not_same_candle_close")
    if not rec["pnl_buy_correct"]:
        reasons.append("pnl_not_buy_arithmetic")
    if rec["legacy_short_pnl"] and opt == "PE":
        reasons.append("legacy_short_pe_logic")

    rec["compliant"] = int(len(reasons) == 0)
    rec["discrepancy_reasons"] = ";".join(reasons)
    return rec


def ensure_live_table(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sma9_trades (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL DEFAULT 'sma9_only',
            instrument TEXT NOT NULL DEFAULT 'NIFTY',
            trade_date TEXT NOT NULL,
            option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
            strike REAL NOT NULL,
            expiry TEXT NOT NULL,
            signal_timestamp TEXT NOT NULL,
            entry_timestamp TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_timestamp TEXT NOT NULL,
            exit_price REAL NOT NULL,
            exit_reason TEXT NOT NULL DEFAULT 'SAME_CANDLE_EXIT',
            pnl_points REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'CLOSED',
            sma9_value REAL,
            candle_open REAL,
            candle_high REAL,
            candle_low REAL,
            candle_close REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            dataset TEXT NOT NULL DEFAULT 'LIVE',
            prev_close REAL,
            condition_a INTEGER,
            condition_b INTEGER,
            ltp_at_entry REAL,
            entry_candle_start TEXT,
            entry_candle_end TEXT
        );
        """
    )


def generate_corrected(candles_by_key, cmap):
    rows = []
    skipped_unconfirmed = 0
    for (strike, opt), key in sorted(cmap.items()):
        candles = candles_by_key[key]
        expiry = key.split("|")[3]
        for idx in range(SMA_PERIOD, len(candles)):
            cur = candles[idx]
            ts = cur["timestamp"]
            if not valid_session(ts):
                continue
            sma_prev = sma_at(candles, idx - 1)
            if sma_prev is None:
                continue
            prev_close = float(candles[idx - 1]["close"])
            open_px = float(cur["open"])
            close_px = float(cur["close"])
            a = prev_close > sma_prev
            b = open_px > sma_prev
            if not (a or b):
                continue
            # Historical OHLC cannot reveal an intra-candle LTP cross; require
            # the modelled entry (open) to already be above SMA9.
            if not (open_px > sma_prev):
                skipped_unconfirmed += 1
                continue
            start = datetime.fromisoformat(ts)
            end = start + timedelta(minutes=5)
            trade_id = "S9C-" + __import__("hashlib").sha1(
                f"SMA9|sma9_only|NIFTY|{strike}|{opt}|{ts}".encode()
            ).hexdigest()[:12].upper()
            rows.append({
                "trade_id": trade_id,
                "strategy_id": "sma9_only",
                "instrument": "NIFTY",
                "trade_date": start.date().isoformat(),
                "option_type": opt,
                "strike": strike,
                "expiry": expiry,
                "signal_timestamp": ts,
                "entry_timestamp": ts,
                "entry_price": round(open_px, 2),
                "exit_timestamp": end.isoformat(),
                "exit_price": round(close_px, 2),
                "exit_reason": "SAME_CANDLE_EXIT",
                "pnl_points": round(close_px - open_px, 2),
                "status": "CLOSED",
                "sma9_value": round(sma_prev, 2),
                "candle_open": open_px,
                "candle_high": float(cur["high"]),
                "candle_low": float(cur["low"]),
                "candle_close": close_px,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "dataset": "HISTORICAL_CORRECTED",
                "prev_close": prev_close,
                "condition_a": int(a),
                "condition_b": int(b),
                "ltp_at_entry": round(open_px, 2),
                "entry_candle_start": ts,
                "entry_candle_end": end.isoformat(),
            })
    return rows, skipped_unconfirmed


def main():
    if not os.path.exists(SMA9_DB):
        print(f"ERROR: {SMA9_DB} missing; run sma9_scanner/app/sma9_db_setup.py first")
        return 1
    os.makedirs(REPORT_DIR, exist_ok=True)

    candles_by_key = load_contract_candles()
    cmap = contract_map(candles_by_key)
    print("Contracts:", cmap)

    db = connect(SMA9_DB)
    legacy = [dict(r) for r in db.execute(
        "SELECT * FROM sma9_trades_legacy ORDER BY entry_timestamp"
    )]
    print("Legacy trades:", len(legacy))

    audit_rows = []
    for t in legacy:
        key = cmap.get((float(t["strike"]), t["option_type"]))
        if key is None:
            rec = {
                "trade_id": t["trade_id"], "option_type": t["option_type"],
                "entry_timestamp": t["entry_timestamp"], "entry_price": t["entry_price"],
                "stored_sma9": t["sma9_value"], "compliant": 0,
                "discrepancy_reasons": "missing_contract",
                "audited_at": now_iso(),
            }
        else:
            rec = audit_trade(t, candles_by_key[key], key)
            rec["audited_at"] = now_iso()
        audit_rows.append(rec)

    # Persist audit rows.
    db.execute("DELETE FROM sma9_audit")
    cols = [r[1] for r in db.execute("PRAGMA table_info(sma9_audit)")]
    placeholders = ",".join("?" for _ in cols)
    for rec in audit_rows:
        db.execute(
            f"INSERT OR REPLACE INTO sma9_audit ({','.join(cols)}) VALUES ({placeholders})",
            tuple(rec.get(c) for c in cols),
        )

    # Corrected historical dataset.
    corrected, skipped = generate_corrected(candles_by_key, cmap)
    ensure_live_table(db)
    db.execute("DELETE FROM sma9_trades_corrected")
    db.execute("DELETE FROM sma9_trades WHERE dataset='HISTORICAL_CORRECTED'")
    live_cols = [r[1] for r in db.execute("PRAGMA table_info(sma9_trades)")]
    live_ph = ",".join("?" for _ in live_cols)
    for row in corrected:
        db.execute(
            f"INSERT OR REPLACE INTO sma9_trades ({','.join(live_cols)}) VALUES ({live_ph})",
            tuple(row.get(c) for c in live_cols),
        )
    corr_cols = [r[1] for r in db.execute("PRAGMA table_info(sma9_trades_corrected)")]
    corr_ph = ",".join("?" for _ in corr_cols)
    for row in corrected:
        db.execute(
            f"INSERT OR REPLACE INTO sma9_trades_corrected ({','.join(corr_cols)}) VALUES ({corr_ph})",
            tuple(row.get(c) for c in corr_cols),
        )
    db.commit()

    # ---- reports -------------------------------------------------------
    csv_path = os.path.join(REPORT_DIR, "audit.csv")
    fieldnames = [r[1] for r in db.execute("PRAGMA table_info(sma9_audit)")]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for rec in audit_rows:
            w.writerow({k: rec.get(k) for k in fieldnames})

    total = len(audit_rows)
    compliant = sum(1 for r in audit_rows if r.get("compliant"))
    discrepant = total - compliant
    by_opt = defaultdict(lambda: {"total": 0, "compliant": 0, "discrepant": 0})
    reason_counts = Counter()
    for r in audit_rows:
        o = r.get("option_type")
        by_opt[o]["total"] += 1
        if r.get("compliant"):
            by_opt[o]["compliant"] += 1
        else:
            by_opt[o]["discrepant"] += 1
        for reason in (r.get("discrepancy_reasons") or "").split(";"):
            if reason:
                reason_counts[reason] += 1

    corr_by_opt = Counter(r["option_type"] for r in corrected)
    corr_pnl = sum(r["pnl_points"] for r in corrected)
    integrity = {
        "stored_sma9_matches_current_candle_sma9": sum(1 for r in audit_rows if r.get("sma9_matches_stored")),
        "sma9_used_completed_candles_only": sum(1 for r in audit_rows if r.get("sma9_no_lookahead")),
        "matches_legacy_ce_bull_pe_bear_rule": sum(1 for r in audit_rows if r.get("old_rule_ok")),
        "candle_ohlc_matches_source": sum(1 for r in audit_rows if r.get("candle_matches")),
        "entry_price_matches_candle_open": sum(1 for r in audit_rows if r.get("entry_price_matches_open")),
        "exit_is_same_candle_close": sum(1 for r in audit_rows if r.get("exit_same_candle")),
        "pnl_matches_buy_arithmetic": sum(1 for r in audit_rows if r.get("pnl_buy_correct")),
        "pnl_matches_legacy_short_arithmetic": sum(1 for r in audit_rows if r.get("legacy_short_pnl")),
        "valid_session_candle": sum(1 for r in audit_rows if r.get("valid_session_candle")),
    }
    lookahead_only = sum(
        1 for r in audit_rows
        if set((r.get("discrepancy_reasons") or "").split(";")) == {"sma9_lookahead_current_candle"}
    )
    summary = {
        "audited_at": now_iso(),
        "source": "sma9_trades_legacy (339 preserved originals)",
        "total_audited": total,
        "compliant": compliant,
        "discrepant": discrepant,
        "compliance_rate_pct": round(compliant / total * 100, 2) if total else 0,
        "by_option_type": dict(by_opt),
        "discrepancy_reason_counts": dict(reason_counts.most_common()),
        "data_integrity": integrity,
        "lookahead_only_discrepant_count": lookahead_only,
        "corrected_dataset": {
            "rows": len(corrected),
            "by_option_type": dict(corr_by_opt),
            "total_pnl_points": round(corr_pnl, 2),
            "skipped_qualification_only_unconfirmed": skipped,
            "assumption": (
                "Historical OHLC has no intra-candle ticks. Entry is modelled at the "
                "candle open only when the open is already above SMA9, which satisfies "
                "both qualification and the LTP>SMA9 confirmation proxy. Both CE and PE "
                "are BUY-only; exit is the same candle close."
            ),
        },
        "legacy_pe_short_logic_count": sum(1 for r in audit_rows if r.get("legacy_short_pnl") and r.get("option_type") == "PE"),
        "sma9_lookahead_count": sum(1 for r in audit_rows if not r.get("sma9_no_lookahead")),
        "invalid_session_candle_count": sum(1 for r in audit_rows if not r.get("valid_session_candle")),
    }
    with open(os.path.join(REPORT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    lines = [
        "# SMA9 Historical Trade Forensic Audit",
        "",
        f"- Audited at: {summary['audited_at']}",
        f"- Legacy records preserved: **{total}** (`sma9_trades_legacy`)",
        f"- Compliant under corrected BUY-only rule: **{compliant}**",
        f"- Discrepant: **{discrepant}**",
        f"- Compliance rate: **{summary['compliance_rate_pct']}%**",
        "",
        "## By option type",
        "",
        "| Option | Total | Compliant | Discrepant |",
        "|---|---|---|---|",
    ]
    for o, v in sorted(by_opt.items()):
        lines.append(f"| {o} | {v['total']} | {v['compliant']} | {v['discrepant']} |")
    lines += ["", "## Discrepancy reasons", "", "| Reason | Count |", "|---|---|"]
    for reason, count in reason_counts.most_common():
        lines.append(f"| {reason} | {count} |")
    lines += [
        "",
        "## Data integrity evidence",
        "",
        "| Check | Matches / 339 |",
        "|---|---|",
        f"| Stored SMA9 equals SMA9 computed through the entry candle close | {integrity['stored_sma9_matches_current_candle_sma9']} |",
        f"| Stored SMA9 uses completed candles only (no look-ahead) | {integrity['sma9_used_completed_candles_only']} |",
        f"| Trade matches legacy CE-bull / PE-bear rule | {integrity['matches_legacy_ce_bull_pe_bear_rule']} |",
        f"| Candle OHLC matches the actual option candle | {integrity['candle_ohlc_matches_source']} |",
        f"| Entry price equals candle open | {integrity['entry_price_matches_candle_open']} |",
        f"| Exit is the same candle's close | {integrity['exit_is_same_candle_close']} |",
        f"| P&L matches BUY arithmetic (exit - entry) | {integrity['pnl_matches_buy_arithmetic']} |",
        f"| P&L matches legacy short arithmetic | {integrity['pnl_matches_legacy_short_arithmetic']} |",
        f"| Candle is inside 09:15-15:25 tradable window | {integrity['valid_session_candle']} |",
        "",
        f"Trades whose only defect is look-ahead SMA9: **{lookahead_only}**.",
        "",
        "## Corrected historical dataset",
        "",
        f"- Rows generated: **{len(corrected)}** "
        f"(CE={corr_by_opt.get('CE', 0)}, PE={corr_by_opt.get('PE', 0)})",
        f"- Total P&L (points): **{round(corr_pnl, 2)}**",
        f"- Skipped (qualified but open <= SMA9, confirmation unverifiable): {skipped}",
        "",
        "## Key findings",
        "",
        f"- PE trades using legacy short arithmetic: **{summary['legacy_pe_short_logic_count']}**",
        f"- Trades whose stored SMA9 included the entry candle close (look-ahead): **{summary['sma9_lookahead_count']}**",
        f"- Trades on invalid/after-hours candles (15:30 or 15:35): **{summary['invalid_session_candle_count']}**",
        "",
        "## Method",
        "",
        "SMA9 was recomputed independently from the actual 5-minute option candles in "
        "`nifty_spot_paper/database/nifty_spot.db` (`historical_option_candles`). "
        "The corrected rule uses only the 9 completed candles ending at the previous "
        "candle; no current/future candle close is used. Original rows were never "
        "modified.",
        "",
        "Full per-trade evidence: `audit.csv`; machine summary: `summary.json`.",
    ]
    with open(os.path.join(REPORT_DIR, "REPORT.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    db.close()
    print(json.dumps(summary, indent=2, default=str))
    print("REPORT_DIR=" + REPORT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
