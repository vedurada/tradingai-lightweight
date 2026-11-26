# SMA9 HIGH Scanner - Locked, Independent Source

BUY-ONLY ATM NIFTY CE/PE paper scanner. Entry rule:

1. previous completed 5-minute candle **CLOSE > SMA9 HIGH** (computed from
   the 9 completed candles ending at that candle), and
2. live option **LTP > previous completed candle HIGH**.

The entry may fire at any 5-second poll while both conditions hold. Exit is
unchanged: at the close of the entry candle (same-candle exit, no carry
forward). No broker order is ever placed.

- Strategy id: `sma9_high`
- Dashboard: `https://tradingai.in/live/sma9-high/`
- Database: `/opt/tradingai/database/sma9_high.db`
- Service: `tradingai-sma9-high-scanner.service` (user `sma9high`)
- Code lock: `sudo ops/verify_integrity.sh`
