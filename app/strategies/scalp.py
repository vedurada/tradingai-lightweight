"""Scalp strategy adapter (HLC 3-bar alignment)."""
from app.research.scalp_engine import first_trigger, today_state, run_opens_range


class ScalpEngine:
    def __init__(self):
        pass

    def today_state(self, instrument, now_ist=None, variant='plain'):
        return today_state(instrument, now_ist=now_ist, variant=variant)

    def run_backtest(self, instrument, date_start, date_end, variant='plain'):
        return run_opens_range(instrument, date_start, date_end, variant=variant)

    def first_trigger(self, candles):
        return first_trigger(candles)
