"""Paper-trade engine (spot-proxy fills with next-bar, no-lookahead exits).

R-DEFINITION MAP (see also app/research/backtest.py — canonical):
- backtest R_multiple (CANONICAL true multiple) = signed move_pts / risk_pts.
- qualification risk_reward = reward_pct / risk_pct (percent ratio; equals
  canonical R for spot trades since both legs scale with entry).
- options economics risk_reward/reward_risk = max_reward / max_risk
  (standardized reward/risk; equals canonical R at max outcome).
- performance realized_R = canonical R (converted here); pnl = R * risk_rs - fees.
This module persists legs JSON and exits on candle OPENS strictly AFTER entry
(entry_bar < t <= exit_bar) with STOP-first tie-break, using the SAME
`exits_opens` routine as the live alert/reconcile path and the approved-spec
opens execution (0.5% stop / 2% target on next opens). Booking the REAL
recorded open (not the planned stop/target level) keeps the live paper ledger
consistent with the published strategy truth and avoids planned-vs-realised
divergence (audit F-04-01).
"""
import uuid, json, hashlib, sqlite3, logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.core.db import get_conn
from app.core.config import settings

_IST = ZoneInfo('Asia/Kolkata')

# NSE lots effective 30-Dec-2025 (fixes stale lot 50).
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30}
BROKERAGE_RS = 40.0  # round-trip retail estimate
SLIPPAGE_PTS = 0.5  # per fill

# Provenance marker written into qualification_evidence by the live watcher so
# genuine production trades are distinguishable from historical test fixtures.
LIVE_ORIGIN = 'live-watch'


def _lot(instrument):
    return LOT_SIZES.get((instrument or "").upper(), 65)


def _direction_sign(direction):
    d = (direction or "").upper()
    if d in ("SHORT", "BEARISH", "BEAR", "BEARISH"):
        return -1
    return 1  # LONG / BULLISH / BULL default


log = logging.getLogger('tradingai.paper_trade')


def _risk_settings():
    try:
        return dict(settings.get('risk') or {})
    except Exception:
        return {}


def max_positions_per_direction():
    """Max concurrent positions per direction across instruments (risk cap).

    config/settings.json -> risk.max_positions_per_direction (default 1).

    NIFTY and BANKNIFTY fire off the SAME directional view, so taking both is
    one idea at 2x the intended risk (2026-10-22: Rs -16,588 for a single
    bearish call). Lab (75 sessions, live lot/cost model): max drawdown
    Rs 26,367 -> Rs 14,228 with an unchanged risk-adjusted return, and the
    loss day shrinks to Rs -7,688.
    """
    try:
        v = int(_risk_settings().get('max_positions_per_direction', 1))
    except (TypeError, ValueError):
        v = 1
    return v if v > 0 else 1


def paper_exit_mode():
    """Ledger exit rule for the live paper ledger.

    'eod'       -> flat at the 15:20 open of the entry session (published
                   spec parity: the paper book and the backtest use it).
    'overnight' -> hold until the stop/target is hit on a later open (the
                   legacy ledger behaviour: positions can stay open for days).
    """
    try:
        v = str((settings.get('paper_trade') or {}).get('exit_mode') or 'overnight')
    except Exception:
        v = 'overnight'
    return v.lower()


def _is_live(evidence):
    """True when a paper_trades row was created by the live watcher.

    Legacy/test rows carry no `origin` marker and are excluded from live
    performance rather than being counted as genuine production trades."""
    try:
        ev = json.loads(evidence or '{}') or {}
    except (TypeError, ValueError):
        return False
    return ev.get('origin') == LIVE_ORIGIN


