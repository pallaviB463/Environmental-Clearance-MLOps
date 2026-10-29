"""Generates dashboards/eia.json. Edit the panel list here, then run: python observability/grafana/build_dashboard.py"""
import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
panels, y = [], 0


def row(title):
    global y
    panels.append({"type": "row", "title": title, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "collapsed": False})
    y += 1


def panel(title, targets, x, w=8, h=8, unit="short", kind="timeseries", thresholds=None, description=""):
    p = {
        "type": kind, "title": title, "description": description, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"datasource": DS, "expr": expr, "legendFormat": legend, "refId": chr(65 + i)}
                    for i, (expr, legend) in enumerate(targets)],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }
    if thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": thresholds}
        if kind == "timeseries":
            p["fieldConfig"]["defaults"]["custom"] = {"thresholdsStyle": {"mode": "line"}}
    panels.append(p)


def next_line(h=8):
    global y
    y += h


SLO = [{"color": "green", "value": None}, {"color": "red", "value": 60}]

row("Service level (D5 / D6) - SLO: p95 of a complete run <= 60 s")
panel("Run latency, submission to result (p50 / p95)", [
    ('histogram_quantile(0.50, sum(rate(eia_run_e2e_seconds_bucket[2m])) by (le))', "p50"),
    ('histogram_quantile(0.95, sum(rate(eia_run_e2e_seconds_bucket[2m])) by (le))', "p95"),
], 0, unit="s", thresholds=SLO)
panel("Throughput", [
    ('sum(rate(eia_runs_total[1m]))', "completed runs/s"),
    ('sum by (status) (rate(eia_screening_requests_total[1m]))', "submissions {{status}}/s"),
], 8, unit="reqps")
panel("Error rate", [
    ('sum(rate(eia_runs_total{status="failed"}[5m])) / clamp_min(sum(rate(eia_runs_total[5m])), 1e-9)', "failed runs"),
    ('sum(rate(eia_http_request_seconds_count{status_class="5xx"}[5m])) / clamp_min(sum(rate(eia_http_request_seconds_count[5m])), 1e-9)', "HTTP 5xx"),
], 16, unit="percentunit")
next_line()
panel("Availability (share of successful scrapes, 5 min)", [
    ('avg by (job) (avg_over_time(up{job=~"api|agent-worker|verifier-agent|llm-stub"}[5m]))', "{{job}}"),
], 0, unit="percentunit")
panel("Queue depth", [('eia_queue_depth', "{{queue}}")], 8)
panel("API latency p95 by route", [
    ('histogram_quantile(0.95, sum by (le, route) (rate(eia_http_request_seconds_bucket[5m])))', "{{route}}"),
], 16, unit="s")
next_line()

row("Agents (A6)")
panel("Task success rate per agent", [
    ('sum by (agent) (rate(eia_agent_tasks_total{outcome=~"draft|pass"}[5m])) / clamp_min(sum by (agent) (rate(eia_agent_tasks_total[5m])), 1e-9)', "{{agent}}"),
], 0, unit="percentunit")
panel("Steps and tool calls per run (mean)", [
    ('sum(rate(eia_agent_steps_per_run_sum[5m])) / clamp_min(sum(rate(eia_agent_steps_per_run_count[5m])), 1e-9)', "steps"),
    ('sum(rate(eia_agent_tool_calls_per_run_sum[5m])) / clamp_min(sum(rate(eia_agent_tool_calls_per_run_count[5m])), 1e-9)', "tool calls"),
], 8)
panel("Per-step latency p95 (agent / step kind)", [
    ('histogram_quantile(0.95, sum by (le, agent, kind) (rate(eia_agent_step_seconds_bucket[5m])))', "{{agent}} {{kind}}"),
], 16, unit="s")
next_line()
panel("LLM retry rate per agent", [
    ('sum by (agent) (rate(eia_llm_retries_total[5m])) / clamp_min(sum by (agent) (rate(eia_llm_calls_total[5m])), 1e-9)', "{{agent}}"),
], 0, unit="percentunit")
panel("Circuit breaker (0 closed, 1 half-open, 2 open)", [
    ('max by (model) (eia_circuit_breaker_state)', "{{model}}"),
], 8, thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 2}])
panel("Container uptime", [
    ('time() - process_start_time_seconds{job=~"api|agent-worker|verifier-agent|llm-stub"}', "{{job}} {{instance}}"),
], 16, unit="s")
next_line()
panel("Verifier verdicts", [('sum by (verdict, reason) (increase(eia_verification_outcomes_total[15m]))', "{{verdict}} {{reason}}")], 0)
panel("Escalations by reason", [('sum by (reason_code) (increase(eia_escalations_total[15m]))', "{{reason_code}}")], 8)
panel("Run mode (agentic vs degraded)", [('sum by (mode, status) (rate(eia_runs_total[5m]))', "{{mode}} {{status}}")], 16, unit="reqps")
next_line()

row("Cost and quality (L5 / L6)")
panel("Cost per run (mean, USD)", [
    ('sum(rate(eia_run_cost_usd_sum[15m])) / clamp_min(sum(rate(eia_run_cost_usd_count[15m])), 1e-9)', "per run"),
], 0, unit="currencyUSD")
panel("Cost by agent (last hour, USD)", [('sum by (agent) (increase(eia_llm_cost_usd_total[1h]))', "{{agent}}")], 8, unit="currencyUSD")
panel("Tokens/s by agent", [('sum by (agent, direction) (rate(eia_llm_tokens_total[5m]))', "{{agent}} {{direction}}")], 16)
next_line()
panel("Live quality of sampled runs (mean score)", [
    ('sum by (metric) (rate(eia_live_quality_score_sum[15m])) / clamp_min(sum by (metric) (rate(eia_live_quality_score_count[15m])), 1e-9)', "{{metric}}"),
], 0, w=12, unit="percentunit")
panel("Caller feedback: satisfaction rate (1 h)", [
    ('sum(increase(eia_feedback_total{satisfactory="true"}[1h])) / clamp_min(sum(increase(eia_feedback_total[1h])), 1e-9)', "satisfied"),
], 12, w=12, unit="percentunit")
next_line()

row("Resources per container (cAdvisor) and corpus freshness (D2)")
panel("CPU per container (cores)", [
    ('sum by (name) (rate(container_cpu_usage_seconds_total{name=~".+"}[1m]))', "{{name}}"),
    ('rate(process_cpu_seconds_total{job=~"api|agent-worker|verifier-agent|llm-stub"}[1m])', "process {{job}} {{instance}}"),
], 0)
panel("Memory per container", [
    ('sum by (name) (container_memory_working_set_bytes{name=~".+"})', "{{name}}"),
    ('process_resident_memory_bytes{job=~"api|agent-worker|verifier-agent|llm-stub"}', "process {{job}} {{instance}}"),
], 8, unit="bytes")
panel("Index age and size", [
    ('time() - eia_index_built_timestamp_seconds', "age (s)"),
    ('eia_index_chunks', "chunks"),
    ('eia_indexer_throughput_chunks_per_second', "throughput {{stage}} chunks/s"),
], 16)
next_line()

dashboard = {
    "uid": "eia-prescreening", "title": "EIA Pre-Screening Service", "timezone": "browser",
    "schemaVersion": 39, "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
    "panels": [dict(p, id=i + 1) for i, p in enumerate(panels)],
}
out = Path(__file__).resolve().parent / "dashboards" / "eia.json"
out.write_text(json.dumps(dashboard, indent=2))
print(f"{len(panels)} panels -> {out}")
