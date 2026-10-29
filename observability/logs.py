"""
Structured JSON logging with the run's correlation id on every line (Requirement D5).
"""
import contextvars
import json
import logging
import sys
import time


correlation_id_var = contextvars.ContextVar("correlation_id", default=None)
run_id_var = contextvars.ContextVar("run_id", default=None)

_service = "eia"


class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": _service,
            "logger": record.name,
            "correlation_id": correlation_id_var.get(),
            "run_id": run_id_var.get(),
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(service: str, level: int = logging.INFO) -> None:
    global _service
    _service = service
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "faiss"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, message: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, message, extra={"fields": fields})
