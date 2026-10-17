"""Unit tests for the no-chase BEAR entry + directional re-anchor (pure, no DB I/O)."""
import sys
sys.path.insert(0, '/opt/tradingai')

from app.research.cpr_trigger_engine import (
    day_levels, NO_CHASE_BEAR, NO_CHASE_BAND_PCT, entry_levels, no_chase_fill)
from app.live.engine import (
    _select_entry_no_chase, _frozen_trade_passes_gate)


def lv():
    # prev H=100, L=90, C=92 -> pp=94, tc=95, bc=93, r1=98, s1=88, r2=104,
    # s2=84, pdh=100, pdl=90  (distinct levels so the tests don't collide)
    return day_levels(100, 90, 92)


def trig():
    # A BEAR trigger candle (index 0); fills are scanned from index 1 onward.
    return {'timestamp': '2026-10-16T09:15:00+05:30',
            'open': 97.5, 'high': 98.0, 'low': 97.4, 'close': 97.6}


def C(o, h, l, ts='2026-10-16T09:20:00+05:30'):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l}


def test_gates_enabled():
    # Re-anchor is gated OFF (2026-10-17 walk-forward: it degrades the book).
    # The helpers below are still tested directly so the code stays correct.
    assert NO_CHASE_BEAR is False
    assert NO_CHASE_BAND_PCT == 0.0015


def test_entry_levels_resistance_then_support():
    names = [(n, d) for n, d, _ in entry_levels(lv())]
    # Resistance first (bear priority), support last.
    assert names[0] == ('R2', 'BEAR')
    assert ('R1', 'BEAR') in names and ('PDH', 'BEAR') in names
    assert ('S1', 'BULL') in names and ('S2', 'BULL') in names
    assert ('PDL', 'BULL') in names
    assert names[-1] == ('PDL', 'BULL')


def test_entry_levels_skips_missing_and_nonpositive():
    assert entry_levels({}) == []
    L = lv()
    L['r2'] = None
    L['s1'] = -1
    names = [n for n, _, _ in entry_levels(L)]
    assert 'R2' not in names and 'S1' not in names and 'R1' in names


def test_no_chase_fill_open_near_resistance_shorts_at_open():
    # open 98.05 is within 0.15% of r1=98 -> BEAR fill at that open.
    j, name, dr, fill = no_chase_fill(lv(), [trig(), C(98.05, 98.1, 98.0)], 0)
    assert (j, name, dr) == (1, 'R1', 'BEAR')
    assert abs(fill - 98.05) < 1e-9


def test_no_chase_fill_limit_at_level_when_range_covers():
    # open 91 is near no level; range 87.5..88.4 covers s1=88 -> limit fill at
    # 88 and the direction RE-ANCHORS to BULL (support).
    j, name, dr, fill = no_chase_fill(lv(), [trig(), C(91.0, 88.4, 87.5)], 0)
    assert (j, name, dr) == (1, 'S1', 'BULL')
    assert fill == 88


def test_no_chase_fill_defers_until_price_returns():
    # candle 1 stays mid-range (near no level) -> skip; candle 2 opens near
    # r2=104 -> defer, then short R2 at that later open.
    candles = [trig(),
               C(91.0, 91.2, 90.8, '2026-10-16T09:20:00+05:30'),
               C(104.05, 104.1, 104.0, '2026-10-16T09:25:00+05:30')]
    j, name, dr, fill = no_chase_fill(lv(), candles, 0)
    assert (j, name, dr) == (2, 'R2', 'BEAR')
    assert abs(fill - 104.05) < 1e-9


def test_no_chase_fill_never_returns_none():
    # price drifts through the middle (between pdl=90 and bc=93) and never
    # comes near a level -> no fill (session skipped).
    candles = [trig(), C(91.0, 91.2, 90.8), C(92.0, 92.2, 91.8)]
    assert no_chase_fill(lv(), candles, 0) is None


def test_no_chase_fill_flips_direction_at_support():
    # Trigger was BEAR (price fell to support); the re-anchor at s2 is BULL.
    j, name, dr, fill = no_chase_fill(lv(), [trig(), C(84.05, 84.1, 84.0)], 0)
    assert (name, dr) == ('S2', 'BULL')
    assert abs(fill - 84.05) < 1e-9


def test_no_chase_fill_below_cpr_uses_bc():
    # A BELOW_CPR break still re-anchors short on a BC retest (bc=93).
    j, name, dr, fill = no_chase_fill(lv(), [trig(), C(93.05, 93.1, 93.0)], 0)
    assert (name, dr) == ('BC', 'BEAR')
    assert abs(fill - 93.05) < 1e-9


def test_no_chase_fill_missing_levels_none():
    assert no_chase_fill({}, [trig(), C(98.05, 98.1, 98.0)], 0) is None


def test_select_entry_no_chase_completed_candle():
    feed = [trig(), C(98.05, 98.1, 98.0)]
    entry, nt, dr, name = _select_entry_no_chase(feed, None, 0, lv())
    assert (name, dr) == ('R1', 'BEAR')
    assert abs(entry - 98.05) < 1e-9
    assert nt == '2026-10-16T09:20:00+05:30'


def test_select_entry_no_chase_forming_open_near_level():
    # No completed fill; the forming candle's OPEN is already near r1.
    feed = [trig()]
    forming = C(98.05, 98.1, 98.0, '2026-10-16T09:20:00+05:30')
    entry, nt, dr, name = _select_entry_no_chase(feed, forming, 0, lv())
    assert (name, dr, nt) == ('R1', 'BEAR', '2026-10-16T09:20:00+05:30')
    assert abs(entry - 98.05) < 1e-9


def test_select_entry_no_chase_forming_range_covers_support():
    # Forming candle has already traded down through s1=88 -> BULL limit fill.
    feed = [trig()]
    forming = C(91.0, 88.4, 87.5, '2026-10-16T09:20:00+05:30')
    entry, nt, dr, name = _select_entry_no_chase(feed, forming, 0, lv())
    assert (name, dr) == ('S1', 'BULL')
    assert entry == 88


def test_select_entry_no_chase_none_when_price_never_returns():
    feed = [trig(), C(91.0, 91.2, 90.8)]
    forming = C(92.0, 92.2, 91.8, '2026-10-16T09:25:00+05:30')
    assert _select_entry_no_chase(feed, forming, 0, lv()) is None


def test_frozen_gate_reanchor_only_when_enabled():
    import app.research.cpr_trigger_engine as eng
    MON, FRI = '2026-10-19', '2026-10-16'   # Monday / Friday
    # Ordinary BULL (no marker) is still rejected under SHORT_ONLY.
    assert _frozen_trade_passes_gate({'direction': 'BULL'}, MON) is False
    b = {'direction': 'BULL', 'no_chase_reanchor': True}
    old = eng.NO_CHASE_BEAR
    try:
        # Re-anchor BULL only passes while the re-anchor feature is enabled.
        eng.NO_CHASE_BEAR = True
        assert _frozen_trade_passes_gate(b, MON) is True
        eng.NO_CHASE_BEAR = False
        assert _frozen_trade_passes_gate(b, MON) is False
    finally:
        eng.NO_CHASE_BEAR = old
    # BEAR still passes; a BEAR on Friday is still dropped.
    assert _frozen_trade_passes_gate({'direction': 'BEAR'}, MON) is True
    assert _frozen_trade_passes_gate({'direction': 'BEAR'}, FRI) is False
