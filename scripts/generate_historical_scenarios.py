#!/usr/bin/env python3
import sys, os, json, sqlite3, uuid, argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, '/opt/tradingai_new')
from app.core.db import get_conn
from app.core.config import instruments

_IST = ZoneInfo('Asia/Kolkata')

SCENARIO_TYPES = [
    'BULLISH_CONTINUATION',
    'BEARISH_CONTINUATION',
    'RANGE_PREMIUM_DECAY',
    'BREAKOUT',
    'BREAKOUT_FAILURE_REVERSAL',
]

STATE_NONE = 'NONE'
STATE_CANDIDATE = 'CANDIDATE'
STATE_CONFIRMED = 'CONFIRMED'
STATE_INVALIDATED = 'INVALIDATED'
STATE_QUALIFIED = 'QUALIFIED'

VALID_TRANSITIONS = {
    STATE_NONE: [STATE_CANDIDATE],
    STATE_CANDIDATE: [STATE_CONFIRMED, STATE_INVALIDATED],
    STATE_CONFIRMED: [STATE_INVALIDATED, STATE_QUALIFIED],
    STATE_INVALIDATED: [],
    STATE_QUALIFIED: [],
}


def calculate_features(candles, idx):
    if idx < 0:
        return {}
    c = candles[idx]
    features = {'timestamp': c['timestamp'], 'price': c['close'], 'volatility': 'NORMAL'}

    # Previous session
    prev_candle = None
    for j in range(idx - 1, -1, -1):
        if candles[j]['timestamp'][:10] != c['timestamp'][:10]:
            prev_candle = candles[j]
            break
    if prev_candle:
        features['prev_close'] = prev_candle['close']
        features['prev_high'] = max(candles[k]['high'] for k in range(
            max(0, idx - 75), idx + 1) if candles[k]['timestamp'][:10] != c['timestamp'][:10])
        features['prev_low'] = min(candles[k]['low'] for k in range(
            max(0, idx - 75), idx + 1) if candles[k]['timestamp'][:10] != c['timestamp'][:10])
        features['prev_range'] = features['prev_high'] - features['prev_low']
        features['prev_direction'] = 'BULLISH' if prev_candle['close'] > prev_candle['open'] else 'BEARISH'
        features['prev_gap'] = c['open'] - prev_candle['close']
    else:
        features.update({'prev_close': None, 'prev_high': None, 'prev_low': None,
                         'prev_range': None, 'prev_direction': None, 'prev_gap': None})

    # Current session
    session_candles = [candles[k] for k in range(idx + 1) if candles[k]['timestamp'][:10] == c['timestamp'][:10]]
    features['session_high'] = max(c['high'] for c in session_candles)
    features['session_low'] = min(c['low'] for c in session_candles)
    features['session_open'] = session_candles[0]['open']
    features['session_range'] = features['session_high'] - features['session_low']

    # Opening range
    features['opening_range_15m'] = None
    features['opening_range_30m'] = None
    features['opening_range_60m'] = None
    if len(session_candles) >= 3:
        o15 = session_candles[:3]
        features['opening_range_15m'] = max(c['high'] for c in o15) - min(c['low'] for c in o15)
    if len(session_candles) >= 6:
        o30 = session_candles[:6]
        features['opening_range_30m'] = max(c['high'] for c in o30) - min(c['low'] for c in o30)
    if len(session_candles) >= 12:
        o60 = session_candles[:12]
        features['opening_range_60m'] = max(c['high'] for c in o60) - min(c['low'] for c in o60)

    # VWAP (cumulative from session start)
    cum_pv = sum(c['close'] * c['volume'] for c in session_candles)
    cum_v = sum(c['volume'] for c in session_candles)
    features['vwap'] = cum_pv / cum_v if cum_v > 0 else c['close']
    features['vwap_relation'] = 'ABOVE' if c['close'] >= features['vwap'] else 'BELOW'

    # Trend and momentum (3-candle)
    if idx >= 3:
        recent = [candles[k]['close'] for k in range(idx - 2, idx + 1)]
        features['trend'] = 'BULLISH' if recent[-1] > recent[0] else 'BEARISH' if recent[-1] < recent[0] else 'NEUTRAL'
        features['momentum'] = 'POSITIVE' if c['close'] > c['open'] else 'NEGATIVE' if c['close'] < c['open'] else 'NEUTRAL'
    else:
        features['trend'] = 'NEUTRAL'
        features['momentum'] = 'NEUTRAL'

    # Recent range (3 and 5 session)
    session_dates = sorted(set(c['timestamp'][:10] for c in candles[:idx + 1]))
    if len(session_dates) >= 2:
        last3 = session_dates[-3:]
        ranges = []
        for sd in last3:
            sd_candles = [c for c in candles if c['timestamp'][:10] == sd]
            if sd_candles:
                ranges.append(max(c['high'] for c in sd_candles) - min(c['low'] for c in sd_candles))
        features['range_3_session'] = sum(ranges) / len(ranges) if ranges else 0
    else:
        features['range_3_session'] = None

    return features


