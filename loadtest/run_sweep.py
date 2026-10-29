"""
Concurrency sweep for D6 / A7. Runs Locust headless at increasing user counts and reports,
for the complete-run metric: RPS, p50, p95, failures, and whether the declared SLO
(docs/SLO.md: p95 <= 60 s) holds. Stops at the first level that breaks the SLO.

    python -m loadtest.run_sweep --host http://localhost:8000 --label workers1
    docker compose up -d --scale agent-worker=3
    python -m loadtest.run_sweep --host http://localhost:8000 --label workers3

Results: loadtest/results/<label>.json and .md
"""
import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx


SLO_P95_SECONDS = 60.0
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def queue_snapshot(host: str) -> dict:
    try:
        return httpx.get(f"{host}/health", timeout=5).json()
    except Exception:
        return {}


def wait_for_drain(host: str, timeout: float = 600) -> float:
    """Wait until no run is queued or in progress, so one level's backlog cannot inflate the next."""
    started = time.time()
    while time.time() - started < timeout:
        try:
            text = httpx.get(f"{host}/metrics", timeout=5).text
        except Exception:
            time.sleep(2)
            continue
        depths = [float(line.split()[-1]) for line in text.splitlines() if line.startswith("eia_queue_depth{")]
        if depths and sum(depths) == 0:
            return time.time() - started
        time.sleep(2)
    return time.time() - started


def run_level(host: str, users: int, duration: str, prefix: Path, cache: str) -> dict:
    cmd = [
        sys.executable, "-m", "locust", "-f", str(HERE / "locustfile.py"), "--headless",
        "-u", str(users), "-r", str(max(1, users // 2)), "-t", duration,
        "--host", host, "--csv", str(prefix), "--only-summary",
    ]
    subprocess.run(cmd, check=False, env={**__import__("os").environ, "LOADTEST_CACHE": cache},
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(f"{prefix}_stats.csv", newline="") as f:
        rows = {row["Name"]: row for row in csv.DictReader(f)}
    run = rows.get("full_run", {})
    submit = rows.get("POST /v1/screenings", {})
    count = int(run.get("Request Count", 0) or 0)
    seconds = lambda key: round(float(run.get(key, 0) or 0) / 1000, 2) if count else None
    return {
        "users": users,
        "completed_runs": count,
        "failed_runs": int(run.get("Failure Count", 0) or 0),
        "runs_per_second": round(float(run.get("Requests/s", 0) or 0), 3),
        "p50_s": seconds("50%"),
        "p95_s": seconds("95%"),
        "max_s": seconds("Max Response Time"),
        "submit_p95_ms": float(submit.get("95%", 0) or 0),
        "slo_met": count > 0 and seconds("95%") <= SLO_P95_SECONDS and int(run.get("Failure Count", 0) or 0) == 0,
        # No run finished inside the window: every run took longer than the test itself
        "note": "" if count else f"no run completed within the {duration} window",
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m loadtest.run_sweep")
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--users", nargs="+", type=int, default=[1, 2, 5, 10, 20, 40])
    parser.add_argument("--duration", default="2m")
    parser.add_argument("--label", default="sweep")
    parser.add_argument("--cache", choices=["off", "on"], default="off")
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    levels = []
    for users in args.users:
        drained = wait_for_drain(args.host)
        print(f"-> {users} users for {args.duration} (queue drained in {drained:.0f}s) ...", flush=True)
        level = run_level(args.host, users, args.duration, RESULTS / f"{args.label}_u{users}", args.cache)
        level["health_after"] = queue_snapshot(args.host)
        levels.append(level)
        print(f"   runs/s={level['runs_per_second']} p50={level['p50_s']}s p95={level['p95_s']}s "
              f"failed={level['failed_runs']} SLO {'met' if level['slo_met'] else 'MISSED'}", flush=True)
        if not level["slo_met"]:
            break

    first_fail = next((l["users"] for l in levels if not l["slo_met"]), None)
    report = {"label": args.label, "host": args.host, "cache": args.cache, "slo_p95_seconds": SLO_P95_SECONDS,
              "levels": levels, "first_failing_concurrency": first_fail}
    (RESULTS / f"{args.label}.json").write_text(json.dumps(report, indent=2))

    lines = [f"# Load test: {args.label} (cache {args.cache})", "",
             f"SLO: p95 of a complete run <= {SLO_P95_SECONDS:g} s", "",
             "| users | runs/s | p50 (s) | p95 (s) | failed | SLO |", "|---|---|---|---|---|---|"]
    for l in levels:
        p50 = l["p50_s"] if l["p50_s"] is not None else f"> {args.duration}"
        p95 = l["p95_s"] if l["p95_s"] is not None else f"> {args.duration}"
        lines.append(f"| {l['users']} | {l['runs_per_second']} | {p50} | {p95} | {l['failed_runs']} | "
                     f"{'met' if l['slo_met'] else 'MISSED'} |")
    lines.append("")
    lines.append(f"First concurrency that misses the SLO: {first_fail if first_fail else 'none in the tested range'}")
    (RESULTS / f"{args.label}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
