#!/usr/bin/env python3
"""B16 draft: lightweight capacity probe against a running API.

Does not stress-test production. Records latency samples for /healthz and /api/ready.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request


def timed_get(url: str, timeout: float) -> tuple[int | None, float, str]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(200).decode('utf-8', errors='replace')
            elapsed = (time.perf_counter() - started) * 1000
            return response.status, elapsed, body[:120]
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return exc.code, elapsed, str(exc)
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        return None, elapsed, str(exc)


def summarize(samples: list[float]) -> dict:
    if not samples:
        return {'count': 0}
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
    return {
        'count': len(ordered),
        'p50_ms': round(statistics.median(ordered), 2),
        'p95_ms': round(ordered[p95_index], 2),
        'max_ms': round(max(ordered), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--rounds', type=int, default=20)
    parser.add_argument('--timeout', type=float, default=5.0)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    targets = {
        'healthz': f'{base}/healthz',
        'ready': f'{base}/api/ready',
    }
    report = {'base_url': base, 'rounds': args.rounds, 'targets': {}, 'ok': True}
    for name, url in targets.items():
        latencies = []
        statuses = []
        for _ in range(max(1, args.rounds)):
            status, elapsed, _detail = timed_get(url, args.timeout)
            statuses.append(status)
            latencies.append(elapsed)
            if status != 200:
                report['ok'] = False
        report['targets'][name] = {
            'url': url,
            'status_counts': {
                str(key): statuses.count(key) for key in sorted(set(statuses), key=lambda item: (item is None, item))
            },
            'latency': summarize(latencies),
        }
    report['notes'] = (
        'Capacity drill is a smoke probe only. Queue depth, Worker concurrency and PDF conversion '
        'need separate load scenarios before claiming production capacity targets.'
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
