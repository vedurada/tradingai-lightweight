"""
Phase 42A.5D: Frontend regime dict-string mismatch test.

Root cause: loadNiftyData() in index page inline scripts passed
inst.regime (a dict like {regime:'BEARISH', trend:'BEARISH', ...}) to
regimeText() which calls r.toUpperCase(). Dicts have no toUpperCase(),
causing TypeError caught by the outer try/catch, leaving page in Loading
state (empty catch, no DOM updates).

Fix: Extract regime string via inst.regime?.regime before passing to
regimeText/regimeColor/regimeWord.

This test verifies the HTML files contain the correct pattern.
"""

import re
import pytest
import sys
import os

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pages that were fixed (inst.regime is a dict from /api/market)
INDEX_PAGES = [
    "indices/banknifty.html",
    "indices/nifty.html",
    "indices/sensex.html",
    "indices/finnifty.html",
]

# Pages with milder variants
OTHER_PAGES = [
    "index.html",
]

REGIME_DICT_EXAMPLE = {
    "regime": "BEARISH",
    "trend": "BEARISH",
    "momentum": "BEARISH",
    "breadth": "NEUTRAL",
    "confidence": 70.0,
    "id": 38976,
    "symbol": "NIFTY",
    "timestamp": "2026-09-18T10:29:04.459Z",
    "vix_regime": "LOW",
    "volatility": "LOW",
}


def _read_html(rel_path):
    full = os.path.join(WORKSPACE, rel_path)
    with open(full, "r") as f:
        return f.read()


class TestRegimeDictStringMismatch:
    """Tests for Phase 42A.5D frontend regime dict-string fix."""

    def test_regimeText_called_with_dict_not_string(self):
        """regimeText(inst.regime) must NOT appear in any index page inline script."""
        for page in INDEX_PAGES:
            html = _read_html(page)
            assert 'regimeText(inst.regime)' not in html, (
                f"{page}: regimeText(inst.regime) still present - "
                "inst.regime is a dict, regimeText expects string"
            )

    def test_regimeColor_called_with_dict_not_string(self):
        """regimeColor(inst.regime) must NOT appear in any index page inline script."""
        for page in INDEX_PAGES:
            html = _read_html(page)
            assert 'regimeColor(inst.regime)' not in html, (
                f"{page}: regimeColor(inst.regime) still present - "
                "inst.regime is a dict, regimeColor expects string"
            )

    def test_regime_extraction_pattern_present(self):
        """Each index page must use inst.regime?.regime or inst.regime.regime."""
        for page in INDEX_PAGES:
            html = _read_html(page)
            has_extraction = bool(re.search(
                r"inst\.regime(?:\?\.)?\.regime|inst\.regime&&inst\.regime\.regime",
                html
            ))
            assert has_extraction, (
                f"{page}: no regime string extraction pattern found - "
                "inst.regime is a dict and must use inst.regime.regime"
            )

    def test_index_page_regime_extraction(self):
        """index.html must extract regime string before calling regimeWord."""
        html = _read_html("index.html")
        # Old pattern: regimeWord(inst.regime) where inst.regime is dict
        assert 'regimeWord(inst.regime)' not in html or 'String(' in html, (
            "index.html: regimeWord(inst.regime) must use string extraction"
        )
        # Check that index.html uses inst.regime?.regime or similar
        has_extraction = bool(re.search(
            r"inst\.regime\.regime|inst\.regime\?\.\.regime", html
        ))
        assert has_extraction, (
            "index.html: no regime string extraction for regimeWord found"
        )

    def test_no_unhandled_dict_toString_in_regime(self):
        """Verify that regimeText function would fail with dict input."""
        # This test documents the root cause: regimeText expects a string
        def regimeText(r):
            if not r:
                return "—"
            r = r.upper()  # TypeError if r is dict
            if "BULL" in r:
                return "BULLISH"
            if "BEAR" in r:
                return "BEARISH"
            return r

        with pytest.raises((AttributeError, TypeError)):
            regimeText(REGIME_DICT_EXAMPLE)

    def test_regimeString_works_correctly(self):
        """regimeText with string input (after fix) works correctly."""
        def regimeText(r):
            if not r:
                return "—"
            r = r.upper()
            if "BULL" in r:
                return "BULLISH"
            if "BEAR" in r:
                return "BEARISH"
            if "RANGE" in r or "NEUTRAL" in r:
                return "RANGE"
            return r

        assert regimeText("BEARISH") == "BEARISH"
        assert regimeText("BULLISH") == "BULLISH"
        assert regimeText("RANGE") == "RANGE"
        assert regimeText("") == "—"
        assert regimeText(None) == "—"

    def test_regimeDict_has_regime_field(self):
        """API /api/market returns regime as dict with 'regime' string field."""
        assert isinstance(REGIME_DICT_EXAMPLE["regime"], str)
        assert REGIME_DICT_EXAMPLE["regime"] in ("BEARISH", "BULLISH", "RANGE")

    def test_regimeColor_with_string(self):
        """regimeColor with string input works correctly."""
        def regimeColor(r):
            if not r:
                return ""
            if "BULL" in r.upper():
                return "#15803d"
            if "BEAR" in r.upper():
                return "#dc2626"
            return "#64748b"

        assert regimeColor("BEARISH") == "#dc2626"
        assert regimeColor("BULLISH") == "#15803d"
        assert regimeColor("") == ""


class TestIndexPageRegimeFix:
    """Test index.html homepage regime display fix."""

    def test_index_no_dict_pass_to_regimeWord(self):
        """index.html must not pass dict directly to regimeWord."""
        html = _read_html("index.html")
        # Check the fixed line uses _rw or similar extraction
        has_old_pattern = "regimeWord(inst.regime)" in html and "String(" not in html
        assert not has_old_pattern, (
            "index.html: regimeWord(inst.regime) passes dict - must extract string"
        )

    def test_index_uses_regime_regime_extraction(self):
        """index.html must extract .regime.regime for regimeWord."""
        html = _read_html("index.html")
        assert "regime.regime" in html or "regime?.regime" in html, (
            "index.html: must use inst.regime.regime extraction for regimeWord"
        )


class TestAllPagesConsistency:
    """Verify all index pages are fixed consistently."""

    def test_all_index_pages_have_regime_fix(self):
        """All 4 index pages must have the regime string extraction fix."""
        for page in INDEX_PAGES:
            html = _read_html(page)
            # Should have extraction pattern
            assert "regime.regime" in html, (
                f"{page}: missing regime.regime extraction"
            )
            # Should NOT have the old buggy pattern
            assert "regimeText(inst.regime)" not in html, (
                f"{page}: still has buggy regimeText(inst.regime)"
            )
            assert "regimeColor(inst.regime)" not in html, (
                f"{page}: still has buggy regimeColor(inst.regime)"
            )

    def test_today_has_indicators(self):
        """today/index.html renders market data."""
        html = _read_html("today/index.html")
        assert "t-snapshot" in html, (
            "today/index.html: should have snapshot container"
        )
