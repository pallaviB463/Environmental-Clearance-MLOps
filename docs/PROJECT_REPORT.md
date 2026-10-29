# Environmental Clearance Pre-Screening Service: Project Report

UE24AM342AA5 ML System Design and AgentOps · Mini Project 13 · Jackfruit (Level 3)

Sections follow PS §11: problem and scope; agent design; architecture with deployment
boundaries; design decisions and what was rejected; evaluation before and after a change;
p95 target, measurements, bottleneck and cost; what did not work.
Numbers marked **[pending]** need a run on the team's machine (Docker, a working NVIDIA key)
and are not estimated here.

---

## 1. Problem and scope

Before a project is built in India it may need prior environmental clearance under the EIA
Notification 2006. Screening decides two things: is the activity in the Schedule, and is it
Category A (Central Government, MoEFCC on EAC recommendation) or Category B (State SEIAA). A wrong
category is expensive: a clearance at the wrong level can be set aside after work has begun.

The service accepts a project description, validates it, decides Schedule applicability and
category from the notification, and routes it to **no clearance**, **Category B (State)** or
**Category A (Central)** with cited provisions, or **escalates to a human**. It produces a
screening opinion; an accredited consultant decides. Impact assessment is out of scope.

**The difficulty (PS §3, §4.1).** The Schedule is a table of thresholds, but a note after it, the
General Condition (GC), moves Category B projects to Category A by location (within 5 km of a
protected area, critically polluted area, eco-sensitive area or inter-State/international boundary;
10 km for items 1(c), 1(d), 7(c), 7(d)). The GC is not repeated in any row. We confirmed the trap
on our own index: for *"Integrated cement plant 0.8 MTPA located 2 km from Gir National Park"* the
top six semantic results contain the cement row `schedule:3(b)` but **not** the GC.

**Corpus.** 123 official MoEFCC documents (manifest: `data/corpus_manifest.csv`): the consolidated
notification amended to March 2025, the principal notification, 77 gazette amendments and 44
office memoranda. 71 have a text layer and are indexed (1,380 chunks); 51 are scans (OCR is out of
scope and they are recorded as skipped) and 1 is a corrupt download.

## 2. Agent design

### Topology (A1, A2)

```
extract ──► screen ◄───────── retry with Verifier feedback ─────────┐
   │          │                                                      │
   │          ├─ draft says escalate / budget exhausted ─► escalate   │
   │          ├─ LLM provider unavailable ────────────────► degrade  │
   │          ▼                                                      │
   │        verify ── pass ──► finalise (output guardrails) ──► answered
   │          ├──── retry (budget left) ──────────────────────────────┘
   │          └──── escalate / retries exhausted ──► escalate
   └─ injection, toxicity, uncertain proximity ──► escalate
```

| Agent | Responsibility | Tools | Model budget |
|---|---|---|---|
| Extractor (deterministic node) | Input guardrails, entity extraction (F3), proximity uncertainty | none | no LLM call |
| **Screener** (LLM agent) | Find the Schedule row, apply thresholds, look for modifying provisions, draft a cited opinion or escalate | `search_corpus`, `get_clause`, `find_modifiers`, `get_request_fields` | shares the run's step / tool / time budget |
| **Verifier** (LLM agent, own service) | Check the draft against the retrieved text; send it back with feedback or escalate | `get_clause`, `search_corpus` | up to 3 turns per attempt |
| Rule engine | Degraded fallback only: provisional opinion when no model is reachable | n/a | none |

The two agents have separate prompts (`agent/prompts/<version>/{screener,verifier}.txt`), separate
tool sets and separate processes in Docker (`agent-worker`, `verifier-agent`). The hand-off is a
typed contract: `DraftDetermination` (category, route, Schedule item, basis, citations with verbatim
quotes, modifiers checked) plus every passage retrieved in the run.

**Failure mid-run.** Screener model unavailable → `degrade` (rule-based provisional opinion,
escalated, never answered). Verifier unreachable → escalated `VERIFIER_UNAVAILABLE` (an unverified
draft is never returned). Worker process dies → its queue message stays in
`eia:queue:processing`; a reaper re-queues it once, then marks the run `WORKER_LOST`.

### Retrieval is a tool the agent chooses

