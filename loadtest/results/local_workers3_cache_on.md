# Load test: local_workers3_cache_on (cache on)

SLO: p95 of a complete run <= 60 s

| users | runs/s | p50 (s) | p95 (s) | failed | SLO |
|---|---|---|---|---|---|
| 10 | 2.618 | 0.01 | 9.1 | 0 | met |

First concurrency that misses the SLO: none in the tested range
