# Runbook and incident log (Requirement D8)

Service: EIA Clearance Pre-Screening. Commands assume the Docker Compose stack.

Where to look first:
- Grafana: http://localhost:3000 (dashboard "EIA Pre-Screening Service")
- Run trace by id: `curl -s localhost:8000/v1/screenings/<run_id>/trace | jq`
- Jaeger: http://localhost:16686 (service `agent-worker`, `api`, `verifier-agent`)
- Logs (JSON, one line per event, every line carries `correlation_id` and `run_id`):
  `docker compose logs -f agent-worker | grep <run_id>`

---

## Failure mode 1: the LLM provider is unavailable or rejecting calls

The most likely failure: free-tier rate limits (HTTP 429), provider outages (5xx), an expired
or revoked key (401/403), or slow responses hitting `LLM_TIMEOUT_SECONDS`.

### Symptom
- Runs finish `escalated` with reason `PROVIDER_UNAVAILABLE` and `mode: degraded`, carrying a
  rule-based `provisional_opinion`. No answers are released.
- Grafana: "Circuit breaker" panel at 2 (open); "Run mode" shows `degraded`; "LLM retry rate" rises.
- Worker logs: `circuit breaker for <model> -> OPEN`.

### Confirmation
```bash
curl -s localhost:8000/admin/breakers                    # breaker state per worker and model
curl -s localhost:8000/health | jq .llm_down_switch      # rule out the demo chaos switch
curl -s localhost:8000/v1/screenings/<run_id>/trace | jq '.events[] | select(.kind=="llm_call") | {model, outcome, error, retries}'
# Call the provider directly with the configured key (prints only the status line):
curl -s -o /dev/null -w "%{http_code}\n" "$LLM_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $LLM_API_KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"$LLM_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":3}"
```
- 401/403: key problem. 429: rate limit. 5xx or timeout: provider outage. 410: model retired.

### Recovery
1. If the chaos switch is on: `curl -X POST localhost:8000/admin/chaos -d '{"llm_down": false}' -H 'content-type: application/json'`.
2. Key problem: generate a new key, put it in `.env`, then `docker compose up -d agent-worker verifier-agent`
   (recreates the containers with the new environment).
3. Model retired or overloaded: change `LLM_MODEL` / `LLM_FALLBACK_MODEL` in `.env` and recreate as above.
4. Rate limited: lower `RATE_LIMIT_PER_MINUTE`, or scale workers down so fewer calls run at once.
5. The breaker half-opens after `CIRCUIT_BREAKER_RESET_TIMEOUT` seconds and closes on the next
   success; no restart is needed once the provider is back.
6. Escalated runs are not cached, so callers can simply resubmit.

---

## Failure mode 2: runs pile up in the queue (backlog or dead workers)

### Symptom
- `GET /v1/screenings/<id>` stays `queued` for longer than usual.
- Grafana: "Queue depth (pending)" rising; "Run latency p95" approaching the 60 s SLO line.

### Confirmation
```bash
docker compose ps agent-worker                            # how many workers, are they healthy
docker compose exec redis redis-cli LLEN eia:queue          # waiting
docker compose exec redis redis-cli LLEN eia:queue:processing   # being worked on
docker compose logs --tail 50 agent-worker                # crash loop? index missing? redis errors?
```
- Pending grows while processing equals the number of workers: not enough workers for the load.
- Processing non-zero but workers are down or restarting: workers died mid-run.

### Recovery
1. Not enough capacity: `docker compose up -d --scale agent-worker=3` (Prometheus discovers new
   replicas automatically through DNS).
2. Workers crashing at start with an index error: rebuild the index with
   `docker compose run --rm indexer`, then `docker compose restart agent-worker`.
3. Runs stuck in `eia:queue:processing` after a crash are re-queued automatically by the reaper in
   any live worker after `RUN_DEADLINE_SECONDS + 60` s (once; a second loss marks the run
   `failed` with `WORKER_LOST`). Nothing needs to be done by hand.
4. Redis down: `docker compose restart redis`. It runs with `appendonly yes`, so queued runs survive.

---

## Incident log

Real failures met while building and testing the system. Newest last.

