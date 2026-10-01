"""SEO regression tests — static HTML metadata/copy/links only.

Scope: frontend/*.html + frontend/indices/*.html.
These tests NEVER touch trading logic, APIs, calculations or the database.
"""
import json
import pathlib
import re
import unittest

FRONTEND = pathlib.Path(__file__).resolve().parent.parent / "frontend"

CORE_PAGES = [
    "index.html",
    "indices/nifty.html",
    "indices/banknifty.html",
    "backtest.html",
    "methodology.html",
    "paper.html",
    "tools.html",
    "learn.html",
]
GUIDE_PAGES = [
    "cpr-guide.html",
    "credit-spreads.html",
    "narrow-wide-cpr.html",
    "how-to-use-cpr-intraday.html",
    "nifty-support-resistance.html",
    "bull-put-spread.html",
    "bear-call-spread.html",
    "free-backtesting-tool.html",
    "pcr-guide.html",
    "max-pain-guide.html",
    "expected-move-guide.html",
    "option-chain-guide.html",
    "india-vix-guide.html",
]
NEW_KNOWLEDGE_GUIDES = [
    "pcr-guide.html",
    "max-pain-guide.html",
    "expected-move-guide.html",
    "option-chain-guide.html",
    "india-vix-guide.html",
]
LEGAL_PAGES = ["contact.html", "privacy.html", "terms.html", "disclaimer.html",
               "refund-policy.html", "affiliate-disclosure.html"]
ALL_PAGES = CORE_PAGES + GUIDE_PAGES + LEGAL_PAGES

# keyword intent -> (page, terms that must appear, case-insensitive substrings)
KEYWORD_MAP = {
    "NIFTY outlook": ("indices/nifty.html", ["NIFTY Market Outlook", "Observed inputs"]),
    "NIFTY levels": ("indices/nifty.html", ["reference levels", "S1/S2"]),
    "NIFTY CPR": ("indices/nifty.html", ["CPR"]),
    "NIFTY options learning": ("indices/nifty.html", ["options positioning", "put-call ratio (PCR)"]),
    "NIFTY PCR": ("indices/nifty.html", ["PCR"]),
    "NIFTY Max Pain": ("indices/nifty.html", ["Max Pain"]),
    "NIFTY expected move": ("indices/nifty.html", ["expected move"]),
    "NIFTY open interest": ("indices/nifty.html", ["open interest"]),
    "NIFTY support resistance": ("indices/nifty.html", ["support &amp; resistance"]),
    "BANKNIFTY outlook": ("indices/banknifty.html", ["BANKNIFTY Market Outlook"]),
    "BANKNIFTY CPR": ("indices/banknifty.html", ["CPR"]),
    "BANKNIFTY options": ("indices/banknifty.html", ["options positioning", "Max Pain"]),
    "CPR": ("cpr-guide.html", ["Central Pivot Range"]),
    "CPR intraday": ("how-to-use-cpr-intraday.html", ["intraday"]),
    "credit spreads": ("credit-spreads.html", ["Bull Put Spread", "Bear Call Spread"]),
    "options strategy learning": ("methodology.html", ["Bull Put", "Bear Call"]),
    "historical scenarios": ("backtest.html", ["Historical Scenario Analysis", "do not predict future"]),
    "model observations": ("paper.html", ["Historical Model Observations", "Hypothetical"]),
    "PCR knowledge": ("pcr-guide.html", ["Put-Call Ratio", "limitations"]),
    "Max Pain knowledge": ("max-pain-guide.html", ["Max Pain", "limitations"]),
    "Expected Move knowledge": ("expected-move-guide.html", ["Expected Move", "limitations"]),
    "Option chain knowledge": ("option-chain-guide.html", ["Open Interest", "limitations"]),
    "India VIX knowledge": ("india-vix-guide.html", ["India VIX", "limitations"]),
    "tools": ("tools.html", ["payoff", "journal"]),
    "learn hub": ("learn.html", ["Learn Market Concepts"]),
}


def read(rel):
    p = FRONTEND / rel
    assert p.exists(), f"missing page file: {rel}"
    return p.read_text()


def meta_content(html, attr, name):
    m = re.search(r'<meta\s+%s="%s"\s+content="(.*?)"' % (attr, name), html, re.S)
    return m.group(1) if m else None


class TestSEOMetadata(unittest.TestCase):
    def test_title_present_and_unique(self):
        titles = {}
        for rel in ALL_PAGES:
            t = read(rel)
            m = re.search(r"<title>(.*?)</title>", t, re.S)
            self.assertIsNotNone(m, f"{rel}: missing <title>")
            title = m.group(1).strip()
            self.assertGreaterEqual(len(title), 20, f"{rel}: title too short")
            self.assertLessEqual(len(title), 110, f"{rel}: title too long (>110 chars)")
            self.assertNotIn(title, titles, f"{rel}: duplicate title of {titles.get(title)}")
            titles[title] = rel

    def test_meta_description_present_and_unique(self):
        descs = {}
        for rel in ALL_PAGES:
            t = read(rel)
            d = meta_content(t, "name", "description")
            self.assertIsNotNone(d, f"{rel}: missing meta description")
            self.assertGreaterEqual(len(d), 50, f"{rel}: description too short")
            self.assertLessEqual(len(d), 250, f"{rel}: description too long")
            self.assertNotIn(d, descs, f"{rel}: duplicate meta description of {descs.get(d)}")
            descs[d] = rel

    def test_canonical_present(self):
        for rel in ALL_PAGES:
            t = read(rel)
            m = re.search(r'<link\s+rel="canonical"\s+href="(.*?)"', t)
            self.assertIsNotNone(m, f"{rel}: missing canonical")
            self.assertTrue(m.group(1).startswith("https://tradingai.in/"),
                            f"{rel}: canonical not absolute tradingai.in URL")

    def test_exactly_one_h1(self):
        for rel in ALL_PAGES:
            t = read(rel)
            h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", t, re.S)
            self.assertEqual(len(h1s), 1, f"{rel}: expected 1 H1, found {len(h1s)}")

    def test_open_graph_present(self):
        for rel in CORE_PAGES + GUIDE_PAGES:
            t = read(rel)
            for prop in ["og:title", "og:description", "og:url"]:
                self.assertIn(prop, t, f"{rel}: missing {prop}")

    def test_no_signal_marketing_titles(self):
        for rel in ALL_PAGES:
            title = re.search(r"<title>(.*?)</title>", read(rel), re.S).group(1).lower()
            self.assertNotIn("signal", title, f"{rel}: 'signal' in title")


