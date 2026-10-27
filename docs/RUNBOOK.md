# Production Runbook & Incident Log

**Service:** Environmental Clearance Pre-Screening Service  
**Course:** UE24AM342AA5 — ML System Design & AgentOps  
**Component:** Jackfruit (Level 3)  
**Standard:** Requirement D8  

---

## 1. Failure Mode 1: LLM Circuit Breaker Open (Provider Outage / Rate Limit)

### Symptom
- Status endpoint returns `status: "escalated"` with reason code `CIRCUIT_BREAKER_OPEN`.
- Logs report `[WARN] Circuit breaker tripped to OPEN state after 5 consecutive timeouts/failures`.
- Ingestion endpoint continues accepting submissions (HTTP 202), but worker escalates immediately rather than hanging.

### Confirmation
1. Inspect the circuit breaker status via Prometheus metric:
   ```bash
   curl -s http://localhost:8000/metrics | grep eia_circuit_breaker
   ```
2. Check recent application logs for upstream provider timeouts:
   ```bash
   docker logs eia-api --tail 50 | grep -E "TIMEOUT|CIRCUIT_BREAKER"
   ```
3. Test direct reachability of upstream model endpoint:
   ```bash
   curl -I -m 5 https://api.together.xyz/health
   ```

### Recovery
1. **Fallback Model Activation:** In `.env`, switch `LLM_PROVIDER` to fallback model (e.g., secondary provider or local stub):
   ```bash
   LLM_PROVIDER=stub
   ```
2. **Reset the Circuit Breaker:** After the reset timeout (30 seconds), the circuit enters `HALF-OPEN` state and probes with a single trial request.
3. **Restart the Worker Service:**
   ```bash
   docker compose restart agent-worker
   ```

---

## 2. Failure Mode 2: Ingestion Queue Backlog / Worker Starvation

### Symptom
- Polling status remains `QUEUED` for $> 30\text{ seconds}$.
- Latency metric `eia_run_duration_seconds` spikes towards the p95 SLO limit ($60\text{s}$).
- Web UI displays persistent `Ingesting / In Queue` state.

### Confirmation
1. Check Redis queue depth:
   ```bash
   docker exec -it eia-redis redis-cli LLEN screening_queue
   ```
2. Check worker container health and step concurrency:
   ```bash
   docker ps --filter "name=agent-worker"
   docker logs --tail 30 $(docker ps -qf "name=agent-worker")
   ```

### Recovery
1. **Scale Workers:** Use Docker Compose horizontal worker scaling (Requirement A7):
   ```bash
   docker compose up --scale agent-worker=3 -d
   ```
2. Verify that queue backlog drops to 0 and throughput increases proportionally.
3. If Redis connection failed, restart Redis and flush stale locks:
   ```bash
   docker compose restart redis
   ```

---

## 3. Incident Log (Genuine Entries Recorded During Development)

| Incident ID | Date | Failure Description | Root Cause | Impact | Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **INC-001** | 2026-10-27 | Agent runtime failed with `ImportError: No module named 'jsonpatch'` & `'requests_toolbelt'` during local run. | Python 3.13 site-packages missing transitive dependencies for `langchain-core` / `langgraph`. | Execution of `run_local.py` failed with Exit Code 1. | Pinned `requests-toolbelt>=1.0.0` and `jsonpatch>=1.38` in `requirements.txt` and installed into active environment. |
| **INC-002** | 2026-10-27 | Batch evaluation script crashed with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'`. | Windows PowerShell console default encoding (cp1252) cannot encode Unicode checkmarks in stdout. | Batch script failed at scenario 20 report printing. | Replaced Unicode glyphs with ASCII `[PASS]` / `[FAIL]` status symbols and UTF-8 JSON serialization. |
| **INC-003** | 2026-10-27 | API server startup crashed with `NameError: name 'Optional' is not defined`. | Missing `from typing import Optional` in `api/quarantine.py`. | Server aborted on initialization. | Added `Optional` import; verified server starts and serves 200 OK on `/health`. |
