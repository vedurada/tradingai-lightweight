#!/usr/bin/env python3
"""Phase 7 audit: trace trades, verify R formula, risk denominator, entry/stop/
target rules, directionality, EOD exits, MFE/MAE, holding, distribution,
outliers, sensitivity, accounting, point-in-time, scenario/selection bias."""
import sys, json, statistics
from collections import Counter
sys.path.insert(0, '/opt/tradingai_new')
sys.path.insert(0, '/opt/tradingai_new/scripts')
from app.core.db import get_conn
from app.research.backtest import BacktestEngine

conn = get_conn()
eng = BacktestEngine()
OUT = {}

for inst in ['NIFTY', 'BANKNIFTY']:
    r = eng.run(inst, '2026-07-27', '2026-09-19')
    trades, decisions = r['trades'], r['decisions']
    candles = {c['timestamp']: c for c in
               conn.execute("SELECT * FROM market_candles_5m WHERE instrument_id=?", (inst,)).fetchall()}
    candles = {k: dict(v) for k, v in candles.items()}

    # --- independent recomputation per trade ---
    rows = []
    for t in trades:
        entry, stop, target = t['entry_price'], t['stop_price'], t['target_price']
        ex, direction = t['exit_price'], t['direction']
        risk_pts = abs(entry - stop)
        reward_pts = abs(target - entry)
        move = (ex - entry) if direction == 'LONG' else (entry - ex)
        true_R = move / risk_pts if risk_pts else float('nan')
        engine_R = t['R_multiple']
        # entry rule check: entry ?= signal-candle close * 0.995
        sig = candles.get(t['entry_time'])
        entry_ratio = entry / sig['close'] if sig else None
        # EOD check: exit == last candle close of day?
        day = sorted([c for c in candles.values() if c['timestamp'][:10] == t['trade_date']],
                     key=lambda c: c['timestamp'])
        eod_close = day[-1]['close'] if day else None
        # independent MFE/MAE excursions from candles after entry
        after = [c for c in day if c['timestamp'] > t['entry_time']]
        if direction == 'LONG':
            mfe_x = max([c['high'] for c in after] + [entry]) - entry if after else 0
            mae_x = entry - min([c['low'] for c in after] + [entry]) if after else 0
        else:
            mfe_x = entry - min([c['low'] for c in after] + [entry]) if after else 0
            mae_x = max([c['high'] for c in after] + [entry]) - entry if after else 0
        rows.append({**t, 'risk_pts': risk_pts, 'reward_pts': reward_pts,
                     'move_pts': move, 'true_R': true_R,
                     'R_ratio': engine_R / true_R if true_R else None,
                     'entry_over_sigclose': entry_ratio,
                     'eod_close': eod_close, 'exit_is_eod_close': abs(ex - eod_close) < 0.011 if eod_close else None,
                     'mfe_x': mfe_x, 'mae_x': mae_x})
    OUT[inst] = rows
    print(f"===== {inst}: {len(rows)} trades =====")
    print(f" directions: {Counter(t['direction'] for t in rows)}")
    print(f" entry_times: {Counter(t['entry_time'][11:16] for t in rows)}")
    print(f" exits: {Counter(t['exit_reason'] for t in rows)}")
    rr = [t['R_ratio'] for t in rows if t['R_ratio'] is not None]
    print(f" engine_R / true_R: min={min(rr):.4f} max={max(rr):.4f} (expect 50.0 if rupee/point unit bug)")
    rk = sorted(t['risk_pts'] for t in rows)
    print(f" risk_pts: min={rk[0]:.2f} max={rk[-1]:.2f} med={statistics.median(rk):.2f} avg={statistics.mean(rk):.2f}")
    er = Counter(round(t['entry_over_sigclose'], 6) for t in rows)
    print(f" entry/signal-close ratios: {dict(er)}")
    tr = sorted(t['reward_pts'] / t['risk_pts'] for t in rows)
    print(f" theoretical RR: min={tr[0]:.3f} max={tr[-1]:.3f} med={statistics.median(tr):.3f}")
    print(f" exit==EOD close: {sum(1 for t in rows if t['exit_is_eod_close'])}/{len(rows)}")
    ht = sorted(t['holding_minutes'] for t in rows)
    print(f" holding: min={ht[0]} max={ht[-1]} med={statistics.median(ht)} avg={round(statistics.mean(ht),1)}")

    # --- trace: last trade + (BANKNIFTY) the TARGET trade ---
    picks = [rows[-1]]
    tgt = [t for t in rows if t['exit_reason'] == 'TARGET']
    if tgt: picks.append(tgt[0])
    for t in picks:
        print(f"--- TRACE {t['trade_id']} {t['trade_date']} {t['scenario']} {t['direction']} exit={t['exit_reason']} ---")
        for k in ('entry_time','entry_price','stop_price','target_price','risk_pts','reward_pts',
                  'exit_time','exit_price','holding_minutes','MFE','MAE','mfe_x','mae_x',
                  'R_multiple','true_R','paper_pnl'):
            print(f"    {k} = {t[k]}")
        day = sorted([c for c in candles.values() if c['timestamp'][:10] == t['trade_date']],
                     key=lambda c: c['timestamp'])
        idx = next(i for i, c in enumerate(day) if c['timestamp'] == t['entry_time'])
        print(f"    entry candle [{idx}]: {day[idx]}")
        for c in day[idx+1:idx+4]: print(f"    next: {c['timestamp'][11:16]} O={c['open']} H={c['high']} L={c['low']} C={c['close']}")
        ex = [c for c in day if c['timestamp'] == t['exit_time']]
        if ex: print(f"    exit candle: {ex[0]}")

    # --- scenario constancy: what does get_active_scenario return across time? ---
    from app.scenarios.engine import ScenarioEngine
    se = ScenarioEngine()
    a = se.get_active_scenario(inst)
    print(f" active scenario (constant whole run): {a['candidate']['scenario_type']} "
          f"created={a['candidate']['created_at'][:16]} match={a['match']['match_state'] if a['match'] else None}")

json.dump({k: v for k, v in OUT.items()},
          open('/tmp/phase7_trades.json', 'w'), default=str)
print('saved /tmp/phase7_trades.json')
conn.close()
