#!/usr/bin/env python3
"""B.4 Part I — Before/After Benchmark.

Measures endpoint latency before and after B.4 optimization.
Run against B.3 baseline (6596cc7) and B.4 implementation (4cd896a).

Usage:
  # Measure current state (B.4):
  python3 scripts/benchmark_b4.py

  # Save results:
  python3 scripts/benchmark_b4.py --output benchmarks_b4.json
"""
import os
import sys
import json
import time
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.api_server import app

ENDPOINTS = [
    ("/api/price/NIFTY", 5),
    ("/api/price/BANKNIFTY", 5),
    ("/api/indicators/NIFTY", 5),
    ("/api/vix", 5),
    ("/api/market", 20),
    ("/api/symbols", 5),
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

RUNS = 5


def benchmark_endpoint(client, path, ttl):
    times = []
    for _ in range(RUNS):
        start = time.monotonic()
        r = client.get(path)
        elapsed = (time.monotonic() - start) * 1000
        times.append({
            "status": r.status_code,
            "latency_ms": round(elapsed, 2),
        })
    return times


def main():
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        output_file = sys.argv[idx + 1]

    results = {}

    with app.test_client() as c:
        # Warmup
        for path, _ in ENDPOINTS:
            try:
                c.get(path)
            except Exception:
                pass

        for path, ttl in ENDPOINTS:
            times = benchmark_endpoint(c, path, ttl)
            latencies = [t["latency_ms"] for t in times]
            results[path] = {
                "runs": RUNS,
                "min_ms": round(min(latencies), 2),
                "max_ms": round(max(latencies), 2),
                "median_ms": round(statistics.median(latencies), 2),
                "avg_ms": round(statistics.mean(latencies), 2),
                "all_runs": times,
                "cacheable": ttl > 0,
            }

    # Summary
    print("=" * 80)
    print("B.4 PART I — Before/After Benchmark")
    print("=" * 80)
    print(f"\n{'Endpoint':<40} {'Min (ms)':<12} {'Max (ms)':<12} {'Median (ms)':<14} {'Cache'}")
    print("-" * 90)
    for path, data in results.items():
        cacheable = "✓" if data["cacheable"] else "—"
        print(f"{path:<40} {data['min_ms']:<12} {data['max_ms']:<12} {data['median_ms']:<14} {cacheable}")

    # Cache effectiveness
    cache_hits = 0
    cache_total = 0
    for path, data in results.items():
        if data["cacheable"]:
            cache_total += 1
            # Check if 2nd run is faster (cache hit)
            if len(data["all_runs"]) >= 2:
                first = data["all_runs"][0]["latency_ms"]
                second = data["all_runs"][1]["latency_ms"]
                if second < first:
                    cache_hits += 1

    if cache_total > 0:
        print(f"\nCache effectiveness: {cache_hits}/{cache_total} endpoints showed improvement on 2nd run")

    print(f"\nTotal endpoints measured: {len(results)}")
    print(f"Benchmark runs per endpoint: {RUNS}")

    if output_file:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
