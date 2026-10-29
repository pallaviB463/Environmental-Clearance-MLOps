import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


QUARANTINE_FILE = Path(__file__).resolve().parent.parent / "data" / "quarantined_records.json"


class QuarantinedRecord(BaseModel):
    quarantine_id: str
    timestamp: float = Field(default_factory=time.time)
    client_ip: Optional[str] = "unknown"
    payload: Dict[str, Any]
    field_errors: List[Dict[str, Any]]
    agent_started: bool = False  # Proof that no agent run started


class QuarantineStore:
    def __init__(self, storage_path: Path = QUARANTINE_FILE):
        self.storage_path = storage_path
        self._records: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self._records = json.load(f)
            except Exception:
                self._records = []

    def _save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self._records, f, indent=2)

    def record_quarantine(
        self,
        quarantine_id: str,
        payload: Dict[str, Any],
        field_errors: List[Dict[str, Any]],
        client_ip: str = "127.0.0.1"
    ) -> QuarantinedRecord:
        record = QuarantinedRecord(
            quarantine_id=quarantine_id,
            timestamp=time.time(),
            client_ip=client_ip,
            payload=payload,
            field_errors=field_errors,
            agent_started=False
        )
        self._records.append(record.model_dump())
        self._save()
        return record

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def get_records(self, limit: int = 50) -> Dict[str, Any]:
        return {'records': list(reversed(self._records))[:limit]}

    def count(self) -> int:
        return len(self._records)


quarantine_store = QuarantineStore()
