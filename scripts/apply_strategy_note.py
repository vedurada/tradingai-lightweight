#!/usr/bin/env python3
"""Insert / update the shared model-rule notice on every strategy/signal page.

Rule copy follows app/research/scalp_engine.py: 3-bar HLC alignment, next-open entry,
signal-candle-extreme stop (+/- 1.0) and 1.5R target, 15:25 EOD. This keeps one
uniform notice on every in-scope page.

Idempotent: a page already carrying the current <!--TAIRULE--> block is left
unchanged; a page carrying an OLD block is updated in place. Read-modify-write
only; no trading logic. Backups are written as <page>.pre-rulebrk-20261017.

    cd /opt/tradingai && python3 scripts/apply_strategy_note.py
"""
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(BASE, 'frontend')
STAMP = 'pre-scalp-20261026'

MARKER = '<!--TAIRULE-->'
NOTICE = (
    MARKER
    + '<div class="tairule" role="note" style="background:#fff7ed;border-bottom:1px solid #fed7aa;color:#7c2d12;font-size:.8rem;text-align:center;padding:.5rem .9rem;line-height:1.45">'
    '<b>Active signal rule:</b> NIFTY and BANKNIFTY: every qualifying scalp HLC 3-bar alignment (multiple signals per session possible) — three consecutive 5-minute candles making higher highs, higher lows and higher closes (BULL) or lower highs, lower lows and lower closes (BEAR); enter at the next 5-minute candle open. The stop is the signal candle low minus 1.0 (BULL) or high plus 1.0 (BEAR); target is 1.5x risk; any open position exits at 15:25 IST. No fixed percentage cap. Rule effective 2026-10-26. VIX remains a market gauge, not a traded signal. See <a href="/methodology.html#strategy-rule" style="color:#9a3412;font-weight:600;text-decoration:underline">the complete rules</a>.'
    '</div>'
)

# Any existing notice block (old wording included) -> match for in-place update.
_BLOCK = re.compile(re.escape(MARKER) + r'.*?</div>', re.S)

# Strategy/signal surfaces only (legal + educational option-spread guides excluded).
PAGES = [
    'index.html',
    'indices/nifty.html',
    'indices/banknifty.html',
    'nifty-intraday-dashboard.html',
    'banknifty-intraday-dashboard.html',
    'methodology.html',
    'how-to-use-cpr-intraday.html',
    'how-to-use-website.html',
    'signal-flow.html',
    'signals.html',
    'paper.html',
    'alerts.html',
    'backtest.html',
    'free-backtesting-tool.html',
    'tools.html',
    'learn.html',
]

ANCHOR = '<nav class="main"'


def _write(path, new, changed, already):
    if new is None:
        already.append(os.path.relpath(path, FRONTEND))
        return
    shutil.copyfile(path, path + '.' + STAMP)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | 0o200)
    try:
        open(path, 'w', encoding='utf-8').write(new)
    finally:
        os.chmod(path, mode)
    changed.append(os.path.relpath(path, FRONTEND))


def main():
    changed, already, missing = [], [], []
    for rel in PAGES:
        path = os.path.join(FRONTEND, rel)
        if not os.path.exists(path):
            missing.append(rel)
            continue
        html = open(path, encoding='utf-8').read()
        if _BLOCK.search(html):
            new = _BLOCK.sub(NOTICE, html, count=1)
            _write(path, None if new == html else new, changed, already)
            continue
        idx = html.find(ANCHOR)
        if idx == -1:
            missing.append(rel + ' (no nav anchor)')
            continue
        _write(path, html[:idx] + NOTICE + '\n' + html[idx:], changed, already)
    print('updated  :', ', '.join(changed) or '-')
    print('unchanged:', ', '.join(already) or '-')
    print('missing  :', ', '.join(missing) or '-')
    return 0


if __name__ == '__main__':
    sys.exit(main())
