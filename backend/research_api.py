from __future__ import annotations

import json
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.research_api")


def register_research_routes(app):
    """Register research read-only API routes on the Flask app."""

    @app.route("/api/research/data-health", methods=["GET"])
    def research_data_health():
        from research_collector import ResearchCollector
        from db_schema import DB_PATH
        rc = ResearchCollector(DB_PATH)
        summary = rc.get_research_summary()
        return {
            "status": "ok",
            "research_summary": summary,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @app.route("/api/research/coverage", methods=["GET"])
    def research_coverage():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        summary = re.export_summary()
        datasets = re.get_research_datasets_info()
        return {
            "status": "ok",
            "coverage": summary,
            "datasets": datasets,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @app.route("/api/research/ai-history", methods=["GET"])
    def research_ai_history():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        instrument = None
        try:
            from flask import request
            instrument = request.args.get("instrument", "")
        except Exception:
            pass
        data = re.export_ai_calls(instrument=instrument if instrument else "", limit=500, as_json=True)
        return {"status": "ok", "data": data}

    @app.route("/api/research/setups", methods=["GET"])
    def research_setups():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        instrument = None
        limit = 100
        try:
            from flask import request
            instrument = request.args.get("instrument", "")
            limit = int(request.args.get("limit", 100))
        except Exception:
            pass
        data = re.export_setup_identity(instrument=instrument if instrument else "", limit=limit, as_json=True)
        return {"status": "ok", "data": data}

    @app.route("/api/research/reentries", methods=["GET"])
    def research_reentries():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        instrument = None
        limit = 100
        try:
            from flask import request
            instrument = request.args.get("instrument", "")
            limit = int(request.args.get("limit", 100))
        except Exception:
            pass
        data = re.export_reentry_log(instrument=instrument if instrument else "", limit=limit, as_json=True)
        return {"status": "ok", "data": data}

    @app.route("/api/research/outcomes", methods=["GET"])
    def research_outcomes():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        instrument = None
        limit = 100
        try:
            from flask import request
            instrument = request.args.get("instrument", "")
            limit = int(request.args.get("limit", 100))
        except Exception:
            pass
        data = re.export_outcomes(instrument=instrument if instrument else "", limit=limit, as_json=True)
        return {"status": "ok", "data": data}

    @app.route("/api/research/manifest", methods=["GET"])
    def research_manifest():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        data = re.export_manifest(as_json=True)
        return {"status": "ok", "data": data}

    @app.route("/api/research/summary", methods=["GET"])
    def research_summary():
        from research_exports import ResearchExporter
        from db_schema import DB_PATH
        re = ResearchExporter(DB_PATH)
        data = re.export_summary()
        return {"status": "ok", "summary": data}

    return app
