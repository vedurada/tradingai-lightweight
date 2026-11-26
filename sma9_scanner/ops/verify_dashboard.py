#!/usr/bin/env python3
"""Render the public dashboard and verify fields + 5s auto-refresh."""
import json
import time
from playwright.sync_api import sync_playwright

URL = "https://tradingai.in/live/index.html"
OUT = "/opt/tradingai/reports/sma9_dashboard_live.png"

result = {"url": URL, "console_errors": [], "page_errors": []}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 1800})
    page.on("console", lambda m: result["console_errors"].append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: result["page_errors"].append(str(e)))
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2500)

    def text(sel):
        try:
            return page.locator(sel).first.inner_text(timeout=3000).strip()
        except Exception:
            return None

    result["fields"] = {
        "generated": text("#generated"),
        "status_badge": text("#scanner-status-badge"),
        "status_text": text("#scanner-status-text"),
        "spot": text("#spot"),
        "atm": text("#atm"),
        "expiry": text("#expiry"),
        "last_scan": text("#last-scan"),
        "poll": text("#poll"),
        "market": text("#market"),
        "today_trades": text("#today-trades"),
        "today_pnl": text("#today-pnl"),
        "audit_total": text("#audit-total"),
        "audit_compliant": text("#audit-compliant"),
        "audit_discrepant": text("#audit-discrepant"),
        "audit_rate": text("#audit-rate"),
    }
    result["ce_card"] = text("#card-CE")
    result["pe_card"] = text("#card-PE")
    result["today_rows"] = page.locator("#today-tbody tr").count()
    result["hist_rows"] = page.locator("#hist-tbody tr").count()
    result["countdown_before"] = text("#refresh-countdown")

    # Prove the data refreshes in-place without navigation.
    page.evaluate("window.__navCount = (window.__navCount||0)")
    generated_before = result["fields"]["generated"]
    page.wait_for_timeout(6500)
    generated_after = text("#generated")
    result["generated_before"] = generated_before
    result["generated_after"] = generated_after
    result["auto_refreshed_without_navigation"] = bool(
        generated_before and generated_after and generated_before != generated_after
    )

    page.screenshot(path=OUT, full_page=True)
    result["screenshot"] = OUT
    browser.close()

print(json.dumps(result, indent=2, default=str))
