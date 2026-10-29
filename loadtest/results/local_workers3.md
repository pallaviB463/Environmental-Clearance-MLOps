# Load test: local_workers3 (cache off)

SLO: p95 of a complete run <= 60 s

| users | runs/s | p50 (s) | p95 (s) | failed | SLO |
|---|---|---|---|---|---|
| 1 | 0.09 | 8.1 | 10.0 | 0 | met |
| 5 | 0.368 | 10.0 | 14.0 | 0 | met |
| 10 | 0.357 | 24.0 | 27.0 | 0 | met |
| 20 | 0.357 | 47.0 | 54.0 | 0 | met |
| 30 | 0.358 | 49.0 | 78.0 | 0 | MISSED |

First concurrency that misses the SLO: 30
