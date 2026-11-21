"""Gateway freshness cache must fail closed without hammering the broker."""
from __future__ import annotations

import pytest

from broker_gateway import daemon
from broker_gateway.errors import BrokerCallFailed


class _Adapter:
    def __init__(self, signature=("sig", 1), valid=True):
        self.signature = signature
        self.valid = valid
        self.validate_calls = 0

    def credential_signature(self):
        return self.signature

    def validate_credentials(self):
        self.validate_calls += 1
        if not self.valid:
            raise RuntimeError("token rejected")


@pytest.fixture(autouse=True)
def _reset_cache():
    daemon._FRESH_CACHE.clear()
    daemon._FRESH_ERROR.clear()
    yield
    daemon._FRESH_CACHE.clear()
    daemon._FRESH_ERROR.clear()


def test_positive_validation_is_cached():
    adapter = _Adapter()
    daemon._require_fresh("mstock", adapter)
    daemon._require_fresh("mstock", adapter)
    assert adapter.validate_calls == 1


def test_failed_validation_is_negative_cached_briefly():
    adapter = _Adapter(valid=False)
    with pytest.raises(BrokerCallFailed, match="token is stale or invalid"):
        daemon._require_fresh("mstock", adapter)
    with pytest.raises(BrokerCallFailed, match="token is stale or invalid"):
        daemon._require_fresh("mstock", adapter)
    # Negative cache prevents a second broker call within the short TTL.
    assert adapter.validate_calls == 1


def test_credential_change_bypasses_negative_cache():
    adapter = _Adapter(valid=False)
    with pytest.raises(BrokerCallFailed):
        daemon._require_fresh("mstock", adapter)
    adapter.signature = ("sig", 2)  # refreshed on disk
    adapter.valid = True
    daemon._require_fresh("mstock", adapter)
    assert adapter.validate_calls == 2


def test_negative_cache_expires(monkeypatch):
    adapter = _Adapter(valid=False)
    monkeypatch.setattr(daemon, "_FRESH_NEG_TTL", 0.0)
    with pytest.raises(BrokerCallFailed):
        daemon._require_fresh("mstock", adapter)
    with pytest.raises(BrokerCallFailed):
        daemon._require_fresh("mstock", adapter)
    assert adapter.validate_calls == 2


def test_error_message_is_reused_from_negative_cache():
    adapter = _Adapter(valid=False)
    with pytest.raises(BrokerCallFailed) as first:
        daemon._require_fresh("mstock", adapter)
    with pytest.raises(BrokerCallFailed) as second:
        daemon._require_fresh("mstock", adapter)
    assert str(first.value) == str(second.value)


def test_mstock_secret_stamp_is_captured_before_read(monkeypatch):
    """TOCTOU: a refreshed file must not be stamped with a pre-read signature."""
    from broker_gateway.adapters import mstock

    monkeypatch.setattr(
        mstock, "_load_secret",
        lambda: {"MSTOCK_API_KEY": "key", "MSTOCK_ACCESS_TOKEN": "token"},
    )
    adapter = mstock.MStockAdapter.__new__(mstock.MStockAdapter)
    adapter._secret_stamp = None
    captured_stamp = ("mtime-before-read", 123)
    adapter._apply_secret(stamp=captured_stamp)
    assert adapter._secret_stamp == captured_stamp
    assert adapter.api_key == "key"
    assert adapter.access_token == "token"
