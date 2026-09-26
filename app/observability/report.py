"""Phase 17 session report generator.

Produces docs/phase17_live_market_validation.md with all required sections.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')


def generate_report(
    session_info: dict,
    market_data: dict,
    decisions: dict,
    options_info: dict,
    pit_results: dict,
    trace_results: dict,
    health: dict,
    frontend: dict,
    findings: list,
) -> str:
    """Generate the Phase 17 session report as markdown."""
    lines = [
        "# Phase 17: Live Market-Day Validation Report",
        "",
        "## Session Information",
        "",
        f"- **Date**: {session_info.get('date', 'N/A')}",
        f"- **NSE Session Status**: {session_info.get('nse_status', 'N/A')}",
        f"- **Validation Start**: {session_info.get('start_time', 'N/A')}",
        f"- **Validation End**: {session_info.get('end_time', 'N/A')}",
        f"- **Instruments**: {', '.join(session_info.get('instruments', []))}",
        "",
        "## Market Data",
        "",
        f"- **Completed Candles Received**: {market_data.get('completed_candles', 'N/A')}",
        f"- **Missing Intervals**: {market_data.get('missing_intervals', 'N/A')}",
        f"- **Stale Intervals**: {market_data.get('stale_intervals', 'N/A')}",
        f"- **Provider Errors**: {market_data.get('provider_errors', 'N/A')}",
        f"- **Cache Behavior**: {market_data.get('cache_behavior', 'N/A')}",
        "",
        "## Decisions",
        "",
        f"- **Number of Evaluations**: {decisions.get('evaluations', 'N/A')}",
        f"- **States Observed**: {decisions.get('states_observed', 'N/A')}",
        f"- **NO_TRADE Decisions**: {decisions.get('no_trade_count', 'N/A')}",
        f"- **Qualified Decisions**: {decisions.get('qualified_count', 'N/A')}",
        f"- **Daily Lock Result**: {decisions.get('daily_lock_result', 'N/A')}",
        f"- **NO_TRADE Reasons**: {decisions.get('no_trade_reasons', 'N/A')}",
        "",
        "## Options Data",
        "",
        f"- **Provider/Source**: {options_info.get('provider', 'N/A')}",
        f"- **Availability**: {options_info.get('availability', 'N/A')}",
        f"- **Freshness**: {options_info.get('freshness', 'N/A')}",
        f"- **Valid Contracts Observed**: {options_info.get('valid_contracts', 'N/A')}",
        f"- **Rejected Contracts**: {options_info.get('rejected_contracts', 'N/A')}",
        f"- **Strategy Economics Available**: {options_info.get('economics_available', 'N/A')}",
        "",
        "## PIT Integrity",
        "",
        f"- **Sampled Timestamps**: {pit_results.get('sampled_timestamps', 'N/A')}",
        f"- **Results**: {pit_results.get('results', 'N/A')}",
        f"- **Future-Data Checks**: {pit_results.get('future_checks', 'N/A')}",
        "",
        "## Decision Trace",
        "",
        f"- **Sampled Trace IDs**: {trace_results.get('sampled_traces', 'N/A')}",
        f"- **Completeness Result**: {trace_results.get('completeness', 'N/A')}",
        "",
        "## Production Health",
        "",
        f"- **API Latency**: {health.get('api_latency', 'N/A')}",
        f"- **HTTP Errors**: {health.get('http_errors', 'N/A')}",
        f"- **nginx**: {health.get('nginx', 'N/A')}",
        f"- **Gunicorn**: {health.get('gunicorn', 'N/A')}",
        f"- **RAM**: {health.get('ram', 'N/A')}",
        f"- **CPU**: {health.get('cpu', 'N/A')}",
        f"- **Disk**: {health.get('disk', 'N/A')}",
        f"- **SQLite**: {health.get('sqlite', 'N/A')}",
        "",
        "## Frontend",
        "",
        f"- **NIFTY Page**: {frontend.get('nifty', 'N/A')}",
        f"- **BANKNIFTY Page**: {frontend.get('banknifty', 'N/A')}",
        f"- **Mobile/Desktop Observations**: {frontend.get('mobile_desktop', 'N/A')}",
        f"- **Stale-State Behavior**: {frontend.get('stale_behavior', 'N/A')}",
        "",
        "## Findings",
        "",
    ]
    for f in findings:
        classification = f.get('classification', 'INFO')
        description = f.get('description', 'N/A')
        lines.append(f"- **{classification}**: {description}")
    lines.append("")
    return '\n'.join(lines)


def generate_report_from_data(data: dict) -> str:
    """Generate report from a single data dict."""
    return generate_report(
        session_info=data.get('session_info', {}),
        market_data=data.get('market_data', {}),
        decisions=data.get('decisions', {}),
        options_info=data.get('options_info', {}),
        pit_results=data.get('pit_results', {}),
        trace_results=data.get('trace_results', {}),
        health=data.get('health', {}),
        frontend=data.get('frontend', {}),
        findings=data.get('findings', []),
    )
