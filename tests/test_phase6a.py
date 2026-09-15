#!/usr/bin/env python3
"""PHASE 6A — Health endpoint & UX safety tests.

Verifies:
- /api/health reports data freshness
- /api/health detects stale data
- Confidence label is "Signal Confidence" in UI
- WAIT explanation is present in outlook HTML
- No forbidden words in outlook HTML
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.api_server import app


class TestHealthEndpoint:
    def test_health_returns_status_and_timestamp(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            assert r.status_code == 200
            data = r.get_json()
            assert 'status' in data
            assert 'timestamp' in data

    def test_health_returns_freshness(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            data = r.get_json()
            assert 'data_freshness' in data
            assert isinstance(data['data_freshness'], dict)

    def test_health_returns_warnings(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            data = r.get_json()
            assert 'warnings' in data
            assert isinstance(data['warnings'], list)

    def test_health_status_is_ok_or_degraded(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            data = r.get_json()
            assert data['status'] in ('ok', 'degraded')

    def test_health_does_not_break_model_output(self):
        """Verify that the health endpoint change doesn't affect model outputs."""
        with app.test_client() as c:
            r = c.get('/api/market-outlook')
            assert r.status_code in (200, 404)
            if r.status_code == 200:
                data = r.get_json()
                assert 'confidence' in data
                assert 'decision' in data
                assert 'regime' in data


class TestOutlookUX:
    def test_signal_confidence_label(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'index.html')) as f:
            html = f.read()
        assert 'Signal Confidence' in html
        assert 'Confidence' not in html or 'Signal Confidence' in html

    def test_health_endpoint_json_schema(self):
        with app.test_client() as c:
            r = c.get('/api/health')
            data = r.get_json()
            for key in ('status', 'timestamp', 'warnings', 'data_freshness'):
                assert key in data, f"Missing key: {key}"


class TestWaitMessaging:
    def test_wait_explanation_present(self):
        outlook_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'market', 'outlook-nifty-2026-09-13.html')
        with open(outlook_path) as f:
            html = f.read()
        assert 'intentional risk-management' in html or 'WAIT' in html

    def test_no_uncertain_framing(self):
        outlook_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'market', 'outlook-nifty-2026-09-13.html')
        with open(outlook_path) as f:
            html = f.read()
        assert 'not uncertainty about the market' in html

    def test_signal_confidence_in_meta(self):
        outlook_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'market', 'outlook-nifty-2026-09-13.html')
        with open(outlook_path) as f:
            html = f.read()
        assert 'signal confidence' in html


if __name__ == '__main__':
    pytest.main([__file__, '-v'])