import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


RUNS_FILE = Path(__file__).resolve().parent.parent / "data" / "runs_store.json"
FEEDBACK_FILE = Path(__file__).resolve().parent.parent / "data" / "feedback_store.json"


class RunRecord(BaseModel):
    run_id: str
    correlation_id: str
    status: str = "QUEUED"  # QUEUED, RUNNING, ANSWERED, ESCALATED, FAILED
    submitted_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    latency_seconds: Optional[float] = None

    request_payload: Dict[str, Any]
    prompt_version: str = "v1"

    category: Optional[str] = None
    route: Optional[str] = None
    basis: Optional[str] = None
    cited_chunk_ids: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)

    verification: Optional[Dict[str, Any]] = None
    escalation: Optional[Dict[str, Any]] = None

    steps: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    from_cache: bool = False


class FeedbackRecord(BaseModel):
    feedback_id: str
    run_id: str
    timestamp: float = Field(default_factory=time.time)
    satisfactory: bool
    reason: Optional[str] = None


class RunStorage:
    def __init__(self):
        self.runs: Dict[str, RunRecord] = {}
        self.feedback: List[FeedbackRecord] = []
        self.cache: Dict[str, str] = {}  # payload_hash -> run_id

    def compute_cache_key(self, payload: Dict[str, Any]) -> str:
        # Canonical string of description + capacity + location + proximity
        canonical = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def create_run(self, run_id: str, correlation_id: str, payload: Dict[str, Any]) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            correlation_id=correlation_id,
            status="QUEUED",
            submitted_at=time.time(),
            request_payload=payload
        )
        self.runs[run_id] = record
        return record

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        return self.runs.get(run_id)

    def update_run(self, record: RunRecord):
        self.runs[record.run_id] = record

    def add_feedback(self, run_id: str, satisfactory: bool, reason: Optional[str] = None) -> FeedbackRecord:
        rec = FeedbackRecord(
            feedback_id=f"fb_{int(time.time() * 1000)}",
            run_id=run_id,
            timestamp=time.time(),
            satisfactory=satisfactory,
            reason=reason
        )
        self.feedback.append(rec)
        return rec

    def count_active_runs(self) -> int:
        return sum(1 for r in self.runs.values() if r.status in ["QUEUED", "RUNNING", "running", "queued"])

    def record_feedback(self, run_id: str, rating: int, comments: Optional[str] = None):
        return self.add_feedback(run_id=run_id, satisfactory=(rating >= 3), reason=comments)

    def get_feedback_summary(self) -> Dict[str, Any]:
        total = len(self.feedback)
        if total == 0:
            return {"total": 0, "satisfactory": 0, "unsatisfactory": 0, "satisfaction_rate": 1.0}
        sat = sum(1 for f in self.feedback if f.satisfactory)
        return {
            "total": total,
            "satisfactory": sat,
            "unsatisfactory": total - sat,
            "satisfaction_rate": round(sat / total, 4)
        }


storage = RunStorage()