def detect_scenario(features, prev_state=STATE_NONE):
    scenario_states = {}
    for stype in SCENARIO_TYPES:
        state = STATE_NONE
        reason = []

        if stype == 'BULLISH_CONTINUATION':
            is_candidate = (features.get('prev_direction') == 'BULLISH' and
                           features.get('momentum') == 'POSITIVE' and
                           features.get('prev_close') is not None and
                           features.get('price', 0) > features.get('prev_close', 0))
            if is_candidate:
                state = STATE_CANDIDATE
                reason.append('bullish_prev_momentum_positive_above_prev_close')
            if state == STATE_CANDIDATE and features.get('momentum') == 'POSITIVE' and features.get('vwap_relation') == 'ABOVE':
                state = STATE_CONFIRMED
                reason.append('confirmed_momentum_positive_vwap_above')
            if state == STATE_CANDIDATE and features.get('momentum') == 'NEGATIVE':
                state = STATE_INVALIDATED
                reason.append('invalidated_momentum_negative')

        elif stype == 'BEARISH_CONTINUATION':
            is_candidate = (features.get('prev_direction') == 'BEARISH' and
                           features.get('momentum') == 'NEGATIVE' and
                           features.get('prev_close') is not None and
                           features.get('price', 0) < features.get('prev_close', 0))
            if is_candidate:
                state = STATE_CANDIDATE
                reason.append('bearish_prev_momentum_negative_below_prev_close')
            if state == STATE_CANDIDATE and features.get('momentum') == 'NEGATIVE' and features.get('vwap_relation') == 'BELOW':
                state = STATE_CONFIRMED
                reason.append('confirmed_momentum_negative_vwap_below')
            if state == STATE_CANDIDATE and features.get('momentum') == 'POSITIVE':
                state = STATE_INVALIDATED
                reason.append('invalidated_momentum_positive')

        elif stype == 'RANGE_PREMIUM_DECAY':
            prev_range = features.get('prev_range') or features.get('range_3_session')
            curr_range = features.get('session_range')
            if prev_range and curr_range and curr_range < prev_range * 0.5 and features.get('momentum') == 'NEUTRAL':
                state = STATE_CANDIDATE
                reason.append('range_compressed_neutral_momentum')
            if state == STATE_CANDIDATE and features.get('momentum') != 'NEUTRAL':
                state = STATE_INVALIDATED
                reason.append('invalidated_directional_momentum')

        elif stype == 'BREAKOUT':
            breakout_level = features.get('opening_range_15m')
            if breakout_level is None:
                breakout_level = features.get('prev_high')
            ref_high = features.get('prev_high') or features.get('session_high')
            if features.get('price', 0) > (ref_high if ref_high else 0):
                state = STATE_CANDIDATE
                reason.append(f'close_above_ref_high_{ref_high}')
            if state == STATE_CANDIDATE:
                state = STATE_CONFIRMED
                reason.append('confirmed_breakout')

        elif stype == 'BREAKOUT_FAILURE_REVERSAL':
            ref_high = features.get('prev_high')
            if ref_high and features.get('price', 0) > ref_high:
                state = STATE_CANDIDATE
                reason.append('breakout_detected')
            if state == STATE_CANDIDATE and features.get('price', 0) < ref_high:
                state = STATE_INVALIDATED
                reason.append('breakout_failed_reversed')

        scenario_states[stype] = {'state': state, 'reason': reason}

    return scenario_states


def measure_outcomes(candles, idx):
    outcomes = {}
    current_price = candles[idx]['close']

    horizons = [5, 10, 15, 30]
    for h in horizons:
        end_idx = min(idx + h, len(candles) - 1)
        future_candles = candles[idx + 1:end_idx + 1] if idx + 1 < len(candles) else []
        if future_candles:
            prices = [c['high'] for c in future_candles] + [c['low'] for c in future_candles] + [c['close'] for c in future_candles]
            mfe = max(prices) - current_price
            mae = current_price - min(prices)
            future_return = (future_candles[-1]['close'] - current_price) / current_price * 100
        else:
            mfe = mae = future_return = 0
        outcomes[f'{h}c'] = {'mfe': round(mfe, 2), 'mae': round(mae, 2), 'return_pct': round(future_return, 2)}

    # EOD outcome
    session_end = idx
    for k in range(idx + 1, len(candles)):
        if candles[k]['timestamp'][:10] != candles[idx]['timestamp'][:10]:
            break
        session_end = k
    eod_candles = candles[idx + 1:session_end + 1] if idx + 1 < session_end + 1 else []
    if eod_candles:
        prices = [c['high'] for c in eod_candles] + [c['low'] for c in eod_candles] + [c['close'] for c in eod_candles]
        outcomes['eod'] = {'mfe': round(max(prices) - current_price, 2),
                           'mae': round(current_price - min(prices), 2),
                           'return_pct': round((eod_candles[-1]['close'] - current_price) / current_price * 100, 2)}
    else:
        outcomes['eod'] = {'mfe': 0, 'mae': 0, 'return_pct': 0}

    return outcomes


