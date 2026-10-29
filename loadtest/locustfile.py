"""
Load test (Requirement D6). Run against the stack with the stub LLM (llm-stub, 1.5 s per
call), so the test measures this system, not the provider's rate limits.

The SLO is on a COMPLETE run: submission to final result. Each task submits, polls until
the run finishes, and reports the whole duration as the custom request "full_run". The
submit and poll HTTP calls are reported too, but they are not the SLO metric.

    locust -f loadtest/locustfile.py --headless -u 10 -r 2 -t 3m --host http://localhost:8000

Env:
    LOADTEST_CACHE=off   (default) every payload is unique, so the cache cannot help
    LOADTEST_CACHE=on    payloads repeat, to measure the effect of the run cache (D7)
"""
import os
import random
import time
import uuid

from locust import HttpUser, between, events, task


SLO_SECONDS = 60.0
POLL_INTERVAL = 1.0
UNIQUE = os.getenv("LOADTEST_CACHE", "off") != "on"

SCENARIOS = [
    ("cement", "mtpa", (0.3, 0.95), "Integrated cement plant near a national park.",
     [{"feature": "protected_area", "subtype": "national_park", "distance_km": 2.0}]),
    ("cement", "mtpa", (0.3, 0.95), "Cement grinding unit at a remote site.", []),
    ("thermal_power", "mw", (50, 450), "Coal based thermal power plant.",
     [{"feature": "protected_area", "subtype": "wildlife_sanctuary", "distance_km": 8.0}]),
    ("mining", "ha", (20, 240), "Limestone mining lease.", []),
]


def _payload():
    sector, unit, (low, high), text, proximity = random.choice(SCENARIOS)
    value = round(random.uniform(low, high), 3) if UNIQUE else low
    return {
        "project_name": f"loadtest-{uuid.uuid4().hex[:6]}" if UNIQUE else "loadtest",
        "sector_hint": sector,
        "description": f"{text} Capacity {value} {unit}.",
        "capacity": {"value": value, "unit": unit},
        "location": {"state": "Gujarat", "district": "Kutch"},
        "proximity": proximity,
    }


class ScreeningUser(HttpUser):
    # A consultant submits, waits for the result, reads it, then submits the next project
    wait_time = between(1, 3)

    def on_start(self):
        # One client id per simulated user: the per-client rate limit applies per user
        self.client.headers["X-Client-ID"] = f"locust-{uuid.uuid4().hex[:8]}"

    @task(10)
    def complete_run(self):
        started = time.time()
        with self.client.post("/v1/screenings", json=_payload(), name="POST /v1/screenings", catch_response=True) as resp:
            if resp.status_code != 202:
                resp.failure(f"submit returned {resp.status_code}: {resp.text[:120]}")
                return
            run_id = resp.json()["run_id"]

        status = "queued"
        while time.time() - started < SLO_SECONDS * 3:
            with self.client.get(f"/v1/screenings/{run_id}", name="GET /v1/screenings/[id]", catch_response=True) as poll:
                if poll.status_code != 200:
                    poll.failure(f"poll returned {poll.status_code}")
                    break
                status = poll.json()["status"]
            if status not in ("queued", "running"):
                break
            time.sleep(POLL_INTERVAL)

        elapsed_ms = (time.time() - started) * 1000
        failed = status in ("queued", "running", "failed")
        events.request.fire(
            request_type="RUN",
            name="full_run",
            response_time=elapsed_ms,
            response_length=0,
            exception=Exception(f"run ended {status}") if failed else None,
            context={},
        )

    @task(1)
    def malformed_submission(self):
        """Quarantine path under load: must be a fast 422, never a run."""
        bad = {"description": "Negative capacity test plant", "sector_hint": "cement",
               "capacity": {"value": -5.0, "unit": "mtpa"}}
        with self.client.post("/v1/screenings", json=bad, name="POST /v1/screenings (malformed)", catch_response=True) as resp:
            if resp.status_code == 422:
                resp.success()
            else:
                resp.failure(f"expected 422, got {resp.status_code}")
