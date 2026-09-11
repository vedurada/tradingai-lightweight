# -*- coding: utf-8 -*-
"""Insert unique editorial content card into each page before <footer>."""
import os, sys, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from page_content import CONTENT

def block(filename, paras):
    ps = "\n".join("      <p>%s</p>" % p for p in paras)
    return (
        "\n  <div class=\"card content-card\" style=\"margin-top:1.5rem\">\n"
        "    <h3>%s</h3>\n%s\n"
        "  </div>\n" % (filename.replace(".html", "").replace("/", " - "), ps)
    ) if False else (
        "\n  <div class=\"card content-card\" style=\"margin-top:1.5rem\">\n"
        "    <h3>How to read this page</h3>\n%s\n"
        "  </div>\n" % ps
    )

for fname, paras in CONTENT.items():
    if paras is None:
        print("skip %s" % fname)
        continue
    path = os.path.join(ROOT, fname)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    if "content-card" in html:
        print("already-done %s" % fname)
        continue
    idx = html.rfind("<footer>")
    if idx == -1:
        print("NO-FOOTER %s" % fname)
        continue
    html = html[:idx] + block(fname, paras) + html[idx:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("inserted %s" % fname)