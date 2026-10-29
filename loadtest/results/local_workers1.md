# Load test: local_workers1 (cache off)

SLO: p95 of a complete run <= 60 s

| users | runs/s | p50 (s) | p95 (s) | failed | SLO |
|---|---|---|---|---|---|
| 1 | 0.09 | 8.1 | 10.0 | 0 | met |
| 5 | 0.112 | 37.0 | 39.0 | 0 | met |
| 10 | 0.125 | 45.0 | 79.0 | 0 | MISSED |

First concurrency that misses the SLO: 10
