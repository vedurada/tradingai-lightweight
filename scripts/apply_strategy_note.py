#!/usr/bin/env python3
"""Insert / update the shared model-rule notice on every strategy/signal page.

Rule copy follows app/research/cpr_trigger_engine.py: outer R2/S2 close confirmations,
BEAR-only ordinary base triggers, weekly alignment, Friday BEAR skip, and a gated
close-cross breakout add-on. This keeps one uniform notice on every in-scope page.

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
STAMP = 'pre-daily-short-20261023'

MARKER = '<!--TAIRULE-->'
NOTICE = (
    MARKER
    + '<div class="tairule" role="note" style="background:#fff7ed;border-bottom:1px solid #fed7aa;color:#7c2d12;font-size:.8rem;text-align:center;padding:.5rem .9rem;line-height:1.45">'
    '<b>Active signal rule:</b> NIFTY and BANKNIFTY: take at most one BEAR trade per session after a completed 5-minute close below the current session SMA20; enter at the next 5-minute candle open. If price is already below SMA20 once its first 20-bar value is available, that close qualifies. The stop is 0.5% above entry, target is 2% below, and any open position exits at 15:20 IST. No bullish signals are generated. Rule effective 2026-10-26. VIX remains a market gauge, not a traded signal. See <a href="/methodology.html#strategy-rule" style="color:#9a3412;font-weight:600;text-decoration:underline">the complete rules</a>.'
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
