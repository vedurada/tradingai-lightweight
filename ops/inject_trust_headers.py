#!/usr/bin/env python3
"""Track B: inject authorship/date/disclosure trust headers into generated pages.

Target: market/outlook-*.html + queries/index.html (webroot).
The generator (backend/outlook.py) is FROZEN and is never touched; this
post-processor runs AFTER generation (see crontab). Stdlib only.

Idempotent: presence of the `tai-trust-header` marker skips the file.
Supports --dry-run and --root (webroot, default: repo root '.').
"""
import argparse
import datetime
import os
import re
import sys

MARKER = "<!-- tai-trust-header -->"
AUTHOR_META = '<meta name="author" content="TradingAI.in">'
DISCLAIMER = ("This page is published by TradingAI.in for educational purposes only "
              "and is not investment advice. Market data may be delayed; "
              "verify with your broker before trading.")

DATE_FROM_FILE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE_FROM_TITLE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{4})")


def page_date(path: str, html: str) -> str:
    m = DATE_FROM_FILE.search(os.path.basename(path))
    if m:
        try:
            d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.strftime("%d %B %Y")
        except ValueError:
            pass
    m = DATE_FROM_TITLE.search(html)
    if m:
        return f"{int(m.group(1)):02d} {m.group(2)} {m.group(3)}"
    ts = os.path.getmtime(path)
    return datetime.datetime.fromtimestamp(ts).strftime("%d %B %Y")


def inject(path: str, dry_run: bool = False) -> str:
    """Patch one file. Returns 'patched' | 'skipped' | 'no-anchor'."""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        html = fh.read()
    if MARKER in html:
        return "skipped"
    if "</head>" not in html or "<main>" not in html:
        return "no-anchor"
    date = page_date(path, html)
    byline = (
        f"{MARKER}\n"
        f'    <p class="tai-byline" style="font-size:0.9rem;color:#475569">'
        f"By <strong>TradingAI.in research team</strong> · Published {date} · "
        f"Contact: <a href=\"/contact.html\">contact page</a></p>\n"
        f'    <p class="tai-disclosure" style="font-size:0.85rem;color:#64748b">'
        f"{DISCLAIMER}</p>"
    )
    html = html.replace("</head>", f"    {AUTHOR_META}\n</head>", 1)
    html = html.replace("<main>", f"<main>\n{byline}", 1)
    if not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    return "patched"


def main() -> int:
    ap = argparse.ArgumentParser(description="Inject Track B trust headers.")
    ap.add_argument("--root", default=".",
                    help="webroot containing market/ and queries/ (default: .)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    targets = []
    market = os.path.join(args.root, "market")
    if os.path.isdir(market):
        targets += sorted(os.path.join(market, f) for f in os.listdir(market)
                          if f.startswith("outlook-") and f.endswith(".html"))
    queries = os.path.join(args.root, "queries", "index.html")
    if os.path.isfile(queries):
        targets.append(queries)
    counts = {"patched": 0, "skipped": 0, "no-anchor": 0}
    for path in targets:
        try:
            result = inject(path, dry_run=args.dry_run)
        except OSError as exc:
            print(f"ERROR {path}: {exc}")
            return 1
        counts[result] += 1
        print(f"{result.upper()} {path}")
    print(f"done: {counts['patched']} patched, {counts['skipped']} skipped, "
          f"{counts['no-anchor']} no-anchor (dry_run={args.dry_run})")
    return 0 if counts["no-anchor"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
