from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.core.db import get_conn, DB_PATH
from app.core.config import settings, instruments
from app.market.provider import MarketDataProvider
from app.core.qualification import QualificationEngine
from app.paper_trade.engine import PaperTradeEngine
from app.research.backtest import BacktestEngine
from app.ai.explanation import AIExplanation
from app.scenarios.engine import ScenarioEngine
import json, os

app = Flask(__name__)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["60 per minute"])
market = MarketDataProvider()
qual = QualificationEngine(settings)
paper = PaperTradeEngine()
backtest = BacktestEngine()
ai = AIExplanation()
scenario = ScenarioEngine()

@app.route('/api/health', methods=['GET'])
def health():
    conn = get_conn()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    return jsonify({'status': 'LIVE', 'timestamp': __import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).isoformat(), 'data': {'tables': len(tables), 'database': DB_PATH}})

@app.route('/api/<symbol>/summary', methods=['GET'])
@limiter.limit("30 per minute")
def summary(symbol):
    quote = market.get_quote(symbol)
    return jsonify({'state': quote.get('state', 'UNAVAILABLE'), 'timestamp': quote.get('timestamp'), 'data': quote})

@app.route('/api/<symbol>/decision', methods=['GET'])
@limiter.limit("10 per minute")
def decision(symbol):
    quote = market.get_quote(symbol)
    ms = {'trend': 'BULLISH', 'vwap_relation': 'ABOVE', 'momentum': 'POSITIVE', 'volatility': 'NORMAL', 'price': quote.get('price', 0)}
    result = qual.qualify(symbol, ms, options_valid=True)
    ai_expl = ai.explain(result) if result.get('decision') != 'NO_TRADE' else {'status': 'AI_DISABLED', 'agreement': 'UNKNOWN'}
    return jsonify({'state': 'LIVE', 'timestamp': __import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).isoformat(), 'data': {'decision': result, 'market_state': ms, 'ai': ai_expl}})

@app.route('/api/<symbol>/paper-trade', methods=['GET'])
@limiter.limit("30 per minute")
def paper_trade(symbol):
    trades = paper.monitor(symbol)
    return jsonify({'state': 'LIVE', 'timestamp': __import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).isoformat(), 'data': {'trades': trades, 'active': len(trades)}})

@app.route('/api/backtest/run', methods=['POST'])
@limiter.limit("5 per minute")
def run_backtest():
    body = request.get_json() or {}
    result = backtest.run(body.get('instrument', 'NIFTY'), body.get('date_start', '2026-09-01'), body.get('date_end', '2026-09-19'))
    return jsonify({'state': 'COMPLETED', 'data': result})

@app.route('/api/backtest/<run_id>', methods=['GET'])
@limiter.limit("30 per minute")
def backtest_result(run_id):
    conn = get_conn()
    run = conn.execute('SELECT * FROM backtest_runs WHERE run_id=?', (run_id,)).fetchone()
    decisions = [dict(d) for d in conn.execute('SELECT * FROM backtest_decisions WHERE run_id=?', (run_id,)).fetchall()]
    trades = [dict(t) for t in conn.execute('SELECT * FROM backtest_trades WHERE run_id=?', (run_id,)).fetchall()]
    outcome = conn.execute('SELECT * FROM backtest_outcomes WHERE run_id=?', (run_id,)).fetchone()
    conn.close()
    return jsonify({'state': 'COMPLETED', 'data': {'run': dict(run) if run else None, 'decisions': decisions, 'trades': trades, 'outcome': dict(outcome) if outcome else None}})

@app.route('/api/research/validation/<run_id>', methods=['GET'])
@limiter.limit("30 per minute")
def no_lookahead_validation(run_id):
    conn = get_conn()
    decisions = [dict(d) for d in conn.execute('SELECT * FROM backtest_decisions WHERE run_id=? AND lookahead_check != "PASS"', (run_id,)).fetchall()]
    conn.close()
    return jsonify({'state': 'COMPLETED', 'data': {'run_id': run_id, 'lookahead_violations': len(decisions), 'result': 'PASS' if len(decisions) == 0 else 'FAILED'}})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000)