class TestSEOSchema(unittest.TestCase):
    def test_jsonld_valid(self):
        found = 0
        for rel in CORE_PAGES + GUIDE_PAGES:
            t = read(rel)
            blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
            self.assertTrue(blocks, f"{rel}: missing JSON-LD")
            for b in blocks:
                doc = json.loads(b)  # raises on invalid JSON
                self.assertIn("@type", doc, f"{rel}: JSON-LD missing @type")
                found += 1
        self.assertGreaterEqual(found, len(CORE_PAGES + GUIDE_PAGES))


class TestSEOInternalLinks(unittest.TestCase):
    def test_no_broken_internal_page_links(self):
        broken = []
        for rel in ALL_PAGES:
            t = read(rel)
            for href in set(re.findall(r'href="(/[^"#]*?)"', t)):
                path = href.split("?")[0].lstrip("/")
                if path == "":
                    path = "index.html"
                if "#" in href and "." not in path:
                    continue
                if not path.endswith(".html"):
                    continue
                if not (FRONTEND / path).exists():
                    broken.append(f"{rel} -> {href}")
        self.assertEqual(broken, [], f"broken internal links: {broken}")

    def test_methodology_reachable_sitewide(self):
        for rel in CORE_PAGES:
            t = read(rel)
            self.assertIn("/methodology.html", t, f"{rel}: methodology not linked anywhere")

    def test_no_generic_cta_only(self):
        for rel in ["index.html", "methodology.html", "backtest.html"]:
            t = read(rel).lower()
            self.assertNotIn("click here", t, f"{rel}: generic anchor text found")


class TestSEOKeywords(unittest.TestCase):
    def test_keyword_coverage(self):
        for intent, (rel, terms) in KEYWORD_MAP.items():
            t = read(rel).lower()
            for term in terms:
                self.assertIn(term.lower(), t, f"intent '{intent}': {rel} missing '{term}'")


class TestSEODynamicSafety(unittest.TestCase):
    def test_no_fabricated_values_in_static_copy(self):
        bad_patterns = [r"PCR is 0", r"Max Pain is 0", r"Today's NIFTY PCR is",
                        r"PCR</td><td>0", r"VIX is 0"]
        for rel in CORE_PAGES:
            t = read(rel)
            for pat in bad_patterns:
                self.assertIsNone(re.search(pat, t), f"{rel}: fabricated-data pattern '{pat}'")

    def test_unavailable_placeholders_preserved(self):
        for rel in ["index.html", "indices/nifty.html", "indices/banknifty.html", "paper.html"]:
            t = read(rel)
            self.assertTrue("—" in t or "unavailable" in t.lower() or "Connecting" in t,
                            f"{rel}: no unavailable/placeholder state found")


class TestSEOKnowledge(unittest.TestCase):
    def test_guides_have_limitations_and_live_links(self):
        for rel in NEW_KNOWLEDGE_GUIDES:
            t = read(rel).lower()
            self.assertIn("limitation", t, f"{rel}: missing Limitations section")
            self.assertTrue("/indices/nifty.html" in t or "/indices/banknifty.html" in t or 'href="/"' in t,
                            f"{rel}: no link back to live pages")

    def test_instrument_pages_link_knowledge_guides(self):
        for rel in ["indices/nifty.html", "indices/banknifty.html"]:
            t = read(rel)
            for g in NEW_KNOWLEDGE_GUIDES:
                self.assertIn(f"/{g}", t, f"{rel}: missing link to {g}")

    def test_ai_boundary_stated(self):
        for rel in ["index.html", "methodology.html"]:
            t = read(rel).lower()
            self.assertIn("deterministic", t, f"{rel}: missing deterministic-vs-AI boundary")
            self.assertNotIn("llm-generated", t, f"{rel}: claims LLM-generated explanations")

    def test_no_hidden_seo_content(self):
        for rel in ALL_PAGES:
            t = read(rel)
            for m in re.finditer(r'style="[^"]*(display\s*:\s*none|visibility\s*:\s*hidden)[^"]*"[^>]*>(.*?)</',
                                 t, re.S | re.I):
                text = re.sub(r"<[^>]+>", "", m.group(2))
                self.assertLessEqual(len(text.strip()), 100,
                                     f"{rel}: hidden element with substantial text")

    def test_honesty_constraints(self):
        mp = read("max-pain-guide.html")
        self.assertIn("does not compute", mp, "max-pain must state TradingAI does not compute it live")
        for rel in NEW_KNOWLEDGE_GUIDES:
            txt = read(rel).lower()
            self.assertNotIn("guaranteed profit", txt, f"{rel}: guarantee language")
            self.assertNotIn("guaranteed return", txt, f"{rel}: guarantee language")
            self.assertNotIn("guaranteed accur", txt, f"{rel}: guarantee language")


if __name__ == "__main__":
    unittest.main()
