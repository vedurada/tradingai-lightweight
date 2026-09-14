#!/usr/bin/env python3
"""B.4 Part I — Before/After Benchmark (portable version).

This script is designed to run at both 6596cc7 (before) and 801a5c1 (after).
It measures endpoint latency without depending on B.4-specific files.

Usage:
  python3 scripts/benchmark_portable.py --output <filename>
"""
import os
import sys
import json
import time
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Clear any cached app state
os.environ.pop("BACKTEST_BACKEND", None)

from backend.api_server import app

ENDPOINTS = [
    ("/api/price/NIFTY", 5),
    ("/api/price/BANKNIFTY", 5),
    ("/api/indicators/NIFTY", 5),
    ("/api/vix", 5),
    ("/api/market", 20),
    ("/api/symbols", 86400),
    ("/api/outlook/NIFTY", 3600),
    ("/api/strategies", 3600),
    ("/api/regimes", 3600),
    ("/api/options/NIFTY", 600),
    ("/api/pcr", 600),
    ("/api/maxpain", 600),
    ("/api/snapshot", 5),
    ("/api/breadth", 5),
    ("/api/data_status", 5),
]

RUNS = 10


def main():
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        output_file = sys.argv[idx + 1]

    results = {}

    with app.test_client() as c:
        # Warmup: 2 requests per endpoint (not counted)
        for path, _ in ENDPOINTS:
            try:
                c.get(path)
                c.get(path)
            except Exception:
                pass

        for path, ttl in ENDPOINTS:
            times = []
            for _ in range(RUNS):
                start = time.perf_counter()
                r = c.get(path)
                elapsed = (time.perf_counter() - start) * 1000
                times.append({
                    "status": r.status_code,
                    "latency_ms": round(elapsed, 3),
                })
            latencies = [t["latency_ms"] for t in times]
            results[path] = {
                "runs": RUNS,
                "min_ms": round(min(latencies), 3),
                "max_ms": round(max(latencies), 3),
                "median_ms": round(statistics.median(latencies), 3),
                "avg_ms": round(statistics.mean(latencies), 3),
                "p90_ms": round(sorted(latencies)[int(len(latencies) * 0.9)], 3),
                "all_runs": times,
                "cacheable": ttl > 0,
                "ttl": ttl,
            }

    # Summary
    commit = os.popen("git rev-parse --short HEAD 2>/dev/null").read().strip() or "unknown"
    print(f"Benchmark at: {commit}")
    print(f"Endpoints: {len(results)}, Runs per endpoint: {RUNS}")
    print()
    print(f"{'Endpoint':<35} {'Min':>8} {'Max':>8} {'Median':>8} {'P90':>8} {'Status'}")
    print("-" * 85)
    for path, data in results.items():
        status = "✓" if all(t["status"] == 200 for t in data["all_runs"]) else "⚠"
        print(f"{path:<35} {data['min_ms']:>7.2f}ms {data['max_ms']:>7.2f}ms {data['median_ms']:>7.2f}ms {data['p90_ms']:>7.2f}ms {status}")

    if output_file:
        with open(output_file, "w") as f:
            json.dump({
                "commit": commit,
                "runs": RUNS,
                "endpoints": results,
            }, f, indent=2)
        print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
