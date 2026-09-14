"""Track B tests: Product/AdSense readiness (webroot-only, engines frozen).

No engine, signal, or backtest assertions here by design. Guards:
- backend/outlook.py byte-identical to the Track A freeze.
- 0/8 model files unchanged.
"""
import glob
import hashlib
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FREEZE = "3d4f7ca"  # Track A freeze commit
MODELS = ["backend/regime.py", "backend/strategies.py", "backend/outlook.py",
          "backend/scenarios.py", "backend/options.py", "backend/ai_outlook.py",
          "backend/backtest.py", "backend/indicators.py"]


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def html_pages():
    return sorted(glob.glob(os.path.join(ROOT, "*.html")) +
                  glob.glob(os.path.join(ROOT, "*", "*.html")))


class TestAdsTxt:
    def test_file_and_line(self):
        body = read("ads.txt").strip()
        assert body == ("google.com, pub-2262405054444130, DIRECT, "
                        "f08c47fec0942fa0")

    def test_deploy_syncs_ads_txt(self):
        deploy = read("deploy-vm.sh")
        assert "ads.txt" in deploy


class TestConsent:
    def test_consent_js_present_and_shaped(self):
        js = read("static/js/consent.js")
        assert "tai_consent" in js
        assert "requestNonPersonalizedAds" in js
        assert "window.TAIConsent" in js
        assert "getElementBy?" not in js  # no malformed guards

    def test_every_page_loads_consent(self):
        bad = []
        for f in html_pages():
            t = open(f, encoding="utf-8", errors="ignore").read()
            m_consent = re.search(
                r'<script src="([^"]*?consent\.js)"[^>]*>', t)
            if not m_consent:
                bad.append(f)
                continue
        assert bad == []


class TestPrivacy:
    def test_no_false_inactive_claim(self):
        assert "No ad partner is currently active" not in read("privacy.html")

    def test_active_adsense_disclosure(self):
        t = read("privacy.html")
        assert "pub-2262405054444130" in t
        assert "_gads" in t
        assert "adssettings.google.com" in t
        assert "tai-cookie-settings" in t


class TestNavConsistency:
    def test_strategies_has_contact_link(self):
        assert "contact.html" in read("strategies.html")

    def test_footer_link_row_across_root_pages(self):
        missing = [f for f in glob.glob(os.path.join(ROOT, "*.html"))
                   if "contact.html" not in
                   open(f, encoding="utf-8", errors="ignore").read()]
        assert missing == []


class TestAdGuardrails:
    def test_policy_doc(self):
        t = read("ops/AD_PLACEMENT_POLICY.md")
        assert "auto ads" in t and "Forbidden zones" in t

    def test_css_separation_rule(self):
        assert "ins.adsbygoogle" in read("static/css/main.css")


class TestTrustHeaders:
    def test_generated_pages_have_trust_headers(self):
        for rel in ["market/outlook-nifty-2026-09-13.html",
                    "queries/index.html"]:
            t = read(rel)
            assert "<!-- tai-trust-header -->" in t, rel
            assert 'name="author"' in t, rel
            assert "TradingAI.in research team" in t, rel
            assert "educational purposes only" in t, rel

    def test_injector_idempotent(self):
        r = subprocess.run(["python3", "ops/inject_trust_headers.py"],
                           capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0
        assert "0 patched" in r.stdout

    def test_cron_wires_injector_after_outlook(self):
        deploy = read("deploy-vm.sh")
        assert deploy.count("inject_trust_headers.py") >= 2


class TestOwnership:
    def test_about_has_identity_block(self):
        t = read("about.html")
        assert "Publisher:" in t and "Editorial responsibility:" in t
        assert "Last reviewed:" in t and "info@tradingai.in" in t


class TestGoogleTag:
    LEARN_PAGES = ["learn/index.html", "learn/cpr.html",
                   "learn/option-chain.html", "learn/option-greeks.html",
                   "learn/pcr.html", "learn/vwap.html"]

    def test_learn_pages_have_ga_tag(self):
        for rel in self.LEARN_PAGES:
            assert "G-MJ3X88QYEL" in read(rel), rel

    def test_consent_defaults_precede_gtag_load_everywhere(self):
        bad = []
        for f in html_pages():
            t = open(f, encoding="utf-8", errors="ignore").read()
            i_load = t.find("gtag/js?id=G-MJ3X88QYEL")
            i_def = t.find("consent', 'default'")
            if i_load < 0 or i_def < 0 or i_def > i_load:
                bad.append(os.path.basename(f))
        assert bad == []

    def test_accept_grants_via_consent_js(self):
        js = read("static/js/consent.js")
        assert "consent', 'update'" in js and "granted" in js


class TestFrozenBoundary:
    def test_outlook_py_byte_identical_to_freeze(self):
        cur = hashlib.sha256(read("backend/outlook.py").encode()).hexdigest()
        frozen = subprocess.run(
            ["git", "show", f"{FREEZE}:backend/outlook.py"],
            capture_output=True, cwd=ROOT).stdout
        assert hashlib.sha256(frozen).hexdigest() == cur

    def test_zero_model_files_changed(self):
        diff = subprocess.run(
            ["git", "diff", f"{FREEZE}..HEAD", "--name-only"] + MODELS,
            capture_output=True, text=True, cwd=ROOT).stdout.strip()
        assert diff == ""
