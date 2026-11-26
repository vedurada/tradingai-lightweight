#!/usr/bin/env python3
"""DEPRECATED legacy SMA9 historical scan runner.

This script used to regenerate the original 339 trades with the old
CE-bull / PE-bear (short) logic and an SMA9 that included the entry candle's
own close (look-ahead).  It must not be used any more: running it could
reintroduce invalid trades into the database.

Use these instead:
  * Live paper trading (5-second polling, BUY only):
        systemctl status tradingai-sma9-scanner.service
        python3 /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py
  * Corrected historical dataset + forensic audit:
        python3 /opt/tradingai/sma9_scanner/app/sma9_historical_audit.py

By default this shim performs no database writes and exits 0.  Pass
``--run-audit`` to delegate to the corrected audit generator.
"""

import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_SCRIPT = os.path.join(APP_DIR, "sma9_historical_audit.py")

MESSAGE = """\
SMA9 legacy runner is DEPRECATED and disabled.

Why:
  * It regenerated trades with the old CE-bull / PE-bear (short) logic.
  * Its SMA9 included the entry candle close, which is look-ahead.

Use instead:
  * live paper scanner : sma9_scanner/app/live_sma9_scanner.py
  * corrected history  : sma9_scanner/app/sma9_historical_audit.py

No database writes were performed.
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--run-audit" in argv:
        print("Delegating to corrected audit generator:", AUDIT_SCRIPT)
        return subprocess.call([sys.executable, AUDIT_SCRIPT])
    print(MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
