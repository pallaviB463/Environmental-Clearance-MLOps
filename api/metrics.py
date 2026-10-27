import time
from prometheus_client import Counter, Histogram, Gauge


# Request & Quarantine counters
REQUESTS_TOTAL = Counter(
    "eia_screening_requests_total",
    "Total screening submissions at the ingestion boundary",
    ["status"]
)

QUARANTINE_RECORDS_TOTAL = Counter(
    "eia_quarantine_records_total",
    "Malformed records quarantined before starting agent run"
)

# Agent Run Outcomes
RUNS_TOTAL = Counter(
    "eia_agent_runs_total",
    "Total completed agent runs by final status",
    ["status"]
)

ESCALATIONS_TOTAL = Counter(
    "eia_escalations_total",
    "Total escalations by reason code",
    ["reason_code"]
)

# Latency Histogram for SLO (D6: p95 <= 60s)
RUN_LATENCY_SECONDS = Histogram(
    "eia_run_duration_seconds",
    "End-to-end latency from submission to final result",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0]
)

# Agent Activity & Cost Tracking (A6 / L5)
STEPS_TOTAL = Counter(
    "eia_agent_steps_total",
    "Total steps taken across agent runs"
)

TOOL_CALLS_TOTAL = Counter(
    "eia_agent_tool_calls_total",
    "Total tool calls executed by agents"
)

VERIFICATION_RETRIES_TOTAL = Counter(
    "eia_verification_retries_total",
    "Total retries triggered by verifier agent"
)

TOKENS_TOTAL = Counter(
    "eia_tokens_used_total",
    "Total LLM tokens consumed",
    ["token_type"]
)

COST_USD_TOTAL = Counter(
    "eia_estimated_cost_usd_total",
    "Total estimated USD cost of runs"
)

# Data Freshness & Pipeline Metrics (D2)
DATA_FRESHNESS_TIMESTAMP = Gauge(
    "eia_index_freshness_timestamp_seconds",
    "Unix timestamp when the corpus index was last generated"
)

INDEX_CHUNK_COUNT = Gauge(
    "eia_index_chunks_count",
    "Total chunks indexed in active corpus"
)

INDEXING_THROUGHPUT_CHUNKS_PER_SEC = Gauge(
    "eia_indexer_throughput_chunks_per_sec",
    "Throughput of the indexing pipeline in chunks/second"
)

# Initialize freshness gauges with current state
DATA_FRESHNESS_TIMESTAMP.set(time.time())
INDEX_CHUNK_COUNT.set(9.0)
INDEXING_THROUGHPUT_CHUNKS_PER_SEC.set(45.0)
