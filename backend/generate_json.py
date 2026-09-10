from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from fetch_market import MarketFetcher
from history_logger import save_outlook, get_all_history, archive_history
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
    settings = {}
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "settings.json")
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", settings.get("database", "database/tradingai.db"))
    db = Database(db_path)
    fetcher = MarketFetcher()
    options_engine = OptionsEngine()
    regime_engine = RegimeEngine()
    scenario_engine = ScenarioEngine()
    strategy_engine = StrategyEngine()
    ai_engine = AIOutlookEngine()

    all_instruments = config["indices"] + config["stocks"]
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    stale_instruments = []

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

        indicators = calculate_all_indicators(ohlcv, quote) if ohlcv else {}
        pivot_data = calculate_pivot(quote)
        cpr_data = calculate_cpr(pivot_data)
        options_analysis = {"data_unavailable": True, "message": "Options data unavailable"}
        regime = regime_engine.evaluate(price=quote["price"], vwap=indicators.get("vwap", 0), prev_close=quote["previous_close"], rsi=indicators.get("rsi"), macd=indicators.get("macd"), adx=indicators.get("adx"), vix_price=vix["price"] if vix else 0, bollinger=indicators.get("bollinger_bands"), pivot=pivot_data, support_resistance=indicators.get("support_resistance"), pcr=options_analysis.get("pcr"), volume=quote.get("volume"), avg_volume=indicators.get("avg_volume"))
        scenarios = scenario_engine.generate(regime["regime"], indicators.get("support_resistance", {}).get("support", []), indicators.get("support_resistance", {}).get("resistance", []), quote["price"])
        strategy = strategy_engine.select(regime["regime"], regime["confidence"], "GOOD" if ohlcv else "PARTIAL")
        ai_outlook = ai_engine.generate(symbol, {**quote, **indicators, "vix": vix["price"] if vix else 0, "regime": regime["regime"], "options_unavailable": options_analysis.get("data_unavailable", False), "support_levels": indicators.get("support_resistance", {}).get("support", []), "resistance_levels": indicators.get("support_resistance", {}).get("resistance", [])})

        strategy_name = strategy.get("strategies", [{}])[0].get("strategy", "") if strategy else ""
        save_outlook(symbol, ai_outlook, quote_price=quote.get("price", 0), strategy_name=strategy_name)

        data_quality = "STALE" if quote.get("stale") else ("GOOD" if ohlcv else "PARTIAL")
        if quote.get("stale"):
            stale_instruments.append(symbol)

        output = {
            "source": "Yahoo Finance",
            "last_updated": datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            "data_timestamp": datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            "data_quality": data_quality,
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

    all_history = get_all_history(days=90)
    with open(os.path.join(data_dir, "history.json"), "w") as f:
        json.dump(all_history, f, indent=2, default=str)

    now = datetime.now(timezone.utc)
    health = {
        "status": "degraded" if stale_instruments else "healthy",
        "stale_instruments": stale_instruments,
        "total_instruments": len(all_instruments),
        "last_updated": now.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    }
    with open(os.path.join(data_dir, "health.json"), "w") as f:
        json.dump(health, f, indent=2)

    archived = archive_history(weekly=True, monthly=False)
    if archived:
        print(f"Archived {archived} old history entries")

if __name__ == "__main__":
    generate_json()