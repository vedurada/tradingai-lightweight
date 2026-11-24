"""mStock Type A adapter, translated to the Kite read-only surface."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import io
import json
import os
import pathlib
import re
import threading
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
TRANSIENT_HTTP = {429, 500, 502, 503, 504}
TRANSIENT_TEXT = ("try again", "something went wrong", "too many requests", "rate limit")
MAX_ATTEMPTS = 3
# Type A order vocabulary (official docs: /docs/v1/typeA/Orders/).
ORDER_VARIETIES = frozenset({"reg", "amo"})
ORDER_EXCHANGES = frozenset({"NSE", "BSE", "NFO", "BFO"})
ORDER_SIDES = frozenset({"BUY", "SELL"})
ORDER_TYPES = frozenset({"LIMIT", "MARKET", "SL", "SL-M"})
ORDER_PRODUCTS = frozenset({"CNC", "NRML", "MIS", "MTF"})
ORDER_VALIDITY = frozenset({"DAY", "IOC"})
INDEX_QUOTE_KEYS = {256265: "NSE:NIFTY 50", 26000: "NSE:NIFTY 50"}
INDEX_HISTORY_TOKENS = {26000: "NSE"}
# mStock publishes Data APIs at 1 request/second.  Historical candles are Data
# APIs, so throttle them at the adapter boundary and give every scanner the same
# cache key for a given 5-minute bar.  The short TTL still lets a forming bar
# appear without a long stale window.
DATA_API_MIN_INTERVAL = float(os.environ.get("MSTOCK_DATA_API_MIN_INTERVAL", "1.05"))
HISTORY_CACHE_TTL = float(os.environ.get("MSTOCK_HISTORY_CACHE_TTL", "20"))
HISTORY_CACHE_MAX = 16
_DATA_API_LOCK = threading.Lock()
_DATA_API_LAST = 0.0


def _pace_data_api() -> None:
    """Keep mStock Data API calls within its published 1 request/second."""
    global _DATA_API_LAST
    with _DATA_API_LOCK:
        now = time.monotonic()
        delay = DATA_API_MIN_INTERVAL - (now - _DATA_API_LAST)
        if delay > 0:
            time.sleep(delay)
        _DATA_API_LAST = time.monotonic()


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


def _history_cache_key(token: int, interval: str, signature, start_dt, end_dt):
    """One cache entry per token per 5-minute bar, not per call timestamp."""
    bar_end = end_dt.astimezone(IST).replace(
        minute=(end_dt.minute // 5) * 5, second=0, microsecond=0)
    return (
        token, interval, signature,
        start_dt.replace(microsecond=0).isoformat(), bar_end.isoformat(),
    )


class MStockAdapter(BrokerAdapter):
    name = "mstock"

    def __init__(self) -> None:
        self._secret_path = pathlib.Path(
            os.environ.get("MSTOCK_SECRET_FILE", DEFAULT_SECRET)
        )
        self._secret_lock = threading.Lock()
        self._secret_stamp: tuple[int, int] | None = None
        self._apply_secret(required=True, stamp=self._secret_signature())
        self.cache_dir = pathlib.Path(os.environ.get("BROKER_GATEWAY_CACHE_DIR", DEFAULT_CACHE))
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        # Keep only the raw CSV text, not 94k materialised dicts. All maps are
        # built by streaming that text once, under a single re-entrant lock, so
        # concurrent scanners cannot each build a private full-size copy.
        self._master_text_cache: str | None = None
        self._master_lock = threading.RLock()
        self._token_exchange: dict[int, str] | None = None
        self._quote_keys: dict[int, str] | None = None
        self._history_cache: collections.OrderedDict = collections.OrderedDict()
        self._history_lock = threading.Lock()

    # -- credentials -----------------------------------------------------
    def _secret_signature(self) -> tuple[int, int] | None:
        try:
            stat = self._secret_path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _apply_secret(self, required: bool = False, stamp=None) -> bool:
        cfg = _load_secret()
        api_key = cfg.get("MSTOCK_API_KEY", "")
        access_token = cfg.get("MSTOCK_ACCESS_TOKEN", "")
        if not api_key or not access_token:
            if required:
                raise RuntimeError("mStock API key/access token is missing; run mstock_session.py")
            return False
        self.api_key = api_key
        self.access_token = access_token
        # Stamp with the signature observed BEFORE the read. Stamping after the
        # read (TOCTOU) could pair old credentials with a newer file signature,
        # causing the next check to skip adopting the newly written token.
        self._secret_stamp = stamp if stamp is not None else self._secret_signature()
        return True

    def _refresh_secret_if_changed(self) -> None:
        # mStock tokens are daily. mstock_session.py rewrites the secret file
        # atomically; a long-running daemon must adopt the new token without a
        # restart, otherwise a pre-market refresh would not reach live trading.
        stamp = self._secret_signature()
        if stamp is None or stamp == self._secret_stamp:
            return
        with self._secret_lock:
            stamp = self._secret_signature()
            if stamp is None or stamp == self._secret_stamp:
                return
            self._apply_secret(stamp=stamp)

    # -- gateway freshness contract --------------------------------------
    def credential_signature(self):
        return self._secret_signature()

    def refresh_credentials_if_changed(self) -> None:
        self._refresh_secret_if_changed()

    def validate_credentials(self) -> None:
        self.profile()

    # -- transport -------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        self._refresh_secret_if_changed()
        return {
            "X-Mirae-Version": "1",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        }

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(0.6 * (2 ** attempt))

    def _http_get(self, path: str, params: dict | None = None, timeout: int = 60) -> bytes:
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        is_data_api = path.startswith(("/instruments/historical", "/instruments/scriptmaster"))
        for attempt in range(MAX_ATTEMPTS):
            if is_data_api:
                _pace_data_api()
            req = urllib.request.Request(url, headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                try:
                    body = json.loads(exc.read().decode("utf-8", "replace"))
                    message = body.get("message") or body.get("error_type")
                except Exception:
                    message = f"HTTP {exc.code}"
                if exc.code in TRANSIENT_HTTP and attempt + 1 < MAX_ATTEMPTS:
                    self._backoff(attempt)
                    continue
                raise BrokerCallFailed(f"mStock {path}: {message}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < MAX_ATTEMPTS:
                    self._backoff(attempt)
                    continue
                raise BrokerCallFailed(f"mStock {path}: {type(exc).__name__}") from exc
        raise BrokerCallFailed(f"mStock {path}: retry exhausted")

    @staticmethod
    def _is_transient_message(message) -> bool:
        text = str(message or "").lower()
        return any(term in text for term in TRANSIENT_TEXT)

    def _get_json(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(MAX_ATTEMPTS):
            raw = self._http_get(path, params=params)
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except ValueError as exc:
                if attempt + 1 < MAX_ATTEMPTS:
                    self._backoff(attempt)
                    continue
                raise BrokerCallFailed(f"mStock {path}: invalid JSON") from exc
            if isinstance(payload, dict) and payload.get("status") == "success":
                return payload
            message = payload.get("message") if isinstance(payload, dict) else payload
            if attempt + 1 < MAX_ATTEMPTS and self._is_transient_message(message):
                self._backoff(attempt)
                continue
            raise BrokerCallFailed(f"mStock {path}: {message}")
        raise BrokerCallFailed(f"mStock {path}: retry exhausted")

    # -- master ----------------------------------------------------------
    def _master_text(self) -> str:
        if self._master_text_cache is not None:
            return self._master_text_cache
        with self._master_lock:
            if self._master_text_cache is not None:
                return self._master_text_cache
            cache = self.cache_dir / "mstock_scriptmaster.csv"
            ttl = int(os.environ.get("BROKER_GATEWAY_MASTER_TTL", "86400"))
            text = None
            if cache.exists() and (time.time() - cache.stat().st_mtime) < ttl:
                text = cache.read_text(encoding="utf-8", errors="replace")
            if text is None:
                raw = self._http_get("/instruments/scriptmaster", timeout=120)
                text = raw.decode("utf-8", "replace")
                tmp = cache.with_name(cache.name + ".tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.chmod(0o644)
                os.replace(str(tmp), str(cache))
            self._master_text_cache = text
            return text

    def _iter_master_rows(self):
        """Stream master rows one at a time; never retain all 94k as dicts."""
        return csv.DictReader(io.StringIO(self._master_text()))

    def _refresh_master(self) -> None:
        """Drop every derived index together so they cannot be mixed."""
        with self._master_lock:
            self._master_text_cache = None
            self._token_exchange = None
            self._quote_keys = None

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
            with self._master_lock:
                if self._token_exchange is None:
                    mapping: dict[int, str] = dict(INDEX_HISTORY_TOKENS)
                    for row in self._iter_master_rows():
                        try:
                            token = int(row["instrument_token"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        mapping[token] = (row.get("exchange") or "").upper()
                    self._token_exchange = mapping
        return self._token_exchange

    def _quote_key_map(self) -> dict[int, str]:
        if self._quote_keys is None:
            with self._master_lock:
                if self._quote_keys is None:
                    mapping: dict[int, str] = dict(INDEX_QUOTE_KEYS)
                    for row in self._iter_master_rows():
                        try:
                            token = int(row["instrument_token"])
                        except (KeyError, TypeError, ValueError):
                            continue
                        exchange = (row.get("exchange") or "").upper()
                        symbol = row.get("tradingsymbol") or ""
                        if exchange and symbol:
                            mapping[token] = f"{exchange}:{symbol}"
                    self._quote_keys = mapping
        return self._quote_keys

    # -- Kite-shaped methods --------------------------------------------
    def instruments(self, exchange: str) -> list[dict]:
        # Serialise the build so concurrent scanners cannot each materialise a
        # full exchange list. The result is not retained by the adapter.
        with self._master_lock:
            out: list[dict] = []
            for row in self._iter_master_rows():
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
        key_map = self._quote_key_map()
        translated: list[tuple[str, str]] = []
        for symbol in symbols:
            original = str(symbol)
            if original.isdigit():
                token = int(original)
                mapped = key_map.get(token)
                if not mapped:
                    raise BrokerCallFailed(f"mStock quote: unknown token {original}")
                translated.append((original, mapped))
            else:
                translated.append((original, original))

        result: dict[str, dict] = {}
        for start in range(0, len(translated), 50):
            batch = translated[start : start + 50]
            payload = self._get_json(
                "/instruments/quote/ohlc", params=[("i", key) for _, key in batch]
            )
            data = payload.get("data") or {}
            for original, key in batch:
                item = data.get(key)
                if not item:
                    raise BrokerCallFailed(f"mStock quote: missing symbol {key}")
                result[original] = {
                    "instrument_token": int(item.get("instrument_token", 0) or 0),
                    "last_price": float(item.get("last_price", 0) or 0),
                    "ohlc": {
                        field: float(value)
                        for field, value in (item.get("ohlc") or {}).items()
                        if value is not None
                    },
                }
        return result

    def historical_data(self, token: int, start, end, interval: str) -> list[dict]:
        token = int(token)
        start_dt = _as_datetime(start)
        end_dt = _as_datetime(end)
        interval = str(interval)

        cache_key = _history_cache_key(
            token, interval, self._secret_signature(), start_dt, end_dt)
        with self._history_lock:
            cached = self._history_cache.get(cache_key)
            if cached and (time.time() - cached[0]) < HISTORY_CACHE_TTL:
                self._history_cache.move_to_end(cache_key)
                return list(cached[1])

            exchange = self._token_map().get(token)
            if not exchange:
                raise BrokerCallFailed(f"mStock historical: unknown instrument token {token}")
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
            result = [rows[key] for key in sorted(rows)]
            self._history_cache[cache_key] = (time.time(), result)
            while len(self._history_cache) > HISTORY_CACHE_MAX:
                self._history_cache.popitem(last=False)
            return list(result)

    def profile(self) -> dict:
        payload = self._get_json("/user/fundsummary")
        data = payload.get("data") or []
        first = data[0] if isinstance(data, list) and data else {}
        return {
            "broker": self.name,
            "user_id": first.get("SEG") if isinstance(first, dict) else None,
        }

    # -- live orders (opt-in, Type A only) --------------------------------
    def _http_post_form(self, path: str, fields: dict) -> dict:
        """POST form-encoded order data exactly once.

        Order placement is never retried here: a timeout may still have reached
        the exchange, and retrying could duplicate a real order. Idempotency is
        owned by the live service's deterministic client_order_id ledger.
        """
        url = BASE + path
        headers = self._headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(fields).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8", "replace"))
                message = (
                    payload.get("message") or payload.get("error_type")
                    or f"HTTP {exc.code}"
                )
            except Exception:
                message = f"HTTP {exc.code}"
            raise BrokerCallFailed(f"mStock {path}: {message}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Fail closed; the caller's ledger decides whether a retry is safe.
            raise BrokerCallFailed(
                f"mStock {path}: {type(exc).__name__} (order may be pending)"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise BrokerCallFailed(f"mStock {path}: invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            message = payload.get("message") if isinstance(payload, dict) else payload
            raise BrokerCallFailed(f"mStock {path}: {message}")
        return payload

    @staticmethod
    def _validate_order_fields(fields: dict) -> None:
        checks = (
            ("variety", ORDER_VARIETIES),
            ("exchange", ORDER_EXCHANGES),
            ("transaction_type", ORDER_SIDES),
            ("order_type", ORDER_TYPES),
            ("product", ORDER_PRODUCTS),
            ("validity", ORDER_VALIDITY),
        )
        for key, allowed in checks:
            value = str(fields.get(key, ""))
            if value not in allowed:
                raise BrokerCallFailed(
                    f"mStock order: invalid {key} {value!r}; allowed: "
                    + ", ".join(sorted(allowed))
                )
        symbol = str(fields.get("tradingsymbol", "")).strip()
        if not symbol or any(ch in symbol for ch in ("&", "=", "\n", "\r")):
            raise BrokerCallFailed("mStock order: invalid tradingsymbol")
        try:
            quantity = int(fields["quantity"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerCallFailed("mStock order: invalid quantity") from exc
        if quantity < 1:
            raise BrokerCallFailed("mStock order: quantity must be >= 1")
        try:
            price = float(fields.get("price", 0))
        except (TypeError, ValueError) as exc:
            raise BrokerCallFailed("mStock order: invalid price") from exc
        if fields["order_type"] == "LIMIT" and price <= 0:
            raise BrokerCallFailed("mStock order: LIMIT price must be positive")
        fields["quantity"] = str(quantity)
        fields["price"] = str(round(price, 2))

    def place_order(
        self, *, variety: str, exchange: str, tradingsymbol: str,
        transaction_type: str, order_type: str, quantity: int,
        product: str, validity: str, price: float, tag: str,
    ) -> dict:
        """Place one Type A regular order. No implicit retry, no secrets returned."""
        fields = {
            "variety": str(variety),
            "exchange": str(exchange),
            "tradingsymbol": str(tradingsymbol),
            "transaction_type": str(transaction_type),
            "order_type": str(order_type),
            "quantity": quantity,
            "product": str(product),
            "validity": str(validity),
            "price": price,
        }
        clean_tag = str(tag or "").strip()
        if clean_tag:
            if any(ch in clean_tag for ch in ("&", "=", "\n", "\r")):
                raise BrokerCallFailed("mStock order: invalid tag")
            fields["tag"] = clean_tag
        self._validate_order_fields(fields)
        payload = self._http_post_form(f"/orders/{fields['variety']}", fields)
        data = payload.get("data") or {}
        order_id = str((data.get("order_id") if isinstance(data, dict) else None) or "")
        if not order_id:
            raise BrokerCallFailed("mStock order: success response without order_id")
        return {"order_id": order_id, "status": "ACCEPTED"}

    @staticmethod
    def _map_order_status(row: dict) -> str:
        raw = str(row.get("status") or "").strip().lower()
        if raw in {"rejected", "reject"}:
            return "REJECTED"
        if raw in {"cancelled", "canceled"}:
            return "CANCELLED"
        if raw in {"complete", "filled", "executed"}:
            return "FILLED"
        try:
            filled = float(row.get("filled_quantity") or 0)
            total = float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            filled, total = 0.0, 0.0
        if total > 0 and filled >= total:
            return "FILLED"
        if raw in {"open", "pending", "triggered", "partial", "amended"}:
            return "ACCEPTED"
        return "UNKNOWN"

    _FILL_PRICE_KEYS = (
        "average_price", "avg_price", "average_traded_price",
        "avg_traded_price", "fill_price", "filled_price", "trade_price",
    )

    @classmethod
    def _fill_price(cls, row: dict) -> float | None:
        """Best-effort fill price; mStock field names vary by API version."""
        for key in cls._FILL_PRICE_KEYS:
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                return round(price, 4)
        return None

    def order_status(self, *, broker_order_id: str) -> dict:
        """Resolve one broker order from the Type A order book."""
        order_id = str(broker_order_id or "").strip()
        if not order_id:
            raise BrokerCallFailed("mStock order status: order id is required")
        payload = self._get_json("/orders")
        rows = payload.get("data") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            if str(row.get("order_id") or "") == order_id:
                return {
                    "order_id": order_id,
                    "status": self._map_order_status(row),
                    "raw_status": row.get("status"),
                    "status_message": row.get("status_message"),
                    "fill_price": self._fill_price(row),
                    "filled_quantity": self._numeric(row, "filled_quantity"),
                }
        return {"order_id": order_id, "status": "UNKNOWN", "fill_price": None,
                "filled_quantity": None}

    _TAG_KEYS = ("tag", "order_tag", "remarks", "client_order_id")

    @staticmethod
    def _numeric(row: dict, key: str) -> float | None:
        value = row.get(key)
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 else None

    def order_by_tag(self, *, tag: str) -> dict:
        """Read-only order-book lookup using the client tag we submit.

        mStock does not document ``tag`` as an idempotency key, so a missing row
        is not proof that an order was never accepted. The live service treats
        this as Stage 1 resolution only: it can adopt a broker order id, but an
        ambiguous miss never triggers an automatic re-placement unless a
        separate, explicit opt-in is enabled.
        """
        clean_tag = str(tag or "").strip()
        if not clean_tag:
            raise BrokerCallFailed("mStock order lookup: tag is required")
        if any(ch in clean_tag for ch in ("&", "=", "\n", "\r")):
            raise BrokerCallFailed("mStock order lookup: invalid tag")
        payload = self._get_json("/orders")
        rows = payload.get("data") or []
        matches = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            row_tag = ""
            for key in self._TAG_KEYS:
                row_tag = str(row.get(key) or "").strip()
                if row_tag:
                    break
            if row_tag != clean_tag:
                continue
            matches.append({
                "order_id": str(row.get("order_id") or "").strip() or None,
                "status": self._map_order_status(row),
                "raw_status": row.get("status"),
                "status_message": row.get("status_message"),
                "fill_price": self._fill_price(row),
                "quantity": self._numeric(row, "quantity"),
                "filled_quantity": self._numeric(row, "filled_quantity"),
            })
        return {"tag": clean_tag, "orders": matches}