class PaperTradeEngine:
    def __init__(self):
        # Connections are opened per call, never cached on the instance.
        # A module-level engine reused across gunicorn gthread workers raised
        # sqlite3.ProgrammingError("SQLite objects created in a thread can only
        # be used in that same thread") on /api/<symbol>/paper-trade. See R-02.
        pass

    def create_paper_trade(self, qualified_trade, link_key=None):
        """Persist one paper trade for a qualified (frozen) live signal.

        When `link_key` is supplied the trade_id is derived deterministically
        from it and an `origin='live-watch'` marker is written, so repeated
        scheduler runs, retries and concurrent processes create AT MOST ONE
        trade per event (the trade_id is the PRIMARY KEY). Without `link_key`
        the legacy random-id behaviour is preserved for callers/tests.
        """
        q = dict(qualified_trade or {})
        if link_key is not None:
            q.setdefault('origin', LIVE_ORIGIN)
            q.setdefault('watch_key', link_key)
            trade_id = 'PT-' + hashlib.sha1(str(link_key).encode()).hexdigest()[:10].upper()
        else:
            trade_id = f'PT-{str(uuid.uuid4())[:8].upper()}'
        legs = q.get('legs') or []
        # Persist legs JSON (previously dropped as None). strikes/expiry
        # derived from legs when present for auditability.
        try:
            legs_json = json.dumps(legs)
        except (TypeError, ValueError):
            legs_json = "[]"
        strikes = None
        expiry = None
        try:
            if isinstance(legs, list) and legs:
                strikes = json.dumps([l.get("strike") for l in legs if isinstance(l, dict)])
                exps = {l.get("expiry") for l in legs if isinstance(l, dict) and l.get("expiry")}
                expiry = next(iter(exps)) if len(exps) == 1 else None
        except Exception:
            pass
        # Fall back to explicit fields if caller supplied them.
        if q.get('strikes') and not strikes:
            strikes = q.get('strikes') if isinstance(q.get('strikes'), str) else json.dumps(q.get('strikes'))
        if q.get('expiry'):
            expiry = q.get('expiry')
        conn = get_conn()
        try:
            existing = conn.execute(
                'SELECT trade_id FROM paper_trades WHERE trade_id=?', (trade_id,)).fetchone()
            if existing:
                conn.close()
                return trade_id
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        # Correlated-exposure cap: a second instrument firing the SAME
        # directional view on the same session is the same idea, not a
        # second bet. Skipped instead of sized down so the ledger keeps one
        # unambiguous position per direction per day.
        if link_key is not None:
            blocked = self._correlated_block(
                (q.get('instrument_id') or '').upper(),
                _direction_sign(q.get('direction')),
                q.get('entry_time'), max_positions_per_direction())
            if blocked:
                log.warning('paper trade skipped %s: correlated position cap '
                            '(existing %s %s, cap %d)',
                            q.get('instrument_id'), blocked.get('trade_id'),
                            blocked.get('instrument_id'), max_positions_per_direction())
                return None
        conn = get_conn()
        try:
            existing = conn.execute(
                'SELECT trade_id FROM paper_trades WHERE trade_id=?', (trade_id,)).fetchone()
            if existing:
                return trade_id
            try:
                conn.execute('''INSERT INTO paper_trades (trade_id, instrument_id, scenario, strategy, objective, direction, legs, strikes, expiry, entry, stop, target, max_risk, expected_reward, entry_time, status, qualification_evidence, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (trade_id, q.get('instrument_id'), q.get('scenario'), q.get('strategy'), q.get('objective'), q.get('direction'), legs_json, strikes, expiry, q.get('entry'), q.get('stop'), q.get('target'), q.get('max_risk'), q.get('expected_reward'), q.get('entry_time') or datetime.now(_IST).isoformat(), 'ACTIVE', json.dumps(q, default=str), datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat()))
                conn.commit()
            except sqlite3.IntegrityError:
                # Concurrent creator won the race on the PRIMARY KEY: either
                # way exactly one trade exists for this link_key. Roll back and
                # return the stable id (never raise, never duplicate).
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            conn.close()
        return trade_id

    def _correlated_block(self, instrument, sign, entry_time, cap):
        """Return the open position that blocks a new one, or None.

        Only LIVE rows are considered (the watcher passes link_key, which
        marks the row origin='live-watch'); synthetic/test rows are not
        risk-managed.
        """
        if not cap or cap <= 0:
            return None
        day = (entry_time or datetime.now(_IST).isoformat())[:10]
        conn = get_conn()
        try:
            rows = conn.execute(
                'SELECT trade_id, instrument_id, direction, entry_time '
                'FROM paper_trades WHERE status IN ("ACTIVE","OPEN")').fetchall()
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass
        opened = [dict(r) for r in rows]
        same = [r for r in opened
                if _direction_sign(r.get('direction')) == sign
                and (r.get('entry_time') or '')[:10] == day]
        return same[0] if len(same) >= cap else None

    def monitor(self, instrument_id):
        """Next-bar, no-lookahead monitor.

        For each ACTIVE/OPEN trade, evaluate the OPEN of 5m candles with
        timestamp STRICTLY AFTER entry_time (entry<t<=exit) via the shared
        `exits_opens` routine: 0.5% stop / 2% target, STOP-first tie-break.
        The exit is booked at the REAL recorded open (gapped or not), matching
        the live alert exit sweep and the approved opens-execution spec.
        """
        conn = get_conn()
        try:
            trades = conn.execute('SELECT * FROM paper_trades WHERE instrument_id=? AND status IN ("ACTIVE", "OPEN")', (instrument_id,)).fetchall()
            results = []
            for t in trades:
                t = dict(t)
                entry_time = t.get('entry_time') or ""
                direction = t.get('direction') or "LONG"
                sign = _direction_sign(direction)
                entry = t.get('entry') or 0
                # Post-entry candle OPENS only: entry_bar < t (no lookahead).
                eod_mode = (paper_exit_mode() == 'eod')
                try:
                    if eod_mode:
                        rows = conn.execute(
                            'SELECT timestamp, open FROM market_candles_5m '
                            'WHERE instrument_id=? AND timestamp > ? AND substr(timestamp,1,10)=? '
                            'ORDER BY timestamp',
                            (instrument_id, entry_time, (entry_time or '')[:10])).fetchall()
                    else:
                        rows = conn.execute(
                            'SELECT timestamp, open FROM market_candles_5m WHERE instrument_id=? AND timestamp > ? ORDER BY timestamp',
                            (instrument_id, entry_time)).fetchall()
                    opens = [(r['timestamp'], r['open']) for r in rows]
                except Exception:
                    opens = []
                filled = False
                current_price = None
                try:
                    snap = conn.execute('SELECT price FROM market_snapshots WHERE instrument_id=? ORDER BY timestamp DESC LIMIT 1', (instrument_id,)).fetchone()
                    current_price = snap['price'] if snap else None
                except Exception:
                    pass
                dir_word = 'BULL' if sign > 0 else 'BEAR'
                is_scalp = str(t.get('scenario') or '').upper() == 'SCALP_HLC' or 'SCALP' in str(t.get('strategy') or '').upper()
                res = None
                exit_ts = None
                try:
                    if is_scalp:
                        sl = t.get('stop')
                        tg = t.get('target')
                        if sl is None or tg is None:
                            res = None
                        else:
                            # absolute stop/target using recorded candle opens
                            risk = abs(float(entry) * 0.0)  # placeholder, not used
                            for ts, o in opens:
                                try:
                                    o = float(o)
                                    slf = float(sl); tgf = float(tg)
                                except (TypeError, ValueError):
                                    continue
                                if dir_word == 'BULL':
                                    s_hit = o <= slf
                                    t_hit = o >= tgf
                                else:
                                    s_hit = o >= slf
                                    t_hit = o <= tgf
                                if s_hit:
                                    res = (-1.0, round(o, 2), 'STOP', ts)
                                    break
                                if t_hit:
                                    res = (round(abs(tgf - float(entry)) / abs(float(entry) - slf), 3) if abs(float(entry)-slf) else 0.0,
                                           round(o, 2), 'TARGET', ts)
                                    break
                    else:
                        from app.research.cpr_trigger_engine import (
                            exits_opens, OPEN_STOP_PCT, OPEN_TARGET_PCT)
                        res = exits_opens(dir_word, float(entry), OPEN_STOP_PCT,
                                          OPEN_TARGET_PCT, opens)
                except Exception:
                    res = None
                if res:
                    _r, xp, reason, _xts = res
                    if reason in ('STOP', 'TARGET') and xp is not None:
                        self._exit_trade(t['trade_id'], xp, reason, entry,
                                         direction, instrument_id, conn=conn,
                                         exit_time=_xts)
                        filled = True
                        t['status'] = 'CLOSED'
                        t['exit_price'] = xp
                        t['exit_reason'] = reason
                elif eod_mode:
                    # Published-spec parity: flat at the 15:20 open of the
                    # entry session when neither the stop nor the target was
                    # reached. Only settled once the session is over, so a
                    # half-finished session never books a premature exit.
                    eod_px = None
                    for _ts, _o in opens:
                        if _ts[11:16] == '15:20':
                            eod_px = _o
                    if eod_px is None and opens:
                        from datetime import time as _time
                        if datetime.now(_IST).time() > _time(15, 30):
                            eod_px = opens[-1][1]
                    if eod_px is not None:
                        self._exit_trade(t['trade_id'], eod_px, 'EOD-1520', entry,
                                         direction, instrument_id, conn=conn)
                        filled = True
                        t['status'] = 'CLOSED'
                        t['exit_price'] = eod_px
                        t['exit_reason'] = 'EOD-1520'
                results.append({**t, 'current_price': current_price, 'filled': filled})
            return results
        finally:
            conn.close()

    def _exit_trade(self, trade_id, exit_price, reason, entry_price=None, direction=None, instrument_id=None, conn=None, exit_time=None):
        """PnL = (exit-entry)*lot*dir - costs (fixes stop-fill using current price).

        entry_price/direction/instrument resolved from DB when not passed
        (backward-compatible with old 4-arg calls). `conn` reuses the caller's
        per-request connection when supplied.
        """
        own = conn is None
        if own:
            conn = get_conn()
        try:
            entry = entry_price
            direction = direction or "LONG"
            instrument = instrument_id
            if entry is None or instrument is None:
                try:
                    row = conn.execute('SELECT entry, direction, instrument_id FROM paper_trades WHERE trade_id=?', (trade_id,)).fetchone()
                    if row:
                        rd = dict(row)
                        if entry is None:
                            entry = rd.get('entry') or 0
                        if direction is None or direction == "LONG":
                            direction = rd.get('direction') or direction or "LONG"
                        if instrument is None:
                            instrument = rd.get('instrument_id')
                except Exception:
                    pass
            entry = entry or 0
            lot = _lot(instrument)
            sign = _direction_sign(direction)
            try:
                signed_pts = (float(exit_price) - float(entry)) * sign
            except (TypeError, ValueError):
                signed_pts = 0.0
            costs = BROKERAGE_RS + SLIPPAGE_PTS * lot
            pnl = round(signed_pts * lot - costs, 2)
            _exit_ts = exit_time or datetime.now(_IST).isoformat()
            conn.execute('UPDATE paper_trades SET exit_price=?, exit_reason=?, exit_time=?, status=?, paper_pnl=?, updated_at=? WHERE trade_id=?',
                (exit_price, reason, _exit_ts, 'CLOSED', pnl, datetime.now(_IST).isoformat(), trade_id))
            conn.commit()
            # Feed the performance event stream: without this the live
            # ledger never wrote paper_trade_events, so the learning /
            # performance pipeline had no production data at all.
            try:
                from app.paper_trade.performance import record_performance
                record_performance(trade_id)
            except Exception as e:
                log.warning('performance record failed for %s: %s',
                            trade_id, str(e)[:120])
        finally:
            if own:
                conn.close()