def generate_scenarios(instrument_id, start_date=None, end_date=None):
    conn = get_conn()

    if instrument_id not in [i['instrument_id'] for i in instruments]:
        print(f"Unknown instrument: {instrument_id}")
        conn.close()
        return

    query = 'SELECT * FROM market_candles_5m WHERE instrument_id=?'
    params = [instrument_id]
    if start_date:
        query += ' AND timestamp >= ?'
        params.append(f'{start_date}T00:00:00+05:30')
    if end_date:
        query += ' AND timestamp <= ?'
        params.append(f'{end_date}T23:59:59+05:30')
    query += ' ORDER BY timestamp'

    candles = [dict(c) for c in conn.execute(query, params).fetchall()]
    conn.close()

    if not candles:
        print(f"No candles for {instrument_id}")
        return {}

    print(f"\n{'='*60}")
    print(f"GENERATING SCENARIOS: {instrument_id} ({len(candles)} candles)")
    print(f"{'='*60}")

    # Delete existing scenarios for idempotency
    conn = get_conn()
    conn.execute('DELETE FROM scenario_candidates WHERE instrument_id=?', (instrument_id,))
    conn.execute('DELETE FROM scenario_matches WHERE instrument_id IN (SELECT instrument_id FROM scenario_candidates WHERE instrument_id=?)', (instrument_id,))
    conn.commit()
    conn.close()

    results = {'instrument': instrument_id, 'candles': len(candles), 'scenarios': {}}

    for stype in SCENARIO_TYPES:
        results['scenarios'][stype] = {'candidates': 0, 'confirmed': 0, 'invalidated': 0, 'qualified': 0}

    features_list = []
    for idx in range(len(candles)):
        features = calculate_features(candles, idx)
        features_list.append(features)

        scenario_states = detect_scenario(features)

        outcomes = measure_outcomes(candles, idx) if any(
            s['state'] in (STATE_CONFIRMED, STATE_CANDIDATE) for s in scenario_states.values()) else {}

        for stype, info in scenario_states.items():
            state = info['state']
            if state == STATE_NONE:
                continue

            results['scenarios'][stype][state.lower()] = results['scenarios'][stype].get(state.lower(), 0) + 1

            conn = get_conn()
            candidate_id = f"SC-{instrument_id}-{stype}-{candles[idx]['timestamp'][:10].replace('-','')}-{idx}"
            try:
                conn.execute('''INSERT OR IGNORE INTO scenario_candidates
                    (candidate_id, instrument_id, session_id, scenario_type, historical_context,
                     required_conditions, confirmation_conditions, invalidation_conditions, status, evidence, confidence, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (candidate_id, instrument_id, f"SESS-{candles[idx]['timestamp'][:10]}", stype,
                     json.dumps(features), json.dumps(info.get('reason', [])),
                     json.dumps([]), json.dumps(info.get('reason', [])), state,
                     json.dumps({'features': features, 'outcomes': outcomes}), 1.0,
                     candles[idx]['timestamp'], candles[idx]['timestamp']))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()

    # Print summary
    print(f"\n{'='*60}")
    print(f"SCENARIO SUMMARY: {instrument_id}")
    print(f"{'='*60}")
    for stype, counts in results['scenarios'].items():
        print(f"{stype}: candidates={counts.get('candidates',0)}, confirmed={counts.get('confirmed',0)}, invalidated={counts.get('invalidated',0)}, qualified={counts.get('qualified',0)}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--instrument', required=True, choices=['NIFTY', 'BANKNIFTY'])
    parser.add_argument('--start', default=None)
    parser.add_argument('--end', default=None)
    args = parser.parse_args()

    results = generate_scenarios(args.instrument, args.start, args.end)
    if results:
        path = f'/opt/tradingai_new/data/generated/{args.instrument.lower()}_scenarios.json'
        os.makedirs('/opt/tradingai_new/data/generated', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nReport: {path}")
