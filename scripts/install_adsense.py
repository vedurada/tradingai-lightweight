#!/usr/bin/env python3
"""Install the Google AdSense loader into TradingAI HTML pages (idempotent).

The loader alone enables AdSense Auto Ads once Auto Ads is turned on in the
AdSense dashboard -- no ad-slot IDs required. Pass --slot <id> to additionally
drop one responsive in-article unit right after the first </h1> on each page.

Skips 404/error pages (AdSense policy forbids ads on error pages) and all
frozen/pre-/backup/removed backups. Writes a one-time .pre-adsense-<ts> backup
before the first modification of any file.

Usage:
  python3 scripts/install_adsense.py --dry-run
  python3 scripts/install_adsense.py
  python3 scripts/install_adsense.py --slot 1234567890
"""
import argparse
import glob
import os
import re
import shutil
import sys
from datetime import datetime

CLIENT = 'ca-pub-2262405054444130'
LOADER = ('<script async src="https://pagead2.googlesyndication.com/pagead/js/'
          'adsbygoogle.js?client=' + CLIENT + '" crossorigin="anonymous"></script>')
UNIT_TMPL = ('\n<ins class="adsbygoogle" style="display:block;margin:1rem 0" '
             'data-ad-client="%s" data-ad-slot="%s" data-ad-format="auto" '
             'data-full-width-responsive="true"></ins>'
             '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script>\n')

SKIP_NAMES = {'404.html'}
SKIP_SUB = ('frozen', '.pre-', 'backup', 'removed-', 'yandex_')
DEFAULT_ROOT = '/opt/tradingai/frontend'


def should_skip(path):
    name = os.path.basename(path)
    if name in SKIP_NAMES:
        return True
    return any(s in name for s in SKIP_SUB)


def process(path, slot, ts, dry):
    try:
        html = open(path, encoding='utf-8').read()
    except (OSError, UnicodeDecodeError):
        return 'read-error'
    if '</head>' not in html:
        return 'no-head'
    orig = html
    if 'adsbygoogle.js?client=' not in html:
        html = html.replace('</head>', LOADER + '\n</head>', 1)
    if slot and 'data-ad-slot' not in html:
        m = re.search(r'</h1>', html)
        if m:
            html = html[:m.end()] + (UNIT_TMPL % (CLIENT, slot)) + html[m.end():]
    if html == orig:
        return 'ok'
    if dry:
        return 'would-change'
    bak = path + '.pre-adsense-' + ts
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return 'changed'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=DEFAULT_ROOT)
    ap.add_argument('--slot', default='')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    targets = []
    for pat in ('*.html', 'indices/*.html', 'signals/*/*.html'):
        targets += sorted(glob.glob(os.path.join(args.root, pat)))

    counts = {}
    for p in targets:
        if should_skip(p):
            continue
        r = process(p, args.slot, ts, args.dry_run)
        counts[r] = counts.get(r, 0) + 1
        if r in ('changed', 'would-change'):
            print(('DRY ' if args.dry_run else 'WROTE ') + os.path.relpath(p, args.root))

    mode = 'DRY-RUN' if args.dry_run else 'APPLIED'
    slot = args.slot or '(auto-ads, no slot)'
    print(f'[{mode}] client={CLIENT} unit={slot} :: ' +
          ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
