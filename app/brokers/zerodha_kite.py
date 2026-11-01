path = "/opt/tradingai/scripts/paper_scalp_live.py"
with open(path) as f:
    content = f.read()

old = '''                            entry_time_s = st.get("entry_time")
                            if entry_time_s is None:
                                # Entry candle not yet ingested; compute as
                                # signal_time + 5min so the entry window is
                                # 5 minutes after the entry candle, not 5
                                # minutes after the signal candle.
                                from datetime import datetime as _dt, timedelta as _td
                                signal_dt = _dt.fromisoformat(
                                    str(st.get("signal_time")).replace("Z", "+00:00")
                                )
                                entry_dt = signal_dt + _td(minutes=5)
                                entry_time_s = entry_dt.isoformat()'''

new = '''                        entry_time_s = st.get("entry_time")
                        if entry_time_s is None:
                            # Entry candle not yet ingested; skip and retry next poll.
                            # _live_signal will return entry_time = entry_candle.timestamp
                            # once the entry candle is ingested into market_candles_5m.
                            continue'''

count = content.count(old)
print(f"Found {count} occurrence(s)")
content = content.replace(old, new, 1)

with open(path, "w") as f:
    f.write(content)
print("Fix applied")