| ID | Date | What happened | Root cause | Impact | Resolution |
|---|---|---|---|---|---|
| INC-001 | 2026-10-27 | `run_local.py` failed: `ImportError: No module named 'jsonpatch'` / `'requests_toolbelt'` | Missing transitive dependencies of langchain-core under Python 3.13 | Local runs failed | Dependencies pinned in `requirements.txt` |
| INC-002 | 2026-10-27 | Evaluation batch crashed: `UnicodeEncodeError: 'charmap' codec can't encode character '✓'` | Windows console code page cp1252 | Eval report not printed | ASCII status markers |
| INC-003 | 2026-10-29 | Under Docker Compose every run stayed `QUEUED` forever | Run records lived in a Python dict inside the API process; the worker container dequeued the id, found no record in its own memory and silently returned | No request could complete in the compose deployment (would score zero at the demo) | Run store, events, caches and feedback moved to Redis (`api/storage.py`); verified with API, worker, verifier and stub as separate processes |
| INC-004 | 2026-10-29 | Worker loop logged errors and never processed jobs when Redis was reachable | Redis client `socket_timeout=0.2 s` was shorter than the 2 s blocking pop, so every `BRPOP` raised a timeout | Same as INC-003 even after the store fix | `socket_timeout=10 s`; `BLMOVE` into a processing list with a reaper for crashed workers |
| INC-005 | 2026-10-29 | Load test reported fast responses but measured nothing | Locust posted `nearest_protected_area`, a field the contract forbids: 100 % of submissions were 422 | D6 numbers were meaningless | Locust payload uses the published contract; the SLO metric is the complete run (`full_run`), not the POST |
| INC-006 | 2026-10-29 | Every NVIDIA NIM call returned HTTP 403 "Authorization failed" | The configured API key was rejected by the provider (well-formed `nvapi-` key, rejected for every model) | No live LLM; system ran on the stub; previously the old client swallowed such errors and returned fake output | Old client replaced by one that raises errors so the breaker and fallback path see them; key regeneration required (see Failure mode 1) |
| INC-007 | 2026-10-29 | First `search_corpus` in each new process timed out at 10 s | Cold load of FAISS plus the embedding model (~8 s) inside the first tool call | First run after every restart lost its first search | `warm_up()` loads the index at worker / verifier / API start |
| INC-008 | 2026-10-29 | `python -m ingest build` crashed on `170_OM_07_11_2014.pdf`: `PdfReadError: startxref not found` | Corrupt / truncated PDF download | Index could not be built | Unreadable documents are recorded in the manifest as skipped and the build continues |
| INC-009 | 2026-10-29 | In the `no_find_modifiers` evaluation, rejected runs looped until the 24-step limit instead of stopping after 2 verification retries | The retry counter was incremented inside a LangGraph routing function; LangGraph discards state changes made by routers, so the counter never rose | Retries were bounded only by the step limit; escalation reasons were wrong (`MODIFIERS_NOT_CHECKED` instead of `VERIFICATION_FAILED`) | Counters and escalation reasons are now written only by nodes (Screener, escalate); routers only read state. Retry rate in the eval went from a false 0 % to the real 68 % |

| INC-010 | 2026-10-29 | First runs on the real model escalated with `LIMIT_TOOL_CALLS`: the model kept searching office memoranda until the budget ran out | Prompt asked for economy but nothing enforced it; tool budget shared across retries | Correct drafts never reached the Verifier | Per-attempt allowance of 8 tool calls, remaining count returned with every tool result, then a forced final answer (`tool_choice: "none"`) |
| INC-011 | 2026-10-29 | Correct answers rejected with `QUOTE_NOT_FOUND` | Real models tidy quotes from table rows (add `\|`, `...`, change case); the check required an exact substring | Right answers escalated | Quote check accepts ellipses/separators if 85 % of the quote is verbatim runs of the passage; invented quotes still fail (tested) |
| INC-012 | 2026-10-29 | Forced final answers came back empty, then HTTP 400 | Removing `tools` from a request whose history holds tool calls is rejected by the provider; with no tools the reasoning model spent the 1,200-token budget thinking | `SCREENER_OUTPUT_INVALID` escalations | Keep tools declared with `tool_choice: "none"`; `LLM_MAX_OUTPUT_TOKENS=4096`; `LLM_REASONING_EFFORT=low` (11 s → 3 s per verifier call) |
| INC-013 | 2026-10-29 | Solar PV run escalated `PROVIDER_UNAVAILABLE` after 263 s, far past the 90 s deadline | Slow forced-answer calls timed out at 30 s and were retried 4× on each of two models; retries ignored the run deadline | A no-clearance case looked like a provider outage | Every LLM call's timeout is capped at the time left and no call starts with < 5 s left (`RunDeadlineExceeded` → `LIMIT_WALL_CLOCK`, breaker untouched); same run now answers in 18 s |
| INC-014 | 2026-10-29 | Solar no-clearance drafts rejected (`MODIFIERS_NOT_CHECKED`, then "not supported") | Verifier applied General Condition checks to a row cited only to rule it out; Verifier prompt demanded a quote proving absence from the Schedule; worker re-sent a slow verification after a fixed 60 s HTTP timeout | Correct no-clearance answers escalated | GC checks only for Category A/B and the governing row; prompt explains how no-clearance is judged; worker waits for the run's remaining time and retries only connection failures |
