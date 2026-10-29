# Service level objective (Requirement D6)

**Declared before any load test was run.** Commit this file before the first measurement so
the repository history shows the target was not chosen after seeing results.

## The objective

> **p95 latency of a complete screening run ≤ 60 seconds**, measured from submission
> (`POST /v1/screenings`) to the final result being available (`GET /v1/screenings/{id}`
> returns `answered` or `escalated`), at **10 concurrent users**, with the LLM replaced by
> the stub service at 1.5 s per call.

Secondary targets:
- Submission call (`POST`, returns 202): p95 ≤ 300 ms. A rejected (422) submission: p95 ≤ 300 ms.
- Failed runs (`status = failed`, or not finished within 3× the SLO): 0 % at the target load.

## Why these numbers (against section 1 of the problem statement)

1. **What a slow answer costs is small next to what a wrong one costs.** Section 1: the
   category decides months of timeline, and a clearance granted at the wrong level can be set
   aside after work has begun. So the design spends latency on correctness: a second retrieval
   for modifying provisions, an independent Verifier, and a retry when verification fails. The
   SLO is set to leave room for that, not to minimise latency.
2. **The user waits for it.** The caller is a consultant or project proponent at a web form,
   before an application is filed. Beyond about a minute, people abandon or resubmit, and a
   resubmitted agent run doubles the cost. 60 s keeps it within one interactive wait.
3. **It fits the agent's own budget.** A normal run makes 4-6 model calls. With a real model
   at 3-8 s per call that is 20-50 s, so 60 s at p95 is achievable in production as well as in
   the stub test. The hard per-run deadline (`RUN_DEADLINE_SECONDS=90`) sits above the SLO, so
   the deadline only cuts off runs that have already missed it.
4. **10 concurrent users** is a deliberately generous peak for a pre-screening tool used by
   consultants in one region; the sweep goes beyond it to find where the target fails.

## How it is measured

- `loadtest/locustfile.py` reports each complete run as the custom request `full_run`; the
  `POST` and polling calls are reported separately and are not the SLO metric.
- `python -m loadtest.run_sweep` steps through 1, 2, 5, 10, 20, 40 users and records RPS, p50,
  p95 and failures at each level, stopping at the first level that misses the SLO.
- The same run latency is exported live as `eia_run_e2e_seconds` and charted on the Grafana
  dashboard with the 60 s line.
