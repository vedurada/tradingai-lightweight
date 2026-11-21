"""mStock Type A adapter, translated to the Kite read-only surface."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from broker_gateway.base import BrokerAdapter
from broker_gateway.errors import BrokerCallFailed

BASE = "https://api.mstock.trade/openapi/typea"
DEFAULT_SECRET = "/opt/tradingai/secrets/mstock.env"
DEFAULT_CACHE = "/opt/tradingai/broker_gateway/cache"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_OFFSET_SUFFIX = re.compile(r"([+-]\d{2})$")


def _load_secret() -> dict[str, str]:
    path = pathlib.Path(os.environ.get("MSTOCK_SECRET_FILE", DEFAULT_SECRET))
    cfg: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip().strip("\"'")
    return cfg


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_timestamp(value: str) -> dt.datetime:
    text = _OFFSET_SUFFIX.sub(r"\1:00", value.strip().replace("Z", "+00:00"))
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed


def _as_datetime(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=IST)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(9, 15), tzinfo=IST)
    return _parse_timestamp(str(value))


class MStockAdapter(BrokerAdapter):
    name = "mstock"

    def __init__(self) -> None:
        cfg = _load_secret()
        self.api_key = cfg.get("MSTOCK_API_KEY", "")
        self.access_token = cfg.get("MSTOCK_ACCESS_TOKEN", "")
        if not self.api_key or not self.access_token:
            raise RuntimeError("mStock API key/access token is missing; run mstock_session.py")
        self.cache_dir = pathlib.Path(os.environ.get("BROKER_GATEWAY_CACHE_DIR", DEFAULT_CACHE))
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        self._rows: list[dict] | None = None
        self._token_exchange: dict[int, str] | None = None

    # -- transport -------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "X-Mirae-Version": "1",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        }

    def _get_json(self, path: str, params: dict | None = None) -> dict:
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", "replace"))
                message = body.get("message") or body.get("error_type")
            except Exception:
                message = f"HTTP {exc.code}"
            raise BrokerCallFailed(f"mStock {path}: {message}") from exc
        except Exception as exc:
            raise BrokerCallFailed(f"mStock {path}: {type(exc).__name__}") from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            message = payload.get("message") if isinstance(payload, dict) else payload
            raise BrokerCallFailed(f"mStock {path}: {message}")
        return payload

    # -- master ----------------------------------------------------------
    def _scriptmaster_rows(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        cache = self.cache_dir / "mstock_scriptmaster.csv"
        ttl = int(os.environ.get("BROKER_GATEWAY_MASTER_TTL", "86400"))
        text = None
        if cache.exists() and (time.time() - cache.stat().st_mtime) < ttl:
            text = cache.read_text(encoding="utf-8", errors="replace")
        if text is None:
            req = urllib.request.Request(
                BASE + "/instruments/scriptmaster", headers=self._headers(), method="GET"
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    text = response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                raise BrokerCallFailed(f"mStock scriptmaster: HTTP {exc.code}") from exc
            except Exception as exc:
                raise BrokerCallFailed(f"mStock scriptmaster: {type(exc).__name__}") from exc
            tmp = cache.with_name(cache.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.chmod(0o644)
            os.replace(str(tmp), str(cache))
        self._rows = list(csv.DictReader(io.StringIO(text)))
        return self._rows

    @staticmethod
    def _segment(row: dict) -> str:
        exchange = (row.get("exchange") or "").upper()
        segment = (row.get("segment") or "").upper()
        instrument_type = (row.get("instrument_type") or "").upper()
        if exchange in ("NFO", "BFO"):
            is_option = segment.startswith("OPT") or instrument_type in ("CE", "PE")
            is_future = segment.startswith("FUT") or instrument_type.startswith("FUT")
            if is_option:
                return f"{exchange}-OPT"
            if is_future:
                return f"{exchange}-FUT"
        return row.get("segment") or exchange

    def _token_map(self) -> dict[int, str]:
        if self._token_exchange is None:
            self._token_exchange = {}
            for row in self._scriptmaster_rows():
                try:
                    token = int(row["instrument_token"])
                except (KeyError, TypeError, ValueError):
                    continue
                self._token_exchange[token] = (row.get("exchange") or "").upper()
        return self._token_exchange

    # -- Kite-shaped methods --------------------------------------------
    def instruments(self, exchange: str) -> list[dict]:
        out: list[dict] = []
        for row in self._scriptmaster_rows():
            if (row.get("exchange") or "").upper() != exchange.upper():
                continue
            try:
                token = int(row["instrument_token"])
            except (KeyError, TypeError, ValueError):
                continue
            strike_raw = (row.get("strike") or "").strip()
            out.append(
                {
                    "instrument_token": token,
                    "exchange_token": row.get("exchange_token", ""),
                    "tradingsymbol": row.get("tradingsymbol", ""),
                    "name": row.get("name", ""),
                    "last_price": float(row["last_price"]) if row.get("last_price") else 0.0,
                    "expiry": _parse_date(row.get("expiry")),
                    "strike": float(strike_raw) if strike_raw else 0.0,
                    "tick_size": float(row.get("tick_size") or 0),
                    "lot_size": int(float(row.get("lot_size") or 0)),
                    "instrument_type": row.get("instrument_type", ""),
                    "segment": self._segment(row),
                    "exchange": row.get("exchange", ""),
                }
            )
        return out

    def quote(self, symbols: list[str]) -> dict[str, dict]:
        if isinstance(symbols, str):
            symbols = [symbols]
        result: dict[str, dict] = {}
        for start in range(0, len(symbols), 50):
            batch = symbols[start : start + 50]
            payload = self._get_json(
                "/instruments/quote/ohlc", params=[("i", symbol) for symbol in batch]
            )
            data = payload.get("data") or {}
            for symbol in batch:
                item = data.get(symbol)
                if not item:
                    raise BrokerCallFailed(f"mStock quote: missing symbol {symbol}")
                result[symbol] = {
                    "instrument_token": int(item.get("instrument_token", 0) or 0),
                    "last_price": float(item.get("last_price", 0) or 0),
                    "ohlc": {
                        key: float(value)
                        for key, value in (item.get("ohlc") or {}).items()
                        if value is not None
                    },
                }
        return result

    def historical_data(self, token: int, start, end, interval: str) -> list[dict]:
        token = int(token)
        exchange = self._token_map().get(token)
        if not exchange:
            raise BrokerCallFailed(f"mStock historical: unknown instrument token {token}")
        start_dt = _as_datetime(start)
        end_dt = _as_datetime(end)
        interval = str(interval)
        if interval not in {
            "minute", "3minute", "5minute", "10minute", "15minute",
            "30minute", "60minute", "day",
        }:
            raise BrokerCallFailed(f"mStock historical: unsupported interval {interval}")

        step = dt.timedelta(days=365 if interval == "day" else 10)
        rows: dict[str, dict] = {}
        cursor = start_dt
        while cursor < end_dt:
            chunk_end = min(cursor + step, end_dt)
            payload = self._get_json(
                f"/instruments/historical/{exchange}/{token}/{interval}",
                params={
                    "from": cursor.strftime("%Y-%m-%d %H:%M:%S"),
                    "to": chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            candles = ((payload.get("data") or {}).get("candles")) or []
            for candle in candles:
                if len(candle) < 5:
                    continue
                stamp = _parse_timestamp(str(candle[0]))
                key = stamp.isoformat()
                rows[key] = {
                    "date": key,
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": int(float(candle[5])) if len(candle) > 5 and candle[5] else 0,
                }
            cursor = chunk_end
        return [rows[key] for key in sorted(rows)]

    def profile(self) -> dict:
        payload = self._get_json("/user/fundsummary")
        data = payload.get("data") or []
        first = data[0] if isinstance(data, list) and data else {}
        return {
            "broker": self.name,
            "user_id": first.get("SEG") if isinstance(first, dict) else None,
        }
