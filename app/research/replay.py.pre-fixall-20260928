"""Strict sequential replay harness (research-only).

For every completed 5m candle T in chronological order, the decision state is
built from information available at T only:
  candles with timestamp <= T -> scenario lookup scoped to T ->
  qualification as_of=T -> first-qualifying-signal-of-day -> entry.
Future candles are touched only after entry, solely to determine the exit.
Shares primitives (ScenarioEngine, QualificationEngine, IntradayExitEngine)
with the batch backtest; the loop, lock handling and level math are
independently implemented so batch-vs-replay parity is a real check.
"""
import uuid
from bisect import bisect_right
from datetime import datetime
from app.core.db import get_conn
from app.scenarios.engine import ScenarioEngine
from app.core.qualification import QualificationEngine
from app.research.backtest import IntradayExitEngine

DECISION_SOURCE = 'sequential_replay'


class SequentialReplay:
    def __init__(self):
        self.conn = get_conn()
        self.scenario = ScenarioEngine()
        self.qualification = QualificationEngine()
        self.exit_engine = IntradayExitEngine()
        # Precomputed sorted candidate created_at per instrument so the
        # per-candle scenario_count is O(log n) and never reads future rows.
        self._cand_ts = {}
        for (inst,) in self.conn.execute(
                'SELECT DISTINCT instrument_id FROM scenario_candidates').fetchall():
            self._cand_ts[inst] = sorted(
                r[0] for r in self.conn.execute(
                    'SELECT created_at FROM scenario_candidates WHERE instrument_id=?',
                    (inst,)).fetchall())

    def scenario_count_at(self, instrument, timestamp):
        """Number of scenario candidates knowable at `timestamp` (PIT-safe)."""
        return bisect_right(self._cand_ts.get(instrument, []), timestamp)

    def run(self, instrument, date_start, date_end):
        self.qualification.reset_research_locks()
        candles = [dict(c) for c in self.conn.execute(
            'SELECT * FROM market_candles_5m WHERE instrument_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp',
            (instrument, date_start, date_end)).fetchall()]
        by_day = {}
        for i, c in enumerate(candles):
            by_day.setdefault(c['timestamp'][:10], []).append((i, c))

        traces, trades, daily = [], [], []
        for day in sorted(by_day):
            day_trades = []
            for i, candle in by_day[day]:
                ts = candle['timestamp']
                lock_before = (instrument, day) in self.qualification.research_daily_locks
                scen = self.scenario.get_scenario_for_timestamp(instrument, ts)
                ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE',
                      'volatility': 'NORMAL', 'price': candle['close']}
                q = self.qualification.qualify(instrument, ms, options_valid=True,
                                               research=True, trade_date=day, as_of=ts)
                lock_after = (instrument, day) in self.qualification.research_daily_locks
                sel = None
                if q['decision'] == 'QUALIFIED_TRADE':
                    sel = self._build_trade(instrument, candle, candles, i, q.get('trade') or {})
                    trades.append(sel)
                    day_trades.append(sel)
                cand = scen['candidate'] if scen else None
                traces.append({
                    'instrument': instrument, 'trade_date': day, 'timestamp': ts, 'candle_index': i,
                    'price': candle['close'], 'regime': ms['trend'],
                    'scenario_count': self.scenario_count_at(instrument, ts),
                    'selected_scenario': (cand['scenario_type'] if cand else None),
                    'selected_candidate_id': (cand['candidate_id'] if cand else None),
                    'scenario_timestamp': (cand['created_at'] if cand else None),
                    'scenario_type': (cand['scenario_type'] if cand else None),
                    'scenario_match': (scen['match']['match_state'] if scen and scen['match'] else None),
                    'qualification_status': q['decision'],
                    'qualification_reason': list(q.get('reasons', [])),
                    'qualification': q['decision'], 'reasons': list(q.get('reasons', [])),
                    'daily_lock_before': lock_before, 'daily_lock_after': lock_after,
                    'lock_before': lock_before, 'lock_after': lock_after,
                    'trade_selected': sel is not None,
                    'trade_id': (sel['trade_id'] if sel else None),
                    'entry_time': (sel['entry_time'] if sel else None),
                    'entry_price': (sel['entry_price'] if sel else None),
                    'stop_price': (sel['stop_price'] if sel else None),
                    'target_price': (sel['target_price'] if sel else None),
                    'decision_source': DECISION_SOURCE})
            if day_trades:
                t0 = day_trades[0]
                daily.append({'trade_date': day, 'n_trades': len(day_trades),
                              'first_signal': t0['entry_time'], 'scenario': t0['scenario'],
                              'direction': t0['direction'], 'R_multiple': t0['R_multiple'],
                              'exit_reason': t0['exit_reason']})
        return {'traces': traces, 'trades': trades, 'daily': daily}

    def _build_trade(self, instrument, entry_candle, all_candles, entry_idx, trade_data):
        entry_price = round(trade_data.get('entry', entry_candle['close']), 2)
        stop = round(trade_data.get('stop', entry_price * 0.99), 2)
        target = round(trade_data.get('target', entry_price * 1.02), 2)
        direction = trade_data.get('direction', 'LONG')
        direction = 'LONG' if direction in ('BULLISH', 'LONG') else ('SHORT' if direction in ('BEARISH', 'SHORT') else 'LONG')
        day = entry_candle['timestamp'][:10]
        after = [c for c in all_candles[entry_idx + 1:] if c['timestamp'][:10] == day]
        exit_time, exit_price, reason, mfe, mae = self.exit_engine.find_exit(
            {'entry_price': entry_price, 'stop_price': stop, 'target_price': target,
             'direction': direction, 'entry_time': entry_candle['timestamp']}, after)
        try:
            holding = (datetime.fromisoformat(exit_time) - datetime.fromisoformat(entry_candle['timestamp'])).total_seconds() / 60
        except Exception:
            holding = 0
        move = (exit_price - entry_price) if direction == 'LONG' else (entry_price - exit_price)
        risk = abs(entry_price - stop) if entry_price else 1
        return {'trade_id': str(uuid.uuid4())[:16].upper(), 'instrument': instrument,
                'trade_date': day, 'scenario': trade_data.get('scenario', 'N/A'), 'direction': direction,
                'entry_time': entry_candle['timestamp'], 'entry_price': entry_price,
                'stop_price': stop, 'target_price': target,
                'exit_time': exit_time, 'exit_price': round(exit_price, 2), 'exit_reason': reason,
                'holding_minutes': round(holding, 1),
                'R_multiple': round(move / risk, 2) if risk else 0,
                'paper_pnl': round(move * 50, 2),
                'MFE': round(mfe, 2), 'MAE': round(mae, 2)}
