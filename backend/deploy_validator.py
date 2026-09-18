from __future__ import annotations

import os
import sys
import logging
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_schema import DB_PATH, init_database

logger = logging.getLogger("tradingai.deploy")

PAGE_IDENTITY_MARKERS = {
    "index.html": {
        "title_contains": "TradingAI",
        "canonical_marker": "tradingai.in",
        "phase41_marker": "data-completeness",
    },
    "today/index.html": {
        "title_contains": "Today",
        "phase41_marker": "Trade Qualification",
    },
    "indices/nifty.html": {
        "title_contains": "NIFTY",
        "phase41_marker": "Phase 41",
    },
    "indices/banknifty.html": {
        "title_contains": "BANKNIFTY",
        "phase41_marker": "Phase 41",
    },
}


def generate_page_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def generate_expected_manifest(pages_dir: str) -> dict:
    manifest = {}
    for page, markers in PAGE_IDENTITY_MARKERS.items():
        path = os.path.join(pages_dir, page)
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read()
            manifest[page] = {
                "hash": generate_page_hash(content),
                "size": len(content),
                "markers": markers,
                "title_check": _check_title(content, markers["title_contains"]),
                "marker_check": _check_marker(content, markers["phase41_marker"]),
            }
        else:
            manifest[page] = {"error": f"File not found: {path}"}
    return manifest


def _check_title(content: str, expected_substring: str) -> bool:
    import re
    match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if match:
        return expected_substring.lower() in match.group(1).lower()
    return False


def _check_marker(content: str, marker: str) -> bool:
    return marker.lower() in content.lower()


def validate_deployment(
    pages_dir: str,
    api_base_url: str = "http://127.0.0.1:8000",
) -> dict:
    from research_exports import ResearchExporter
    from db_schema import DB_PATH

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": {},
        "overall": "PASS",
    }

    # 1. Page identity check
    manifest = generate_expected_manifest(pages_dir)
    page_checks = {}
    for page, info in manifest.items():
        if "error" in info:
            page_checks[page] = {"status": "FAIL", "reason": info["error"]}
            result["overall"] = "FAIL"
        else:
            checks_passed = all(
                [info.get("title_check", False), info.get("marker_check", False)]
            )
            page_checks[page] = {
                "status": "PASS" if checks_passed else "FAIL",
                "hash": info["hash"],
                "size": info["size"],
                "title_check": info.get("title_check", False),
                "marker_check": info.get("marker_check", False),
            }
            if not checks_passed:
                result["overall"] = "FAIL"
    result["checks"]["page_identity"] = page_checks

    # 2. API health check
    try:
        import urllib.request
        with urllib.request.urlopen(f"{api_base_url}/api/health", timeout=5) as resp:
            health = json.loads(resp.read())
            result["checks"]["api_health"] = {
                "status": "PASS" if health.get("status") == "ok" else "FAIL",
                "response": health,
            }
            if health.get("status") != "ok":
                result["overall"] = "FAIL"
    except Exception as e:
        result["checks"]["api_health"] = {"status": "FAIL", "error": str(e)}
        result["overall"] = "FAIL"

    # 3. Research data check
    try:
        re = ResearchExporter(DB_PATH)
        summary = re.export_summary()
        result["checks"]["research_data"] = {
            "status": "PASS" if summary.get("research_setup_identity", 0) >= 0 else "FAIL",
            "setup_count": summary.get("research_setup_identity", 0),
        }
    except Exception as e:
        result["checks"]["research_data"] = {"status": "FAIL", "error": str(e)}
        result["overall"] = "FAIL"

    # 4. Database check
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        result["checks"]["database"] = {
            "status": "PASS" if len(tables) > 0 else "FAIL",
            "table_count": len(tables),
        }
    except Exception as e:
        result["checks"]["database"] = {"status": "FAIL", "error": str(e)}
        result["overall"] = "FAIL"

    return result