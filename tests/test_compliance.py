"""Compliance regression tests — no trade-directive content in public UI.

Scope: frontend/*.html + frontend/indices/*.html (static served files).
These tests NEVER touch trading logic, APIs, calculations or the database.
"""
import pathlib
import re
import unittest

FRONTEND = pathlib.Path(__file__).resolve().parent.parent / "frontend"

PAGES = [p.relative_to(FRONTEND).as_posix()
         for p in list(FRONTEND.glob("*.html")) + list((FRONTEND / "indices").glob("*.html"))
         if "frozen" not in p.name and ".pre-" not in p.name
         and "backup" not in p.name and "removed-" not in p.name]

MANDATORY_NOTICE = ("It is not investment advice, a research recommendation, "
                    "or an instruction to buy, sell, or hold any security or derivative.")

# user-facing actionable phrases (negations like "not a recommendation" are fine
# and are covered by allowing the mandatory-notice sentence only)
BANNED_PHRASES = [
    "trade now", "get signals", "get calls", "join telegram", "telegram.me/tradingai_cpr",
    "live trade", "paper trade", "paper-trade", "paper day", "model signal",
    "buy/sell alerts", "entry at", "stop-loss", "stop loss", "take profit",
    "trade alerts", "push notification", "whatsapp", "guaranteed returns",
    "guaranteed profit", "win rate", "winning-trade", "trade calls",
]

OUTLOOK_PAGES = ["index.html", "indices/nifty.html", "indices/banknifty.html"]

# Owner-authorised 2026-09-29: a single model-channel subscribe button on the
# three outlook index pages. No other page may link or name the channel.
ALERT_CHANNELS = ["index.html", "indices/nifty.html", "indices/banknifty.html"]
CHANNEL_URL = "https://telegram.me/tradingai_cpr"
SUBSCRIBE_BLOCK = 'aria-label="Model alert channel"'


def read(rel):
    return (FRONTEND / rel).read_text()


def _channel_free(rel, text):
    """Text with the authorised subscribe block removed."""
    if rel not in ALERT_CHANNELS or SUBSCRIBE_BLOCK not in text:
        return text
    parts = text.split(SUBSCRIBE_BLOCK)
    kept = [parts[0]]
    for seg in parts[1:]:
        end = seg.find("</section>")
        kept.append(seg[end:] if end != -1 else "")
    return SUBSCRIBE_BLOCK.join(kept)


class TestNoActionableContent(unittest.TestCase):
    def test_no_banned_actionable_phrases(self):
        # allow-list: mandatory notice + historical/educational negations
        allowed_res = [
            r"not investment advice.*?instruction to buy, sell, or hold",
            r"does not (send|provide|promise|predict|guarantee)",
            r"do not (predict|guarantee|promise)",
            r"never (guarantee|promise|send|replaces|consider)",
            r"not (a|the) (recommendation|forecast|forecasting|instruction|prediction|success rate)",
            r"no (guarantee|future-prediction|lookahead)",
            r"paper_confluence",
        ]
        for rel in PAGES:
            t = read(rel)
            low = t.lower()
            for phrase in BANNED_PHRASES:
                if CHANNEL_URL.endswith(phrase):
                    # placement is enforced strictly by test_subscribe_block_scope
                    continue
                for m in re.finditer(re.escape(phrase), low):
                    ctx = low[max(0, m.start() - 160):m.end() + 60]
                    ok = any(re.search(a, ctx) for a in allowed_res)
                    self.assertTrue(ok, f"{rel}: actionable phrase '{phrase}' in: ...{ctx[-120:]}")

    def test_no_telegram_links(self):
        for rel in PAGES:
            t = _channel_free(rel, read(rel)).lower()
            self.assertNotIn("t.me/", t, f"{rel}: channel link outside the authorised block")
            self.assertNotIn("telegram", t, f"{rel}: channel reference outside the authorised block")

    def test_subscribe_block_scope(self):
        for rel in PAGES:
            t = read(rel)
            n = t.count(SUBSCRIBE_BLOCK)
            if rel in ALERT_CHANNELS:
                self.assertEqual(n, 1, f"{rel}: expected exactly one subscribe block")
                block = t.split(SUBSCRIBE_BLOCK)[1].split("</section>")[0]
                self.assertEqual(block.count('href="%s"' % CHANNEL_URL), 1,
                                 f"{rel}: subscribe block must link the channel exactly once")
                self.assertNotIn("data-fallback", block,
                                 f"{rel}: copyable fallback line removed, single button only")
                self.assertEqual(block.count(CHANNEL_URL), 1,
                                 f"{rel}: the address must appear only in the button")
                self.assertEqual(block.count('target="_blank"'), 1,
                                 f"{rel}: the single subscribe button must open a new page")
                self.assertNotIn("tg://", block,
                                 f"{rel}: app deep link removed, one button only")
                self.assertIn("not investment advice", block.lower(),
                              f"{rel}: subscribe block must carry the no-advice wording")
            else:
                self.assertEqual(n, 0, f"{rel}: subscribe block not authorised on this page")
                self.assertNotIn(CHANNEL_URL, t, f"{rel}: channel link not authorised on this page")

    def test_no_flashing_trade_badges(self):
        for rel in PAGES:
            t = read(rel)
            self.assertNotIn("tgBlink", t, f"{rel}: alert CTA animation present")
            self.assertNotIn("bullBlink", t, f"{rel}: direction blink animation present")
            self.assertNotIn("bullTextBlink", t, f"{rel}: direction blink animation present")


