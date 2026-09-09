from __future__ import annotations

import json
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from fetch_market import MarketFetcher
from indicators import calculate_all_indicators, calculate_pivot, calculate_cpr
from options import OptionsEngine
from regime import RegimeEngine
from scenarios import ScenarioEngine
from strategies import StrategyEngine
from ai_outlook import AIOutlookEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tradingai")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "instruments.json")

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)

def generate_data() -> None:
    config = load_config()
    db = Database(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", config["database"]))
    fetcher = MarketFetcher()
    options_engine = OptionsEngine()
    regime_engine = RegimeEngine()
    scenario_engine = ScenarioEngine()
    strategy_engine = StrategyEngine()
    ai_engine = AIOutlookEngine()

    all_instruments = config["indices"] + config["stocks"]
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"), exist_ok=True)

    market_data = {"source": "Yahoo Finance", "last_updated": datetime.now(timezone.utc).isoformat(), "instruments": {}}

    for inst in all_instruments:
        symbol = inst["symbol"]
        yf_symbol = inst["yfinance_symbol"]
        logger.info(f"Processing {symbol} ({yf_symbol})")

        quote = fetcher.fetch_quote(symbol, yf_symbol)
        if not quote:
            logger.warning(f"No quote for {symbol}")
            continue

        ohlcv = fetcher.fetch_ohlcv(symbol, yf_symbol, period="60d", interval="1d", limit=20)
        vix = fetcher.fetch_vix()
        options = fetcher.fetch_option_chain(symbol, yf_symbol) if symbol in ["NIFTY", "BANKNIFTY"] else None

        indicators = calculate_all_indicators(ohlcv, quote) if ohlcv else {}
        pivot_data = calculate_pivot(quote)
        cpr_data = calculate_cpr(pivot_data)
        options_analysis = options_engine.analyze_options(options, quote["price"]) if options else {"data_unavailable": True, "message": "Options data unavailable"}

        regime = regime_engine.evaluate(
            price=quote["price"], vwap=indicators.get("vwap", 0), prev_close=quote["previous_close"],
            rsi=indicators.get("rsi"), macd=indicators.get("macd"), adx=indicators.get("adx"),
            vix_price=vix["price"] if vix else 0, bollinger=indicators.get("bollinger_bands"),
            pivot=pivot_data, support_resistance=indicators.get("support_resistance"),
            pcr=options_analysis.get("pcr"),
        )

        scenarios = scenario_engine.generate(regime["regime"], indicators.get("support_resistance", {}).get("support", []), indicators.get("support_resistance", {}).get("resistance", []), quote["price"])
        strategy = strategy_engine.select(regime["regime"], regime["confidence"], "GOOD" if ohlcv else "PARTIAL")
        ai_outlook = ai_engine.generate(symbol, {**quote, **indicators, "vix": vix["price"] if vix else 0, "regime": regime["regime"], "options_unavailable": options_analysis.get("data_unavailable", False), "support_levels": indicators.get("support_resistance", {}).get("support", []), "resistance_levels": indicators.get("support_resistance", {}).get("resistance", [])})

        instrument_data = {
            "quote": quote,
            "indicators": indicators,
            "pivot": pivot_data,
            "cpr": cpr_data,
            "options": options_analysis,
            "regime": regime,
            "scenarios": scenarios,
            "strategy": strategy,
            "ai_outlook": ai_outlook,
            "data_quality": "GOOD" if ohlcv else "PARTIAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        market_data["instruments"][symbol] = instrument_data

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", f"{symbol.lower()}.json"), "w") as f:
            json.dump(instrument_data, f, indent=2, default=str)

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market.json"), "w") as f:
        json.dump(market_data, f, indent=2, default=str)

    logger.info(f"Generated data for {len(market_data['instruments'])} instruments")

if __name__ == "__main__":
    generate_data()