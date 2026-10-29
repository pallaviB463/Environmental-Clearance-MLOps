# Load test: local_workers3_cache_off (cache off)

SLO: p95 of a complete run <= 60 s

| users | runs/s | p50 (s) | p95 (s) | failed | SLO |
|---|---|---|---|---|---|
| 10 | 0.368 | 22.0 | 27.0 | 0 | met |

First concurrency that misses the SLO: none in the tested range
