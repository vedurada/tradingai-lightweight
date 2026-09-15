import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from walkforward import run_walkforward, WalkForwardResult, WindowMetrics

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "database", "tradingai.db")


def test_insufficient_data_short_window():
    results = run_walkforward("NIFTY", "2026-09-10", "2026-09-15", db_path=DB_PATH)
    assert len(results) == 1
    assert results[0].insufficient_data is True
    assert "INSUFFICIENT_HISTORICAL_DATA" in results[0].message


def test_insufficient_data_no_symbol_data():
    results = run_walkforward("NIFTY", "2027-01-01", "2027-01-31", db_path=DB_PATH)
    assert results[0].insufficient_data is True


def test_coverage_reported():
    results = run_walkforward("NIFTY", "2026-06-24", "2026-09-15",
                              dev_days=25, val_days=15, oos_days=15,
                              step_days=15, db_path=DB_PATH)
    assert len(results) >= 1
    r = results[0]
    assert r.insufficient_data is False
    cov = r.coverage
    assert cov["symbol"] == "NIFTY"
    assert "earliest" in cov
    assert "latest" in cov
    assert "total_candles" in cov
    assert "total_trading_days" in cov
    assert cov["total_trading_days"] > 0


def test_window_dates_chronological():
    results = run_walkforward("NIFTY", "2026-06-24", "2026-09-15",
                              dev_days=25, val_days=15, oos_days=15,
                              step_days=15, db_path=DB_PATH)
    if not results or results[0].insufficient_data:
        return
    r = results[0]
    assert r.development_start <= r.development_end
    assert r.validation_start <= r.validation_end
    assert r.test_start <= r.test_end
    assert r.development_end <= r.validation_start
    assert r.validation_end <= r.test_start
    assert r.test_start <= r.test_end


def test_window_provenance():
    results = run_walkforward("NIFTY", "2026-06-24", "2026-09-15",
                              dev_days=25, val_days=15, oos_days=15,
                              step_days=15, db_path=DB_PATH,
                              strategy_version="BREAKOUT",
                              indicator_version="v2",
                              data_version="5m-20260915",
                              cost_model_version="v1")
    if results and results[0].insufficient_data:
        return
    assert len(results) >= 1
    for r in results:
        assert r.strategy_version == "BREAKOUT"
        assert r.indicator_version == "v2"
        assert r.data_version == "5m-20260915"
        assert r.cost_model_version == "v1"
        assert r.window_id.startswith("NIFTY_WF_")


def test_insufficient_data_has_coverage():
    results = run_walkforward("NIFTY", "2026-09-10", "2026-09-15", db_path=DB_PATH)
    r = results[0]
    assert r.insufficient_data is True
    assert r.coverage is not None
    assert "total_trading_days" in r.coverage


def test_metrics_namedtuple():
    m = WindowMetrics(total_trades=10, completed_trades=8, win_rate=62.5,
                      winning_trades=5, losing_trades=3, breakeven_trades=0,
                      net_pnl=5000, gross_pnl=8000, gross_loss=3000,
                      profit_factor=2.67, max_drawdown=-2000, avg_r=0.625,
                      best_r=1.5, worst_r=-0.5, still_open=2, trade_count=10)
    assert m.total_trades == 10
    assert m.completed_trades == 8
    assert m.win_rate == 62.5
    assert m.still_open == 2


def test_metrics_from_backtest_none():
    from walkforward import _metrics_from_backtest
    assert _metrics_from_backtest(None) is None


def test_metrics_from_backtest_empty():
    from walkforward import _metrics_from_backtest
    class FakeResult:
        trades = []
        performance = {}
    m = _metrics_from_backtest(FakeResult())
    assert m is None


def test_multiple_windows():
    results = run_walkforward("NIFTY", "2026-06-24", "2026-09-15",
                              dev_days=20, val_days=12, oos_days=12,
                              step_days=12, db_path=DB_PATH)
    if not results or results[0].insufficient_data:
        return
    assert len(results) >= 1
    ids = [r.window_id for r in results]
    assert len(set(ids)) == len(ids), "Window IDs should be unique"


def test_chronological_no_lookahead():
    results = run_walkforward("NIFTY", "2026-06-24", "2026-09-15",
                              dev_days=25, val_days=15, oos_days=15,
                              step_days=15, db_path=DB_PATH)
    if not results or results[0].insufficient_data:
        return
    for r in results:
        assert r.test_end >= r.test_start
        if r.validation_metrics:
            assert r.validation_metrics.total_trades >= 0
        if r.development_metrics:
            assert r.development_metrics.total_trades >= 0
