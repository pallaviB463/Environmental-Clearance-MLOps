"""
Agent-level Prometheus metrics (Requirements A6 / L5 / L6). Each process (worker,
verifier) exposes its own copy; Prometheus scrapes every replica and Grafana sums them.
Container uptime comes from the default process_start_time_seconds collector.
"""
from prometheus_client import Counter, Gauge, Histogram


STEP_BUCKETS = [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60]
RUN_BUCKETS = [0.5, 1, 2.5, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180]

# Per-agent task outcomes -> success rate = success / all
AGENT_TASKS_TOTAL = Counter(
    "eia_agent_tasks_total",
    "Agent task outcomes per agent",
    ["agent", "outcome"]
)

AGENT_STEP_SECONDS = Histogram(
    "eia_agent_step_seconds",
    "Latency of each agent step (LLM turn, tool call, check)",
    ["agent", "kind"],
    buckets=STEP_BUCKETS
)

AGENT_STEPS_PER_RUN = Histogram(
    "eia_agent_steps_per_run",
    "Steps taken per run, per agent",
    ["agent"],
    buckets=[1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20]
)

AGENT_TOOL_CALLS_PER_RUN = Histogram(
    "eia_agent_tool_calls_per_run",
    "Tool calls made per run, per agent",
    ["agent"],
    buckets=[0, 1, 2, 3, 4, 5, 6, 8, 10]
)

TOOL_CALLS_TOTAL = Counter(
    "eia_tool_calls_total",
    "Tool calls by tool and outcome",
    ["agent", "tool", "outcome"]
)

LLM_CALLS_TOTAL = Counter(
    "eia_llm_calls_total",
    "LLM calls by agent, model and outcome",
    ["agent", "model", "outcome"]
)

LLM_RETRIES_TOTAL = Counter(
    "eia_llm_retries_total",
    "LLM call retries (each retry after a transient failure)",
    ["agent"]
)

LLM_TOKENS_TOTAL = Counter(
    "eia_llm_tokens_total",
    "Tokens consumed by agent and direction",
    ["agent", "direction"]
)

LLM_COST_USD_TOTAL = Counter(
    "eia_llm_cost_usd_total",
    "Estimated LLM cost in USD by agent",
    ["agent"]
)

CIRCUIT_BREAKER_STATE = Gauge(
    "eia_circuit_breaker_state",
    "Circuit breaker state per model: 0 closed, 1 half-open, 2 open",
    ["model"]
)

VERIFICATION_OUTCOMES_TOTAL = Counter(
    "eia_verification_outcomes_total",
    "Verifier verdicts",
    ["verdict", "reason"]
)

RUNS_TOTAL = Counter(
    "eia_runs_total",
    "Completed runs by final status and mode",
    ["status", "mode"]
)

RUN_E2E_SECONDS = Histogram(
    "eia_run_e2e_seconds",
    "Submission to final result, measured per run (SLO metric)",
    buckets=RUN_BUCKETS
)

RUN_COST_USD = Histogram(
    "eia_run_cost_usd",
    "Cost per run in USD",
    buckets=[0, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]
)

ESCALATIONS_TOTAL = Counter(
    "eia_escalations_total",
    "Escalations by reason code",
    ["reason_code"]
)

LIVE_QUALITY_SCORE = Histogram(
    "eia_live_quality_score",
    "Automatic evaluation scores of sampled live runs (0..1)",
    ["metric"],
    buckets=[0, 0.25, 0.5, 0.75, 0.9, 1.0]
)

RUNS_IN_PROGRESS = Gauge(
    "eia_worker_runs_in_progress",
    "Runs currently executing in this worker"
)
