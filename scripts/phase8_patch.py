#!/usr/bin/env python3
"""Phase 8 engine change: timestamp-scoped scenario lookup (no strategy change).
- ScenarioEngine.get_scenario_for_timestamp(instrument, ts): latest candidate
  with created_at <= ts (deterministic tiebreak candidate_id ASC) + its latest
  match with timestamp <= ts. get_active_scenario kept for live/API (as-of-now).
- QualificationEngine.qualify(..., as_of=None): scoped lookup when as_of set.
- BacktestEngine._simulate_decision: passes as_of=candle timestamp.
- API replay endpoint: scenarios scoped to created_at <= requested timestamp."""
import pathlib

# --- 1. scenarios/engine.py ---
p = pathlib.Path('/opt/tradingai_new/app/scenarios/engine.py')
s = p.read_text()
old = """    def get_active_scenario(self, instrument_id):"""
new = '''    def get_scenario_for_timestamp(self, instrument_id, timestamp):
        """Point-in-time scenario lookup: latest candidate created at or before
        `timestamp` (deterministic tiebreak on candidate_id), plus its latest
        match at or before `timestamp`. Never reads future state."""
        c = self.conn.execute(
            'SELECT * FROM scenario_candidates WHERE instrument_id=? AND created_at <= ? '
            'ORDER BY created_at DESC, candidate_id ASC LIMIT 1',
            (instrument_id, timestamp)).fetchone()
        if not c:
            return None
        m = self.conn.execute(
            'SELECT * FROM scenario_matches WHERE candidate_id=? AND timestamp <= ? '
            'ORDER BY timestamp DESC LIMIT 1',
            (c['candidate_id'], timestamp)).fetchone()
        return {'candidate': dict(c), 'match': dict(m) if m else None}

    def get_active_scenario(self, instrument_id):'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
print('scenarios/engine.py patched')

# --- 2. core/qualification.py ---
p = pathlib.Path('/opt/tradingai_new/app/core/qualification.py')
s = p.read_text()
old = "    def qualify(self, instrument_id, market_state, options_valid=True, research=False, trade_date=None):"
new = ("    def qualify(self, instrument_id, market_state, options_valid=True, research=False, trade_date=None,\n"
       "                  as_of=None):")
assert old in s
s = s.replace(old, new, 1)
old = "        active = self.scenario.get_active_scenario(instrument_id)"
new = """        # Point-in-time rule: historical decisions (as_of set) use the latest
        # scenario known at that timestamp; live path (as_of None) uses current state.
        if as_of is not None:
            active = self.scenario.get_scenario_for_timestamp(instrument_id, as_of)
        else:
            active = self.scenario.get_active_scenario(instrument_id)"""
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
print('core/qualification.py patched')

# --- 3. research/backtest.py ---
p = pathlib.Path('/opt/tradingai_new/app/research/backtest.py')
s = p.read_text()
old = "        qual_result = self.qualification.qualify(instrument, ms, options_valid=True, research=True, trade_date=trade_date)"
new = "        qual_result = self.qualification.qualify(instrument, ms, options_valid=True, research=True, trade_date=trade_date, as_of=candle['timestamp'])"
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
print('research/backtest.py patched')

# --- 4. api/app.py replay endpoint scoping ---
p = pathlib.Path('/opt/tradingai_new/app/api/app.py')
s = p.read_text()
old = '    scenarios = conn.execute("SELECT * FROM scenario_candidates WHERE instrument_id=? AND created_at LIKE ? ORDER BY created_at DESC", (instrument, f"{date}%")).fetchall()'
new = '    scenarios = conn.execute("SELECT * FROM scenario_candidates WHERE instrument_id=? AND created_at <= ? ORDER BY created_at DESC", (instrument, f"{date}T{timestamp}")).fetchall()'
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
print('api/app.py patched')
