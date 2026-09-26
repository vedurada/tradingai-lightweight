#!/usr/bin/env python3
"""Phase 7 genuine-bug fixes (accounting only; strategy rules untouched).
B1: R_multiple unit mismatch (rupee-PnL / point-risk = 50x true R) -> points/points.
B2: TARGET fill at candle extreme (favorable intrabar assumption) -> fill at target.
B3: MFE/MAE stored as price levels -> favorable/adverse excursions in points.
B4: risk-gate epsilon 1e-9 smaller than 2-decimal rounding noise -> 1e-6."""
import pathlib

bt = pathlib.Path('/opt/tradingai_new/app/research/backtest.py')
src = bt.read_text()

# --- B3: excursion tracking ---
old = """        mfe = entry_price
        mae = entry_price
        
        for c in candles_after_entry:
            high = c['high']
            low = c['low']
            close = c['close']
            ts = c['timestamp']
            
            if direction == 'LONG':
                if high > mfe: mfe = high
                if low < mae: mae = low
            else:
                if low < mfe: mfe = low
                if high > mae: mae = high"""
new = """        # MFE/MAE are excursions in points from entry (both >= 0).
        # MFE = max favorable move, MAE = max adverse move (magnitude).
        mfe = 0.0
        mae = 0.0
        
        for c in candles_after_entry:
            high = c['high']
            low = c['low']
            close = c['close']
            ts = c['timestamp']
            
            if direction == 'LONG':
                if high - entry_price > mfe: mfe = high - entry_price
                if entry_price - low > mae: mae = entry_price - low
            else:
                if entry_price - low > mfe: mfe = entry_price - low
                if high - entry_price > mae: mae = high - entry_price"""
assert old in src, 'B3 anchor missing'
src = src.replace(old, new)

# --- B2: TARGET fills at target (no favorable intrabar assumption) ---
old = """            if target_touched:
                exit_price = max(target, high) if direction == 'LONG' else min(target, low)
                return (ts, exit_price, 'TARGET', mfe, mae)"""
new = """            if target_touched:
                # Fill at target. Never assume the favorable extreme:
                # intrabar ordering above target is unknowable from OHLC.
                return (ts, target, 'TARGET', mfe, mae)"""
assert old in src, 'B2 anchor missing'
src = src.replace(old, new)

# --- B1: points-based R ---
old = """        if direction == 'LONG':
            pnl = (exit_price - entry_price) * 50
        else:
            pnl = (entry_price - exit_price) * 50
        
        risk = abs(entry_price - stop) if entry_price != 0 else 1
        r_multiple = pnl / risk if risk != 0 else 0"""
new = """        if direction == 'LONG':
            pnl = (exit_price - entry_price) * 50
            move_pts = exit_price - entry_price
        else:
            pnl = (entry_price - exit_price) * 50
            move_pts = entry_price - exit_price
        
        risk = abs(entry_price - stop) if entry_price != 0 else 1
        # R must be unit-consistent: points / points. (Dividing rupee-PnL by
        # point-risk inflated R by the 50x lot multiplier. Fixed Phase 7.)
        r_multiple = move_pts / risk if risk != 0 else 0"""
assert old in src, 'B1 anchor missing'
src = src.replace(old, new)

# --- docstring update ---
old = """    Exit precedence:
    1. STOP (same-candle stop+target = AMBIGUOUS -> STOP against trade)
    2. TARGET (same-candle stop+target = AMBIGUOUS -> STOP against trade)
    3. SCENARIO_INVALIDATION
    4. EOD"""
new = """    Exit precedence:
    1. STOP (same-candle stop+target = AMBIGUOUS -> STOP against trade).
       STOP fills at the adverse extreme (conservative gap assumption).
    2. TARGET fills exactly at target (no favorable intrabar assumption).
    3. SCENARIO_INVALIDATION
    4. EOD at last close.
    
    Units: R_multiple = move_points / risk_points (unit-consistent).
    MFE/MAE = favorable/adverse excursions in points from entry (>= 0)."""
assert old in src, 'docstring anchor missing'
src = src.replace(old, new)
bt.write_text(src)
print('backtest.py patched')

rk = pathlib.Path('/opt/tradingai_new/app/risk/engine.py')
rsrc = rk.read_text()
old = '1e-9'
assert rsrc.count(old) == 2, f'expected 2 eps anchors, found {rsrc.count(old)}'
rsrc = rsrc.replace('1e-9', '1e-6')
rsrc = rsrc.replace(
    "        if rr < self.min_reward_risk - 1e-6:",
    "        # eps absorbs 2-decimal rounding noise (~1e-5); true breaches still rejected. (Phase 7)\n"
    "        if rr < self.min_reward_risk - 1e-6:")
rk.write_text(rsrc)
print('risk/engine.py patched (eps 1e-9 -> 1e-6)')
