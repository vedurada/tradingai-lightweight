#!/usr/bin/env python3
"""Apply the learned loss-memory to the plain backtest book (additive overlay).

Additive. Runs after paper_confluence logs the day. It evaluates every closed
NIFTY/BANKNIFTY paper_align trade of the plain engine variant (no filter)
against the loss-memory and records the ones the memory would veto in a NEW
table `paper_align_veto`, then prints the book's R with and without the applied
veto.

It never edits paper_align rows, and never touches engine/trigger/alert code.

  python3 scripts/veto_paper_book.py             # today, plain engine
  python3 scripts/veto_paper_book.py 2026-10-12  # a specific session, plain
  python3 scripts/veto_paper_book.py --all        # one-time full history sweep
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')
import loss_memory as lm
from app.core.db import get_conn

IST = ZoneInfo('Asia/Kolkata')


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_align_veto (
        session_date TEXT NOT NULL, instrument_id TEXT NOT NULL,
        variant TEXT NOT NULL DEFAULT 'plain', direction TEXT, level TEXT,
        regime TEXT, dow TEXT, r_multiple REAL, result TEXT,
        rule TEXT, created_at TEXT NOT NULL,
        PRIMARY KEY (session_date, instrument_id, variant))""")
    try:
        conn.execute("ALTER TABLE paper_align_veto ADD COLUMN vix_dir TEXT")
    except Exception:
        pass


def sweep(conn, engine, day):
    mem = lm.load_memory(engine)
    if not mem:
        print('[%s] no loss memory; run scripts/learn_losses.py first' % engine)
        return None
    rows = conn.execute(
        "SELECT session_date, instrument_id, direction, level, entry_time, r_multiple, result "
        "FROM paper_align WHERE variant=? AND state='SIGNAL' AND instrument_id IN ('NIFTY','BANKNIFTY') "
        "AND result IN ('WIN','LOSS') AND r_multiple IS NOT NULL AND session_date=?",
        (engine, day)).fetchall()
    vetoed, kept = [], []
    now = datetime.now(IST).isoformat(timespec='seconds')
    for r in rows:
        fp = lm.fingerprint_book(conn, r)
        v = lm.evaluate(mem, fp)
        if v['action'] == 'VETO':
            w = v.get('worst') or {}
            vetoed.append((r, fp, w))
            conn.execute(
                "INSERT OR REPLACE INTO paper_align_veto "
                "(session_date,instrument_id,variant,direction,level,regime,dow,vix_dir,"
                "r_multiple,result,rule,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r['session_date'], r['instrument_id'], engine, r['direction'],
                 r['level'], fp['regime'], fp['dow'], fp['vix_dir'], r['r_multiple'], r['result'],
                 w.get('reason'), now))
        else:
            kept.append(r)
    conn.commit()
    return rows, kept, vetoed


def report(engine, day, res):
    if not res:
        return
    rows, kept, vetoed = res
    rsum = lambda rs: round(sum(float(x['r_multiple'] or 0) for x in rs), 2)
    print('[%s] %s: book n=%d R=%+.2f | after veto n=%d R=%+.2f | vetoed=%d'
          % (engine, day, len(rows), rsum(rows), len(kept), rsum(kept), len(vetoed)))
    for r, fp, w in vetoed:
        print('  VETO %s %s %s/%s %s %s -> %+.2fR (%s)'
              % (r['session_date'], r['instrument_id'], fp['direction'], fp['level'],
                 fp['regime'], fp['dow'], float(r['r_multiple'] or 0), w.get('reason')))


def main(argv):
    args = [a for a in argv[1:]]
    if '--all' in args:
        args.remove('--all')
        all_days = True
    else:
        all_days = False
    day = args[0] if args else datetime.now(IST).date().isoformat()

    conn = get_conn()
    try:
        ensure_table(conn)
        if all_days:
            days = [r[0] for r in conn.execute(
                "SELECT DISTINCT session_date FROM paper_align "
                "WHERE variant='plain' AND state='SIGNAL' "
                "AND instrument_id IN ('NIFTY','BANKNIFTY') "
                "AND result IN ('WIN','LOSS') AND r_multiple IS NOT NULL")]
            for d in sorted(days):
                for engine in lm.ENGINES:
                    report(engine, d, sweep(conn, engine, d))
        else:
            for engine in lm.ENGINES:
                report(engine, day, sweep(conn, engine, day))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))