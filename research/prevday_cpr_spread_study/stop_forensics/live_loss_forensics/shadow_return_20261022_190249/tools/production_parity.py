"""Production parity check: the study's replica vs the live production source.

The production modules are NOT imported (importing app.core.db would open
handles to the live database). Instead the relevant function definitions are
extracted from the production source with ast and executed in an isolated
namespace, then compared with the study replica on randomised inputs.

Read-only: it only reads the two production source files.
"""
import ast
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import prodlib as P  # noqa: E402

STRAT = '/opt/tradingai/app/research/cpr_strategy_engine.py'
TRIG = '/opt/tradingai/app/research/cpr_trigger_engine.py'

FUNCS = {
    STRAT: ['calculate_cpr', 'pivot_levels'],
    TRIG: ['day_levels', 'bear_trigger', 'bull_trigger', 'entry_levels',
           'no_chase_fill', 'breakout_trigger', 'exits_opens', 'decay_win'],
}
CONSTS = {'_ENTRY_LEVELS', '_BREAKOUT_UP', '_BREAKOUT_DN', 'NO_CHASE_BAND_PCT',
          'DECAY_TOL_POINTS'}


def load_production(path, names):
    src = open(path).read()
    tree = ast.parse(src)
    ns = {}
    mods = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            mods.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in CONSTS:
                    mods.append(node)
    code = compile(ast.Module(body=mods, type_ignores=[]), path, 'exec')
    exec(code, ns)
    return ns


def rand_levels(rng):
    base = rng.uniform(20000, 25000)
    return {'pp': base, 'tc': base * 1.005, 'bc': base * 0.995,
            'r1': base * 1.003, 's1': base * 0.997, 'r2': base * 1.006,
            's2': base * 0.994, 'pdh': base * 1.002, 'pdl': base * 0.998,
            'prev_close': base}


def rand_candle(rng):
    o = rng.uniform(20000, 25000)
    return {'timestamp': '2026-07-07T09:20:00+05:30', 'open': o,
            'high': o * (1 + rng.uniform(-0.003, 0.003)),
            'low': o * (1 - rng.uniform(0, 0.004)),
            'close': o * (1 + rng.uniform(-0.003, 0.003))}


def main():
    rng = random.Random(20261022)
    strat = load_production(STRAT, FUNCS[STRAT])
    trig = load_production(TRIG, FUNCS[TRIG])
    # the trigger module imports these from the strategy module
    trig['calculate_cpr'] = strat['calculate_cpr']
    trig['pivot_levels'] = strat['pivot_levels']
    checks = []

    def cmp(name, a, b, ctx):
        ok = (a == b)
        checks.append({'check': name, 'ok': bool(ok), 'prod': str(a)[:120],
                       'replica': str(b)[:120], 'ctx': str(ctx)[:160]})
        return ok

    # calculate_cpr / pivot_levels / day_levels
    for _ in range(400):
        h = rng.uniform(21000, 26000)
        l = h - rng.uniform(50, 600)
        c = rng.uniform(l, h)
        cmp('calculate_cpr', strat['calculate_cpr'](h, l, c),
            P.calculate_cpr(h, l, c), (h, l, c))
        pp = (h + l + c) / 3
        cmp('pivot_levels', strat['pivot_levels'](h, l, pp),
            P.pivot_levels(h, l, pp), (h, l, pp))
        cmp('day_levels', trig['day_levels'](h, l, c), P.day_levels(h, l, c),
            (h, l, c))

    # triggers
    for _ in range(600):
        lv = rand_levels(rng)
        cd = rand_candle(rng)
        cmp('bear_trigger', trig['bear_trigger'](cd, lv), P.bear_trigger(cd, lv), cd)
        cmp('bull_trigger', trig['bull_trigger'](cd, lv), P.bull_trigger(cd, lv), cd)
        cmp('entry_levels', trig['entry_levels'](lv), P.entry_levels(lv), lv)

    # no_chase_fill
    for _ in range(300):
        lv = rand_levels(rng)
        cs = [rand_candle(rng) for _ in range(6)]
        cmp('no_chase_fill', trig['no_chase_fill'](lv, cs, 0),
            P.no_chase_fill(lv, cs, 0), cs)

    # breakout_trigger
    for _ in range(300):
        lv = rand_levels(rng)
        c1 = rand_candle(rng)
        pc = c1['close']
        c2 = rand_candle(rng)
        cmp('breakout_trigger', trig['breakout_trigger'](c2, pc, lv),
            P.breakout_trigger(c2, pc, lv), (c2, pc))

    # exits_opens
    for _ in range(600):
        dr = rng.choice(['BULL', 'BEAR'])
        entry = rng.uniform(20000, 26000)
        stop_pct = 0.005
        target_pct = 0.02
        opens = []
        for _ in range(rng.randint(1, 6)):
            opens.append(('t', round(entry * (1 + rng.uniform(-0.03, 0.03)), 2)))
        cmp('exits_opens', trig['exits_opens'](dr, entry, stop_pct, target_pct, opens),
            P.exits_opens(dr, entry, stop_pct, target_pct, opens), (dr, entry, opens))

    # decay_win
    for _ in range(600):
        dr = rng.choice(['BULL', 'BEAR'])
        inst = rng.choice(['NIFTY', 'BANKNIFTY', 'INDIA_VIX'])
        entry = rng.uniform(20000, 26000)
        xp = entry * (1 + rng.uniform(-0.01, 0.01))
        r = rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0, 4.0])
        cmp('decay_win', trig['decay_win'](dr, entry, xp, r, inst),
            P.decay_win(dr, entry, xp, r, inst), (dr, entry, xp, r, inst))

    failed = [c for c in checks if not c['ok']]
    out = {'checks': len(checks), 'failed': len(failed),
           'failures': failed[:20],
           'per_check': {k: sum(1 for c in checks if c['check'] == k)
                         for k in sorted({c['check'] for c in checks})},
           'source_files': {'strategy': STRAT, 'trigger': TRIG},
           'note': 'production functions extracted with ast; modules never imported'}
    print(json.dumps({k: v for k, v in out.items() if k != 'failures'}, indent=2))
    if failed:
        for f in failed[:10]:
            print('MISMATCH', f)
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
