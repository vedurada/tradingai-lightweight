import logging
import json
import uuid
from datetime import datetime, timezone


def _json_serializer(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as JSON with monitoring fields."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "endpoint"):
            log_entry["endpoint"] = record.endpoint
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "error_code"):
            log_entry["error_code"] = record.error_code
        if hasattr(record, "latency_ms"):
            log_entry["latency_ms"] = record.latency_ms
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id
        if hasattr(record, "alert_type"):
            log_entry["alert_type"] = record.alert_type
        if hasattr(record, "severity"):
            log_entry["severity"] = record.severity
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=_json_serializer)


def setup_logging(log_level="INFO", log_file=None):
    logger = logging.getLogger("tradingai")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(console_handler)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(StructuredJsonFormatter())
            logger.addHandler(file_handler)
    return logger


def get_logger():
    return logging.getLogger("tradingai")


def log_request(logger, endpoint, status_code, error_code=None, latency_ms=None, correlation_id=None, message="Request completed"):
    extra = {
        "endpoint": endpoint,
        "status_code": status_code,
    }
    if error_code:
        extra["error_code"] = error_code
    if latency_ms is not None:
        extra["latency_ms"] = round(latency_ms, 2)
    if correlation_id:
        extra["correlation_id"] = correlation_id
    level = logging.WARNING if status_code >= 400 else logging.INFO
    logger.log(level, message, extra=extra)


def log_alert(logger, alert_type, severity, correlation_id=None, **kwargs):
    extra = {
        "alert_type": alert_type,
        "severity": severity,
    }
    if correlation_id:
        extra["correlation_id"] = correlation_id
    extra.update(kwargs)
    level = logging.CRITICAL if severity == "CRITICAL" else logging.WARNING
    logger.log(level, f"Alert: {alert_type}", extra=extra)
