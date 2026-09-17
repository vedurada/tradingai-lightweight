#!/usr/bin/env python3
"""Track C S2: pre-render market snapshot values into static HTML first paint.

Fills the `s-{sym}-{price,trend,vix}` spans (+ regime badge + VIX card) in
index.html from /api/market so crawlers/no-JS clients see numbers, not em-dashes.
Live JS keeps refreshing on top; if the API is unreachable the file is left
untouched (stale values beat blank ones — staleness is stamped, not hidden).

Never fabricates: symbols absent from the API payload keep their placeholders.
The frozen generator/backend is never touched; this runs AFTER data jobs
(deploy sync step + cron, same pattern as inject_trust_headers.py). Stdlib only.

Idempotent. Supports --dry-run, --root (webroot), --api-base.
"""
import argparse
import datetime
import json
import re
import sys
from typing import Optional
import urllib.request

SYMBOLS = {"nifty": "NIFTY", "banknifty": "BANKNIFTY",
           "sensex": "SENSEX", "finnifty": "FINNIFTY"}


def fetch_market(api_base: str) -> dict:
    req = urllib.request.Request(api_base.rstrip("/") + "/api/market",
                                 headers={"User-Agent": "prerender/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fmt_price(v) -> Optional[str]:
    if v is None:
        return None
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return None


def patch_span(html: str, span_id: str, value: Optional[str]) -> str:
    if value is None:
        return html
    return re.sub(r'(id="' + re.escape(span_id) + r'">)[^<]*',
                  r"\g<1>" + value, html, count=1)


def patch_badge(html: str, card_name: str, regime: Optional[str]) -> str:
    if regime is None:
        return html
    pat = (r"(<h3>" + re.escape(card_name) + r"</h3>.*?"
           r'<div class="badge"[^>]*>)[^<]*(</div>)')
    return re.sub(pat, r"\g<1>" + regime + r"\g<2>", html, count=1,
                  flags=re.S)


def prerender(root: str, api_base: str, dry_run: bool = False) -> str:
    path = root.rstrip("/") + "/index.html"
    with open(path, encoding="utf-8", errors="ignore") as fh:
        html = fh.read()
    original_html = html
    data = fetch_market(api_base)
    inst = data.get("instruments") or {}
    vix = inst.get("VIX", {})
    vix_price = fmt_price((vix.get("quote") or {}).get("price"))
    vix_chg = (vix.get("quote") or {}).get("change_pct")
    vix_chg_s = (f"{float(vix_chg):+.2f}%" if vix_chg is not None else None)

    names = {"nifty": "NIFTY 50", "banknifty": "BANKNIFTY",
             "sensex": "SENSEX", "finnifty": "FINNIFTY"}
    for key, sym in SYMBOLS.items():
        item = inst.get(sym) or {}
        q = item.get("quote") or {}
        reg = (item.get("regime") or {}).get("regime")
        html = patch_span(html, f"s-{key}-price", fmt_price(q.get("price")))
        html = patch_badge(html, names[key], reg)
    html = patch_span(html, "s-vix-price", vix_price)
    html = patch_span(html, "s-vix-change", vix_chg_s)

    api_has_data = any(
        fmt_price((inst.get(sym, {}).get("quote") or {}).get("price"))
        for sym in SYMBOLS.values()
    ) or vix_price is not None
    if not api_has_data:
        return "no-data"
    stamp = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ).strftime("%d %b %Y, %H:%M IST")
    html2, n = re.subn(r'data-prerendered="[^"]*"',
                       f'data-prerendered="{stamp}"', html, count=1)
    if n == 0:
        # First run: add the stamp attribute to the snapshot grid div.
        html2, n = re.subn(r"(<!-- MARKET SNAPSHOT -->\s*\n\s*<div )",
                           r"\g<1>" + f'data-prerendered="{stamp}" ',
                           html, count=1)
    if n == 0:
        return "no-anchor"
    if not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html2)
    return "patched"


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-render snapshot first paint.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--api-base", default="http://127.0.0.1:8000")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        print(prerender(args.root, args.api_base, args.dry_run).upper())
        return 0
    except Exception as exc:  # API down etc: leave file untouched
        print(f"SKIP ({exc})")
        return 3


if __name__ == "__main__":
    sys.exit(main())
