from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from fetch_market import MarketFetcher
from indicators import calculate_all_indicators, calculate_pivot, calculate_cpr
from options import OptionsEngine
from regime import RegimeEngine
from scenarios import ScenarioEngine
from strategies import StrategyEngine
from ai_outlook import AIOutlookEngine

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "instruments.json")

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)

def generate_json() -> None:
    config = load_config()
    db = Database(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", config["database"]))
    fetcher = MarketFetcher()
    options_engine = OptionsEngine()
    regime_engine = RegimeEngine()
    scenario_engine = ScenarioEngine()
    strategy_engine = StrategyEngine()
    ai_engine = AIOutlookEngine()

    all_instruments = config["indices"] + config["stocks"]
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    for inst in all_instruments:
        symbol = inst["symbol"]
        yf_symbol = inst["yfinance_symbol"]
        print(f"Generating JSON for {symbol}")

        quote = fetcher.fetch_quote(symbol, yf_symbol)
        if not quote:
            print(f"  No quote for {symbol}")
            continue

        ohlcv = fetcher.fetch_ohlcv(symbol, yf_symbol, period="60d", interval="1d", limit=20)
        vix = fetcher.fetch_vix()
        options = fetcher.fetch_option_chain(symbol, yf_symbol) if symbol in ["NIFTY", "BANKNIFTY"] else None

        indicators = calculate_all_indicators(ohlcv, quote) if ohlcv else {}
        pivot_data = calculate_pivot(quote)
        cpr_data = calculate_cpr(pivot_data)
        options_analysis = options_engine.analyze_options(options, quote["price"]) if options else {"data_unavailable": True, "message": "Options data unavailable"}
        regime = regime_engine.evaluate(price=quote["price"], vwap=indicators.get("vwap", 0), prev_close=quote["previous_close"], rsi=indicators.get("rsi"), macd=indicators.get("macd"), adx=indicators.get("adx"), vix_price=vix["price"] if vix else 0, bollinger=indicators.get("bollinger_bands"), pivot=pivot_data, support_resistance=indicators.get("support_resistance"), pcr=options_analysis.get("pcr"))
        scenarios = scenario_engine.generate(regime["regime"], indicators.get("support_resistance", {}).get("support", []), indicators.get("support_resistance", {}).get("resistance", []), quote["price"])
        strategy = strategy_engine.select(regime["regime"], regime["confidence"], "GOOD" if ohlcv else "PARTIAL")
        ai_outlook = ai_engine.generate(symbol, {**quote, **indicators, "vix": vix["price"] if vix else 0, "regime": regime["regime"], "options_unavailable": options_analysis.get("data_unavailable", False), "support_levels": indicators.get("support_resistance", {}).get("support", []), "resistance_levels": indicators.get("support_resistance", {}).get("resistance", [])})

        output = {
            "source": "Yahoo Finance",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "data_timestamp": datetime.now(timezone.utc).isoformat(),
            "data_quality": "GOOD" if ohlcv else "PARTIAL",
            "quote": quote,
            "indicators": {k: v for k, v in indicators.items() if k != "timestamp"},
            "pivot": pivot_data,
            "cpr": cpr_data,
            "options": options_analysis,
            "regime": regime,
            "scenarios": scenarios,
            "strategy": strategy,
            "ai_outlook": ai_outlook,
        }

        with open(os.path.join(data_dir, f"{symbol.lower()}.json"), "w") as f:
            json.dump(output, f, indent=2, default=str)

    print(f"Generated JSON for {len(all_instruments)} instruments")

if __name__ == "__main__":
    generate_json()