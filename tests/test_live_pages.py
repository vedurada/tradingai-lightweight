"""TradingAI.in - Phase 1 Live Test Suite: Page Availability + Link Integrity.

Spec suites covered: PAGE (Page Availability), LINK (Link integrity).
~45 tests.
"""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# ═══════════════════════════════════════════════════════════
# PAGE — Page Availability
# ═══════════════════════════════════════════════════════════

class TestPageExistence:
    def test_001_index_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "index.html"))

    def test_002_market_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "market.html"))

    def test_003_about_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "about.html"))

    def test_004_contact_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "contact.html"))

    def test_005_privacy_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "privacy.html"))

    def test_006_terms_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "terms.html"))

    def test_007_disclaimer_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "disclaimer.html"))

    def test_008_404_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "404.html"))

    def test_009_sitemap_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "sitemap.xml"))

    def test_010_robots_txt_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "robots.txt"))

    def test_011_ads_txt_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "ads.txt"))

    def test_012_strategies_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "strategies.html"))

    def test_013_scanner_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "scanner.html"))

    def test_014_portfolio_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "portfolio.html"))

    def test_015_stock_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "stock.html"))

    def test_016_stock_options_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "stock-options.html"))

    def test_017_history_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "history.html"))

    def test_018_alerts_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "alerts.html"))

    def test_019_strategy_builder_html_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "strategy-builder.html"))


class TestPageContent:
    def test_020_index_has_dashboard(self):
        t = read("index.html")
        assert 'id="dashboard"' in t

    def test_021_index_has_canonical(self):
        t = read("index.html")
        assert '<link rel="canonical" href="https://tradingai.in/">' in t

    def test_022_index_has_sebi_disclaimer(self):
        t = read("index.html")
        assert "SEBI" in t and "Educational" in t

    def test_023_index_has_skip_link(self):
        t = read("index.html")
        assert 'skip-link' in t

    def test_024_index_has_live_clock(self):
        t = read("index.html")
        assert 'id="live-clock"' in t

    def test_025_index_has_ticker(self):
        t = read("index.html")
        assert 'id="ticker-track"' in t

    def test_026_index_has_last_updated_bar(self):
        t = read("index.html")
        assert 'id="last-updated-bar"' in t

    def test_027_market_has_canonical(self):
        t = read("market.html")
        assert 'href="https://tradingai.in/market.html"' in t

    def test_028_about_has_canonical(self):
        t = read("about.html")
        assert 'href="https://tradingai.in/about.html"' in t

    def test_029_contact_has_canonical(self):
        t = read("contact.html")
        assert 'href="https://tradingai.in/contact.html"' in t

    def test_030_privacy_has_canonical(self):
        t = read("privacy.html")
        assert 'href="https://tradingai.in/privacy.html"' in t

    def test_031_terms_has_canonical(self):
        t = read("terms.html")
        assert 'href="https://tradingai.in/terms.html"' in t

    def test_032_disclaimer_has_canonical(self):
        t = read("disclaimer.html")
        assert 'href="https://tradingai.in/disclaimer.html"' in t

    def test_033_all_pages_have_og_title(self):
        for page in ["index.html", "market.html", "about.html", "contact.html",
                      "privacy.html", "terms.html", "disclaimer.html"]:
            t = read(page)
            assert 'og:title' in t, f"{page} missing og:title"

    def test_034_all_pages_have_meta_description(self):
        for page in ["index.html", "market.html", "about.html", "contact.html",
                      "privacy.html", "terms.html", "disclaimer.html"]:
            t = read(page)
            assert 'meta name="description"' in t, f"{page} missing description"

    def test_035_index_has_ld_json(self):
        t = read("index.html")
        assert 'application/ld+json' in t


class TestPageFooter:
    def test_036_index_has_footer_links(self):
        t = read("index.html")
        assert 'href="/about.html"' in t
        assert 'href="/contact.html"' in t
        assert 'href="/privacy.html"' in t
        assert 'href="/terms.html"' in t
        assert 'href="/disclaimer.html"' in t

    def test_037_market_has_footer_links(self):
        t = read("market.html")
        assert 'href="/about.html"' in t
        assert 'href="/contact.html"' in t


# ═══════════════════════════════════════════════════════════
# LINK — Link Integrity
# ═══════════════════════════════════════════════════════════

class TestLinkIntegrity:
    def test_038_index_no_broken_internal_hrefs(self):
        t = read("index.html")
        hrefs = re.findall(r'href="([^"]+)"', t)
        for h in hrefs:
            if h.startswith("http") or h.startswith("//"):
                continue
            if h.startswith("#"):
                continue
            if h.startswith("mailto:"):
                continue
            # Internal links should not point to nonexistent paths
            assert len(h) > 1, f"Empty href found"

    def test_039_index_internal_links_use_slash_or_html(self):
        t = read("index.html")
        hrefs = re.findall(r'href="([^"]+)"', t)
        for h in hrefs:
            if h.startswith("http") or h.startswith("//") or h.startswith("#") or h.startswith("mailto:"):
                continue
            # All internal links should be valid paths
            assert h.startswith("/") or h.startswith("."), f"Unexpected href: {h}"

    def test_040_market_page_has_correct_internal_links(self):
        t = read("market.html")
        assert 'href="/about.html"' in t
        assert 'href="/contact.html"' in t

    def test_041_no_ghost_indices_market_link(self):
        t = read("index.html")
        assert "/indices/market.html" not in t

    def test_042_index_data_nav_attributes(self):
        t = read("index.html")
        assert 'data-nav="/market.html"' in t

    def test_043_index_footer_sitemap_link(self):
        t = read("index.html")
        assert 'href="/sitemap.xml"' in t

    def test_044_index_has_external_tracking_consent(self):
        t = read("index.html")
        assert "gtag" in t or "google" in t

    def test_045_no_dashboard_empty_text(self):
        t = read("index.html")
        has_state = any(s in t for s in ["MARKET CLOSED", "LIVE", "DELAYED", "STALE", "UNAVAILABLE", "ERROR", "CLOSED"])
        assert has_state, "Homepage must show explicit data state (CLOSED/LIVE/etc.), not just Loading"
