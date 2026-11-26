#!/usr/bin/env python3
"""Create the dedicated SMA9 HIGH database (clean bootstrap).

The live scanner also creates its tables at startup, so this script is only
needed for a manual/offline bootstrap. It never touches any other database.
"""
import os
import sys

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from app.live_sma9_high_scanner import DB_PATH, init_db  # noqa: E402

if __name__ == "__main__":
    init_db()
    print(f"SMA9 HIGH database ready: {DB_PATH}")