Nothing in code fixes the retrieval order. The Screener decides whether to search, what to search
for, and whether to follow a cross-reference. `find_modifiers(chunk_id)` returns what can change how
a provision applies, following links recorded **at ingestion from the text itself**: the GC when the
row says "General Condition shall apply", whether the item is in the GC's 10 km proviso, amendment
footnotes with whether they are in force, the routing paragraphs, and later notifications that cite
the item. This is PS §5 steps 2 and 3: determine whether another provision modifies the row, then
search again from what was read.

### Verification (A3)

Deterministic checks first (cheap, authoritative), then an LLM review:
1. every citation resolves to a passage retrieved in this run;
2. every quote appears verbatim in its passage (catches invented evidence);
3. category and route agree; a Schedule row (or para 2 for no-clearance) is cited;
4. **modifier check**: if the cited row says the GC applies, the GC must have been retrieved; if the
   project is within the GC distance (5 km, or 10 km for proviso items, read from the GC text's
   references) a Category B draft is rejected; a GC-based Category A must cite the GC;
5. a row whose amendment history is recorded as quashed / not in force is escalated;
6. the Verifier model reads the full text of every cited passage and reports unsupported claims and
   ignored provisions.

`retry` returns the draft to the Screener with the specific feedback (e.g. *"Schedule item 3(b)
states 'General Condition shall apply'. Call find_modifiers on schedule:3(b) …"*), at most
`MAX_VERIFICATION_RETRIES` times; then the run escalates.

### Loop limits (A1)

Per run: `MAX_STEPS=24` (graph nodes + LLM turns; a normal run uses 8-12), `MAX_TOOL_CALLS=12`
(normal: 3-5), `RUN_DEADLINE_SECONDS=90` wall clock, `MAX_VERIFICATION_RETRIES=2`. Each LLM call has
`LLM_TIMEOUT_SECONDS`, each tool call `TOOL_TIMEOUT_SECONDS`. Hitting any limit escalates with
`LIMIT_STEPS` / `LIMIT_TOOL_CALLS` / `LIMIT_WALL_CLOCK`.

### Resilience (A5)

`agent/llm/gateway.py`, per model on the path `LLM_MODEL → LLM_FALLBACK_MODEL`:
circuit breaker → retry with exponential backoff (0.5 s, 1 s, 2 s + jitter, transient errors only) →
timeout → provider. All models failed or open → degraded path. Demonstrable on request:
`POST /admin/chaos {"llm_down": true}` makes every call fail as HTTP 503. Measured on the local
stack: the first run made 1 + 3 retried calls (3.7 s) and degraded; on the next run the fifth
consecutive failure opened the breaker and the run failed fast (0.7 s).

## 3. Architecture and deployment boundaries (D3)

See the diagram in the README. Services under Docker Compose:

| Service | Why it is its own deployment unit |
|---|---|
| `api` | I/O-bound; must answer polls while agents run. Scales on request rate. |
| `agent-worker` (×N) | Network/CPU-heavy (LLM turns, query embeddings). Scales on queue depth (A7). |
| `verifier-agent` | Second agent; fails independently (worker escalates instead of releasing an unverified answer); released independently (a stricter verifier prompt without redeploying the Screener). |
| `llm-stub` | Provider stand-in for load tests (D6); swapped out by configuration only. |
| `indexer` | One-shot batch job with a different resource profile; must finish before anything reads the index. |
| `redis` | The only shared state: queue, runs, events, caches, rate limits, chaos switch. |
| `prometheus`, `grafana`, `jaeger` (+ optional `cadvisor`) | Observability, isolated from the app. |

Async execution (A4): `POST` returns `202` with a run id; the run is queued in Redis; the caller
polls. Polling was chosen over callbacks because callers (browser, Locust, curl) have no public
endpoint of their own; the queue decouples submission from execution so bursts wait instead of
overloading the provider.

## 4. Design decisions and what was rejected

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Chunking | Structure-aware: one chunk per Schedule row, GC and SC as own chunks, paragraphs by roman sub-paragraph, footnotes separate | Fixed 500-char windows: split rows and could cut the GC from its 10 km proviso |
| Reaching the GC | `find_modifiers` follows links extracted from the text at ingestion | Hard-coding "cement → GC" in code: fails for every other row; a second blind similarity search: the GC's wording does not resemble the request |
| Agent framework | LangGraph (explicit graph, conditional retry edge) | CrewAI: less control over the verify/retry loop and limits |
| Vector store | FAISS via LangChain, local MiniLM embeddings, on-disk embedding cache | Qdrant / hosted embeddings: not in the PS list (L1); embedding through a paid API is the only real cost in the PS |
| Verification | Deterministic checks + separate LLM reviewer | LLM-only self-check: a model reviewing its own draft in the same conversation tends to agree with itself |
| Degradation | Rule engine opinion attached to an escalation | Returning the rule-engine answer as the result: the PS forbids a non-completed run being returned as confident |
| Old hand-typed corpus (11 chunks) | Replaced by the indexed text | Its thresholds were out of date (mining 50 ha vs 250/500 ha in the 2025 text) |
| SLO metric | Complete run (submit → result) | Timing the POST: measures ~10 ms of queueing, not the service |
| Generic "industrial project" (PS wording) | Escalate `SECTOR_AMBIGUOUS` | Guessing a row: the earlier version silently cited the cement row for any "industrial" project |

## 5. Evaluation (L2, L3)

**Set:** 28 scenarios in `eval/scenarios.json`, each with expected outcome, supporting passages and
reason; includes PS §4.1 (RC-1), boundary distances (4.9 / 5.1 km), the 10 km proviso, all four GC
triggers, quashed amendments, missing / estimated distances, out-of-corpus, two injection attempts,
no-clearance cases, and the PS wording taken literally. Every scenario is first validated against
the published contract. Run: `python -m eval.run_eval`.

**Metrics** (definitions and formulas in `eval/metrics.py`; TruLens-equivalent, computed in-house):
- *groundedness*: share of citations that resolve to retrieved text **and** whose quote is verbatim;
- *context relevance*: share of retrieved passages that are reference supporting passages or were cited;
- *context recall*: share of supporting passages that were retrieved (for §4.1: was the GC reached);
- *faithfulness*: the final draft passes the Verifier's deterministic checks when re-run
  independently (optionally plus an LLM entailment judge, `--judge llm`);
- *hallucination rate*: share of runs with at least one citation that does not resolve or whose quote
  is not in the passage.

**Results with the stub LLM** (proves the harness and the agent loop; the stub's answers come from
the rule engine, so these are not model-quality numbers): route accuracy 1.00, groundedness 1.00,
context relevance 0.18, context recall 1.00, faithfulness 1.00, hallucination 0.00. Context relevance
is genuinely low: `find_modifiers` also returns later notifications that seldom matter.

**Deliberate change (L3): remove the `find_modifiers` tool** (`--change no_find_modifiers`), i.e.
fall back to plain similarity search. Hypothesis: the GC is no longer reached on the first attempt,
the Verifier rejects the Category B drafts, and recovery costs retries and latency.
Measured with the stub (the stub models a naive single-pass RAG model when it has no modifier
tool, and follows the Verifier's feedback on a retry):

| metric | before | after (no `find_modifiers`) | change |
|---|---|---|---|
| route accuracy | 1.00 | 1.00 | +0.00 |
| groundedness | 1.00 | 1.00 | +0.00 |
| context relevance | 0.18 | 0.30 | +0.12 |
| context recall | 1.00 | 0.98 | −0.02 |
| faithfulness | 1.00 | 1.00 | +0.00 |
| hallucination rate | 0.00 | 0.00 | +0.00 |
| runs rejected by the Verifier at least once | 0 % | **68 %** | +68 pts |
| LLM calls per run | 4.1 | 6.8 | **+63 %** |
| cost per 100 runs | $0.175 | $0.261 | **+49 %** |

Reading: without the modifier tool, two drafts in three ignore the General Condition and are
caught by the Verifier, which names the missing provision; the retry recovers the right answer, so
accuracy holds, but at 63 % more model calls. Removing PS §5 step 2 is paid for by step 4.
Retrieval precision (context relevance) improves because fewer loosely related passages are pulled
in, which supports trimming `find_modifiers` output (see §7).
With the real LLM, all four metrics before/after: **[pending]**.

**Prompt variants (L2):** v1 is a concise baseline ("check whether any other provision modifies
the row"); v2 spells out the procedure (row → thresholds → `find_modifiers` → re-search from what
was read; consolidated text supersedes older gazette text). `python -m eval.run_eval --compare v1 v2`.
With the stub both variants behave identically by construction. Real-LLM comparison: **[pending]**.

## 6. Performance, cost and caching (D6, D7, L5, A7)

**SLO (declared before measuring, `docs/SLO.md`):** p95 of a complete run ≤ 60 s at 10 concurrent
users, stub LLM at 1.5 s per call.

**Measured on the local multi-process stack** (same topology as Compose: API, Redis, worker(s),
verifier service and stub service as separate processes on one laptop; 90 s per level; the queue is
drained before each level; results in `loadtest/results/`):

| users | 1 worker: runs/s | p50 | p95 | SLO | 3 workers: runs/s | p50 | p95 | SLO |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.09 | 8.1 s | 10.0 s | met | 0.09 | 8.1 s | 10.0 s | met |
| 5 | 0.11 | 37 s | 39 s | met | 0.37 | 10 s | 14 s | met |
| 10 | 0.13 | 45 s | **79 s** | **missed** | 0.36 | 22-24 s | 27 s | met |
| 20 | | | | | 0.36 | 47 s | 54 s | met |
| 30 | | | | | 0.36 | 49 s | **78 s** | **missed** |

The SLO fails at **10 users with one worker** and at **30 users with three**. Scaling from one to
three workers multiplied throughput by 3.2 (0.11 → 0.36 runs/s).

**Docker Compose measurements** (`python -m loadtest.run_sweep` with 1 and 3 workers): **[pending]**.

**Bottleneck.** Worker concurrency. A worker executes one run at a time, and a run is ~8 s, almost
all of it waiting on 5 stub model calls of 1.5 s. Throughput is therefore capped at about
workers / 8.3 s: 0.12 runs/s for one worker, 0.36 for three, exactly what was measured, and above
the cap every extra user only adds queue wait (p50 climbs while runs/s stays flat). Scaling was
linear, so no shared component (API, Redis, verifier, stub) saturated at three workers. Because the
work is I/O wait, the next step would be several concurrent runs per worker (async or threads)
rather than more containers.

**Cost (L5).** Tokens and cost are recorded at call time per step (`usage_by_step` in every run
record and trace) and per agent (Prometheus `eia_llm_cost_usd_total{agent}`). Prices are configured
(`LLM_PRICE_*`; the NVIDIA free tier bills $0, so a reference list price is used). With the stub,
token counts are characters/4 of the messages actually sent, about 7,960 tokens per run, which at
the configured prices is about $0.18 per 100 runs. **Largest cost driver: the Screener's multi-turn
context** (~8,200 prompt tokens per run against ~1,500 for the Verifier), because every turn
re-sends the conversation including earlier tool results. Real-LLM cost per 100 runs: **[pending]**.

**Caching (D7).** Whole-run cache keyed on the payload, prompt version, index version and models
(only completed, non-degraded runs); retrieval cache keyed on query and index version; embedding
cache on disk. Measured at 10 users with three workers:

| | runs/s | p50 | p95 | cost per run |
|---|---|---|---|---|
| cache off (unique payloads) | 0.37 | 22 s | 27 s | full |
| cache on (repeated payloads) | 2.62 | 0.01 s | 9.1 s | 80 % hit rate → about 80 % lower |

The remaining p95 with the cache on comes from the first, uncached submission of each payload.
During the cache-on run the per-client rate limit rejected 64 submissions: with instant answers each
simulated user exceeded 20 submissions a minute, which is the limiter doing its job as a cost control. Rate limiting: per client id, fixed one-minute
window in Redis, `RATE_LIMIT_PER_MINUTE`.

## 7. What did not work, and limitations

- **Live LLM evaluation is pending.** The team's NVIDIA key returned HTTP 403 for every model
  (INC-006). Every component was built and tested against the OpenAI-compatible stub, which is
  why the stub can stand in for the provider with no code change.
- The previous version of this project reported 100 % faithfulness from a rule-based pipeline with
  no model in the loop; those numbers were removed.
- 51 scanned documents are not indexed (no OCR); cases that depend only on them would escalate.
- Context relevance is low (0.18): `find_modifiers` is generous. Candidate fix: rank later
  notifications by similarity to the row and keep the top one.
- The stub Verifier model always agrees, so the LLM-review half of verification is exercised only
  with a real model; the deterministic half is exercised by tests.
- Circuit breakers are per process (each worker learns about an outage separately); a shared breaker
  in Redis was not built.
- cAdvisor is optional because Docker Desktop on macOS can refuse its host mounts; per-container CPU
  and memory then come from each service's own process metrics.
