"""Market data provider — Zerodha Kite Connect only.

yfinance has been removed entirely. All live/backtest/shadow market data now
comes from Zerodha. MarketDataProvider keeps the same interface
(get_quote / get_5m_candles) but delegates to ZerodhaDataProvider so every
consumer (LiveEngine, collector, paper_scalp_live, ...) automatically uses
Zerodha with no yfinance fallback.
"""

import logging
from app.market.zerodha_provider import ZerodhaDataProvider

log = logging.getLogger('tradingai.provider')


class MarketDataProvider:
    """Zerodha-backed market data provider (yfinance removed)."""

    def __init__(self, use_cache=True):
        self._zp = ZerodhaDataProvider(use_cache=use_cache)
        self.kc = self._zp.kc
        self.mode = self._zp.mode
        self.use_cache = self._zp.use_cache
        self.active_provider = 'zerodha'
        self._instrument_tokens = self._zp._instrument_tokens

    def get_quote(self, symbol, use_cache=None):
        return self._zp.get_quote(symbol, use_cache=use_cache)

    def get_5m_candles(self, symbol, periods=100, use_cache=None):
        return self._zp.get_5m_candles(symbol, periods=periods, use_cache=use_cache)
