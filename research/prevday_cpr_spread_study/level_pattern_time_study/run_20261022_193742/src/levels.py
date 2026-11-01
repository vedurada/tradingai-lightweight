"""Level calculations, independently implemented, plus the cross-check
against the production level functions.

The production functions are never imported (importing them would open
handles to the live database); they are extracted from the production source
with ast and executed in an isolated namespace, exactly like the earlier
parity harness did.
"""
import ast
import sys

import config as C

LEVEL_NAMES = ('pp', 'tc', 'bc', 'r1', 'r2', 's1', 's2', 'pdh', 'pdl', 'pdc')

# which side of the price a level acts as
RESISTANCE = ('tc', 'r1', 'r2', 'pdh')
SUPPORT = ('bc', 's1', 's2', 'pdl')
BOUNDARY = ('pp', 'pdc')


def level_side(name):
    if name in RESISTANCE:
        return 'resistance'
    if name in SUPPORT:
        return 'support'
    return 'boundary'


def levels_from_prev(prev_high, prev_low, prev_close):
    """The study's own implementation of the reference levels.

    P  = (H + L + C) / 3
    BC = (H + L) / 2 ; TC = 2P - BC ; the system stores tc >= bc
    R1 = 2P - L ; S1 = 2P - H ; R2 = P + (H - L) ; S2 = P - (H - L)
    PDH = previous high ; PDL = previous low ; PDC = previous close
    """
    p = (prev_high + prev_low + prev_close) / 3.0
    bc = (prev_high + prev_low) / 2.0
    tc = 2.0 * p - bc
    if tc < bc:
        tc, bc = bc, tc
    rng = prev_high - prev_low
    return {
        'pp': p,
        'tc': tc,
        'bc': bc,
        'r1': 2.0 * p - prev_low,
        's1': 2.0 * p - prev_high,
        'r2': p + rng,
        's2': p - rng,
        'pdh': prev_high,
        'pdl': prev_low,
        'pdc': prev_close,
    }


def cpr_width(lv):
    return abs(lv['tc'] - lv['bc'])


def cpr_width_pct(lv):
    return 100.0 * cpr_width(lv) / lv['pp'] if lv['pp'] else 0.0


# ---------------------------------------------------------------------------
# production cross-check
# ---------------------------------------------------------------------------
def _extract(path, names, ns=None):
    """Extract the given top level functions/constants from a source file."""
    src = open(path).read()
    tree = ast.parse(src)
    ns = ns if ns is not None else {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            exec(compile(mod, path, 'exec'), ns)
        elif isinstance(node, ast.Assign):
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id in names:
                try:
                    ns[tgt.id] = ast.literal_eval(node.value)
                except Exception:
                    pass
    return ns


def production_levels():
    """The production level functions, executed in isolation.

    All three functions share ONE namespace so that day_levels can call
    calculate_cpr and pivot_levels exactly as in production.
    """
    ns = {}
    _extract(C.STRATEGY_SRC, ['calculate_cpr', 'pivot_levels'], ns)
    _extract(C.TRIGGER_SRC, ['day_levels'], ns)
    return ns


def compare_levels(prev_high, prev_low, prev_close):
    """Compare the study implementation with the production implementation."""
    ns = production_levels()
    prod = ns['day_levels'](prev_high, prev_low, prev_close)
    mine = levels_from_prev(prev_high, prev_low, prev_close)
    out = {}
    for k in LEVEL_NAMES:
        if k == 'pdc':
            pk = 'prev_close'
        else:
            pk = k
        pv = prod.get(pk)
        mv = mine[k]
        out[k] = {
            'study': round(mv, 6),
            'production': round(float(pv), 6) if pv is not None else None,
            'match': (pv is not None and abs(float(pv) - mv) < 1e-6),
        }
    return out


def nearest_opposing_level(lv, level_name, price, direction):
    """The nearest opposing level and the distance to it.

    direction 'BEAR' (short): the opposing level is the next support below.
    direction 'BULL' (long): the opposing level is the next resistance above.
    """
    if direction == 'BEAR':
        cands = [('bc', lv['bc']), ('s1', lv['s1']), ('s2', lv['s2']),
                 ('pdl', lv['pdl'])]
        below = [(n, v) for n, v in cands if v < price]
        if not below:
            return None, None
        n, v = max(below, key=lambda kv: kv[1])
        return n, round(price - v, 4)
    cands = [('tc', lv['tc']), ('r1', lv['r1']), ('r2', lv['r2']),
             ('pdh', lv['pdh'])]
    above = [(n, v) for n, v in cands if v > price]
    if not above:
        return None, None
    n, v = min(above, key=lambda kv: kv[1])
    return n, round(v - price, 4)


def all_level_prices(lv):
    return {n: lv[n] for n in LEVEL_NAMES}


if __name__ == '__main__':
    print(compare_levels(23000.0, 22500.0, 22800.0))
