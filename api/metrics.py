"""
API-level Prometheus metrics: ingestion boundary, HTTP latency/errors, cache, rate limiting,
feedback, queue depth, and index freshness (D2) read from the index manifest at scrape time.
"""
import json

from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily, InfoMetricFamily

from agent.config import settings
from agent.redis_client import get_redis


REQUESTS_TOTAL = Counter(
    "eia_screening_requests_total",
    "Screening submissions at the ingestion boundary",
    ["status"]  # accepted | quarantined | rate_limited | cache_hit
)

QUARANTINE_RECORDS_TOTAL = Counter(
    "eia_quarantine_records_total",
    "Malformed records quarantined before starting an agent run"
)

HTTP_REQUEST_SECONDS = Histogram(
    "eia_http_request_seconds",
    "HTTP request latency by route",
    ["method", "route", "status_class"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5]
)

FEEDBACK_TOTAL = Counter(
    "eia_feedback_total",
    "Caller feedback on results",
    ["satisfactory"]
)


class QueueAndIndexCollector:
    """Computed on each scrape so the values are always current."""

    def collect(self):
        depth = GaugeMetricFamily("eia_queue_depth", "Runs waiting in the queue", labels=["queue"])
        redis = get_redis()
        if redis is not None:
            try:
                depth.add_metric(["pending"], redis.llen("eia:queue"))
                depth.add_metric(["processing"], redis.llen("eia:queue:processing"))
            except Exception:
                pass
        yield depth

        manifest_file = settings.index_dir / "manifest.json"
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text())
            built = GaugeMetricFamily("eia_index_built_timestamp_seconds", "When the corpus index was last built")
            built.add_metric([], manifest.get("built_at_unix", 0))
            yield built
            chunks = GaugeMetricFamily("eia_index_chunks", "Chunks in the active index")
            chunks.add_metric([], manifest.get("chunk_count", 0))
            yield chunks
            docs = GaugeMetricFamily("eia_index_documents", "Documents by indexing outcome", labels=["outcome"])
            docs.add_metric(["indexed"], manifest.get("documents_indexed", 0))
            docs.add_metric(["skipped"], len(manifest.get("documents_skipped", [])))
            yield docs
            throughput = GaugeMetricFamily("eia_indexer_throughput_chunks_per_second",
                                           "Throughput of the last ingestion run", labels=["stage"])
            throughput.add_metric(["pipeline"], manifest.get("throughput_chunks_per_sec", 0))
            throughput.add_metric(["embedding"], manifest.get("embedding_throughput_chunks_per_sec", 0))
            yield throughput
            info = InfoMetricFamily("eia_index", "Index build information")
            info.add_metric([], {"embedding_model": manifest.get("embedding_model", ""),
                                 "built_at": manifest.get("built_at", ""),
                                 "chunker_version": str(manifest.get("chunker_version", ""))})
            yield info


REGISTRY.register(QueueAndIndexCollector())