class TestMandatoryNotice(unittest.TestCase):
    def test_notice_on_outlook_pages(self):
        for rel in OUTLOOK_PAGES + ["tools.html", "backtest.html", "paper.html", "methodology.html"]:
            self.assertIn(MANDATORY_NOTICE, read(rel), f"{rel}: missing mandatory notice")

    def test_no_advice_positioning(self):
        for rel in ["index.html", "methodology.html", "disclaimer.html"]:
            t = read(rel).lower()
            self.assertIn("does not provide investment advice", t,
                           f"{rel}: missing no-advice statement")


class TestOutlookLabels(unittest.TestCase):
    ALLOWED = {"Bullish", "Cautiously Bullish", "Neutral", "Range-bound",
               "Cautiously Bearish", "Bearish", "High Volatility",
               "No Clear Outlook", "Insufficient Data"}

    def test_outlook_enum_closed(self):
        for rel in OUTLOOK_PAGES:
            t = read(rel)
            labels = set(re.findall(r'"(Bullish|Bearish|Neutral[^"]*|Range-bound|High Volatility|No Clear[^"]*|Insufficient[^"]*|Cautiously[^"]*)"', t))
            for lab in labels:
                self.assertIn(lab, self.ALLOWED, f"{rel}: unexpected outlook label '{lab}'")

    def test_confidence_enum(self):
        for rel in OUTLOOK_PAGES:
            t = read(rel)
            self.assertTrue("Confidence" in t or "confidence" in t,
                            f"{rel}: missing confidence display")


class TestLegalPresence(unittest.TestCase):
    def test_legal_pages_exist_and_linked(self):
        for slug in ["disclaimer.html", "terms.html", "privacy.html",
                     "refund-policy.html", "affiliate-disclosure.html",
                     "tools.html", "learn.html", "methodology.html", "contact.html"]:
            self.assertTrue((FRONTEND / slug).exists(), f"missing legal/hub page {slug}")
        home = read("index.html")
        for slug in ["disclaimer.html", "terms.html", "privacy.html",
                     "refund-policy.html", "affiliate-disclosure.html"]:
            self.assertIn(f"/{slug}", home, f"home footer missing {slug}")

    def test_review_placeholders_flagged(self):
        for rel in ["disclaimer.html", "terms.html", "privacy.html", "refund-policy.html"]:
            t = read(rel).lower()
            self.assertTrue("qualified" in t and ("review" in t or "placeholder" in t),
                            f"{rel}: missing professional-review flag")


if __name__ == "__main__":
    unittest.main()
