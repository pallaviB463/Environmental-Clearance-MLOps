"""
Quarantine for rejected submissions (Requirements F2 / D1). Each record keeps the raw
payload and the field-level errors, and proves no agent run started. Stored in Redis
when available (shared by API replicas), otherwise in a local JSON file.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent.redis_client import get_redis


QUARANTINE_FILE = Path(__file__).resolve().parent.parent / "data" / "quarantined_records.json"
REDIS_KEY = "eia:quarantine"


class QuarantinedRecord(BaseModel):
    quarantine_id: str
    timestamp: float = Field(default_factory=time.time)
    client_ip: Optional[str] = "unknown"
    correlation_id: Optional[str] = None
    payload: Any
    field_errors: List[Dict[str, Any]]
    agent_started: bool = False  # proof that no agent run started


class QuarantineStore:

    def __init__(self, storage_path: Path = QUARANTINE_FILE):
        self.storage_path = storage_path

    def _load_file(self) -> List[Dict[str, Any]]:
        if self.storage_path.exists():
            try:
                return json.loads(self.storage_path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def record_quarantine(
        self,
        quarantine_id: str,
        payload: Any,
        field_errors: List[Dict[str, Any]],
        client_ip: str = "unknown",
        correlation_id: Optional[str] = None,
    ) -> QuarantinedRecord:
        record = QuarantinedRecord(
            quarantine_id=quarantine_id,
            client_ip=client_ip,
            correlation_id=correlation_id,
            payload=payload,
            field_errors=field_errors,
            agent_started=False,
        )
        redis = get_redis()
        if redis:
            redis.rpush(REDIS_KEY, record.model_dump_json())
        else:
            records = self._load_file()
            records.append(record.model_dump())
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        return record

    def get_records(self, limit: int = 50) -> Dict[str, Any]:
        redis = get_redis()
        if redis:
            records = [json.loads(raw) for raw in redis.lrange(REDIS_KEY, -limit, -1)]
        else:
            records = self._load_file()[-limit:]
        return {"count": self.count(), "records": list(reversed(records))}

    def count(self) -> int:
        redis = get_redis()
        return redis.llen(REDIS_KEY) if redis else len(self._load_file())


quarantine_store = QuarantineStore()
