"""
Run store shared by every container.

The API, every worker replica and the verifier read and write runs through Redis, so a
run created by the API is visible to whichever worker dequeues it (this was broken when
runs lived in a per-process dict). With REDIS_URL empty, a single-process in-memory
store is used for local development and tests.

Keys
    eia:run:<id>            run record (JSON), 7-day TTL
    eia:run:<id>:events     append-only trace events (JSON list)
    eia:cache:<hash>        run id of a completed run with the same inputs (D7)
    eia:feedback            feedback records (JSON list)
"""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent.config import settings
from agent.redis_client import get_redis


RUN_TTL_SECONDS = 7 * 24 * 3600
ACTIVE_STATUSES = ("queued", "running")


class RunRecord(BaseModel):
    run_id: str
    correlation_id: str
    client_id: str = "anonymous"
    status: str = "queued"  # queued, running, answered, escalated, failed
    mode: str = "agentic"   # agentic | degraded | cache
    submitted_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    latency_seconds: Optional[float] = None
    attempts: int = 0
    worker_id: Optional[str] = None
    trace_id: Optional[str] = None

    request_payload: Dict[str, Any]
    prompt_version: str = "v1"
    prompt_hashes: Dict[str, str] = Field(default_factory=dict)

    category: Optional[str] = None
    route: Optional[str] = None
    schedule_item: Optional[str] = None
    basis: Optional[str] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    escalation: Optional[Dict[str, Any]] = None
    provisional_opinion: Optional[Dict[str, Any]] = None
    disclaimer: Optional[str] = None

    steps: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    usage_by_step: List[Dict[str, Any]] = Field(default_factory=list)
    from_cache: bool = False
    cached_from_run: Optional[str] = None


class FeedbackRecord(BaseModel):
    feedback_id: str
    run_id: str
    timestamp: float = Field(default_factory=time.time)
    satisfactory: bool
    reason: Optional[str] = None
    run_status: Optional[str] = None
    run_route: Optional[str] = None
    prompt_version: Optional[str] = None


class RunStorage:

    def __init__(self):
        self._runs: Dict[str, str] = {}
        self._events: Dict[str, List[str]] = {}
        self._cache: Dict[str, str] = {}
        self._feedback: List[str] = []

    # -----------------------------------------------------
    # Runs
    # -----------------------------------------------------

    def create_run(self, record: RunRecord) -> RunRecord:
        self.update_run(record)
        return record

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        redis = get_redis()
        raw = redis.get(f"eia:run:{run_id}") if redis else self._runs.get(run_id)
        return RunRecord.model_validate_json(raw) if raw else None

    def update_run(self, record: RunRecord) -> None:
        raw = record.model_dump_json()
        redis = get_redis()
        if redis:
            redis.setex(f"eia:run:{record.run_id}", RUN_TTL_SECONDS, raw)
        else:
            self._runs[record.run_id] = raw

    def count_active_runs(self) -> int:
        redis = get_redis()
        if redis is None:
            return sum(1 for raw in self._runs.values() if json.loads(raw)["status"] in ACTIVE_STATUSES)
        count = 0
        for key in redis.scan_iter("eia:run:*", count=500):
            if key.endswith(":events"):
                continue
            raw = redis.get(key)
            if raw and json.loads(raw).get("status") in ACTIVE_STATUSES:
                count += 1
        return count

    # -----------------------------------------------------
    # Trace events (D5 run reconstruction)
    # -----------------------------------------------------

    def append_event(self, run_id: str, event: Dict[str, Any]) -> None:
        raw = json.dumps(event, default=str)
        redis = get_redis()
        if redis:
            key = f"eia:run:{run_id}:events"
            redis.rpush(key, raw)
            redis.expire(key, RUN_TTL_SECONDS)
        else:
            self._events.setdefault(run_id, []).append(raw)

    def get_events(self, run_id: str) -> List[Dict[str, Any]]:
        redis = get_redis()
        raws = redis.lrange(f"eia:run:{run_id}:events", 0, -1) if redis else self._events.get(run_id, [])
        events = [json.loads(raw) for raw in raws]
        return sorted(events, key=lambda e: e.get("ts", 0))

    # -----------------------------------------------------
    # Whole-run cache (D7)
    # -----------------------------------------------------

    @staticmethod
    def compute_cache_key(payload: Dict[str, Any], prompt_version: str, index_version: str) -> str:
        canonical = json.dumps(
            {"payload": payload, "prompt": prompt_version, "index": index_version,
             "models": [settings.llm_model, settings.llm_fallback_model]},
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def cache_get(self, key: str) -> Optional[str]:
        if not settings.cache_enabled:
            return None
        redis = get_redis()
        return redis.get(f"eia:cache:{key}") if redis else self._cache.get(key)

    def cache_set(self, key: str, run_id: str) -> None:
        if not settings.cache_enabled:
            return
        redis = get_redis()
        if redis:
            redis.setex(f"eia:cache:{key}", settings.run_cache_ttl_seconds, run_id)
        else:
            self._cache[key] = run_id

    # -----------------------------------------------------
    # Feedback (L6)
    # -----------------------------------------------------

    def add_feedback(self, record: FeedbackRecord) -> FeedbackRecord:
        raw = record.model_dump_json()
        redis = get_redis()
        if redis:
            redis.rpush("eia:feedback", raw)
        else:
            self._feedback.append(raw)
        return record

    def list_feedback(self) -> List[FeedbackRecord]:
        redis = get_redis()
        raws = redis.lrange("eia:feedback", 0, -1) if redis else self._feedback
        return [FeedbackRecord.model_validate_json(raw) for raw in raws]

    def get_feedback_summary(self) -> Dict[str, Any]:
        records = self.list_feedback()
        total = len(records)
        satisfactory = sum(1 for r in records if r.satisfactory)
        by_route: Dict[str, Dict[str, int]] = {}
        reasons: Dict[str, int] = {}
        for r in records:
            bucket = by_route.setdefault(r.run_route or r.run_status or "unknown", {"satisfactory": 0, "unsatisfactory": 0})
            bucket["satisfactory" if r.satisfactory else "unsatisfactory"] += 1
            if not r.satisfactory and r.reason:
                reasons[r.reason.strip().lower()[:80]] = reasons.get(r.reason.strip().lower()[:80], 0) + 1
        return {
            "total": total,
            "satisfactory": satisfactory,
            "unsatisfactory": total - satisfactory,
            "satisfaction_rate": round(satisfactory / total, 4) if total else None,
            "by_route": by_route,
            "top_unsatisfactory_reasons": sorted(reasons.items(), key=lambda kv: -kv[1])[:10],
        }


storage = RunStorage()
