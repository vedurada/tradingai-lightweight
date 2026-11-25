"""Read-only scalp API endpoints.

Registered in app/api/app.py under the ``/api/scalp`` prefix. Uses the global
Flask-Limiter default_limits configured there; no per-route limiter decorators
(the established pattern in this package).
"""

from flask import Blueprint, jsonify

bp = Blueprint("scalp_api", __name__)


@bp.route("/<instrument>/signals", methods=["GET"])
def scalp_signals(instrument):
    """Get current scalp signals for an instrument."""
    try:
        from app.research.scalp_engine import today_state
        state = today_state(instrument, variant="plain")
        if isinstance(state, dict) and "signals" in state:
            return jsonify({
                "state": "LIVE",
                "timestamp": state.get("date", ""),
                "data": state
            })
        return jsonify({
            "state": "UNAVAILABLE",
            "timestamp": "",
            "data": {"reason": "SCALP_SIGNALS_UNAVAILABLE"}
        })
    except Exception as e:
        return jsonify({
            "state": "UNAVAILABLE",
            "timestamp": "",
            "data": {"reason": f"SCALP_SIGNALS_ERROR: {str(e)}"}
        })


@bp.route("/<instrument>/decision", methods=["GET"])
def scalp_decision(instrument):
    """Get scalp decision data for an instrument."""
    try:
        from app.research.scalp_engine import today_state
        state = today_state(instrument, variant="plain")

        if isinstance(state, dict) and "state" in state:
            if state["state"] == "SIGNAL" and state.get("entry") is not None:
                scalp_data = {
                    "direction": state.get("direction"),
                    "entry": state.get("entry"),
                    "stop": state.get("stop"),
                    "target": state.get("target"),
                    "entry_time": state.get("entry_time"),
                    "signal_time": state.get("signal_time"),
                    "r_multiple": state.get("r_multiple"),
                    "level": state.get("level"),
                    "strategy": "Scalp HLC 3-bar"
                }
                return jsonify({
                    "state": "LIVE",
                    "timestamp": state.get("date", ""),
                    "data": scalp_data
                })
            return jsonify({
                "state": "NO_TRADE",
                "timestamp": "",
                "data": {"reason": "NO_ACTIVE_SCALP_SIGNAL"}
            })
        return jsonify({
            "state": "UNAVAILABLE",
            "timestamp": "",
            "data": {"reason": "SCALP_DATA_UNAVAILABLE"}
        })
    except Exception as e:
        return jsonify({
            "state": "UNAVAILABLE",
            "timestamp": "",
            "data": {"reason": f"SCALP_ERROR: {str(e)}"}
        })


@bp.route("/<instrument>/summary", methods=["GET"])
def scalp_summary(instrument):
    """Get scalp summary data for an instrument."""
    try:
        from app.research.scalp_engine import today_state
        state = today_state(instrument, variant="plain")

        summary_data = {
            "signal_count": state.get("signal_count", 0),
            "signals": state.get("signals", []),
            "candles_so_far": state.get("candles_so_far", 0),
            "last_candle": state.get("last_candle", ""),
            "state": state.get("state", "WATCH"),
            "reason": state.get("reason", "NO_SIGNAL_YET")
        }

        return jsonify({
            "state": "LIVE",
            "timestamp": state.get("date", ""),
            "data": summary_data
        })
    except Exception as e:
        return jsonify({
            "state": "UNAVAILABLE",
            "timestamp": "",
            "data": {"reason": f"SCALP_SUMMARY_ERROR: {str(e)}"}
        })
