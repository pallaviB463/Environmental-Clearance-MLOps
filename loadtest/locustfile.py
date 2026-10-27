import time
from locust import HttpUser, task, between


class ScreeningLoadTestUser(HttpUser):
    wait_time = between(1, 2)

    @task(3)
    def submit_and_poll_section_4_1_case(self):
        """
        Simulates consultant submitting the Section 4.1 Cement Plant Case
        and polling until final result is ready.
        Measures complete end-to-end latency against p95 <= 60s SLO (Requirement D6).
        """
        payload = {
            "project_name": "Locust Load Test Plant",
            "sector_hint": "cement",
            "description": "Cement grinding facility located 2.0 km from national park boundary.",
            "capacity": {"value": 0.8, "unit": "million_tonnes_per_annum"},
            "location": {"state": "Gujarat", "district": "Gir Somnath"},
            "nearest_protected_area": {"type": "national_park", "distance_km": 2.0, "basis": "surveyed"}
        }

        start_time = time.time()
        with self.client.post("/v1/screenings", json=payload, catch_response=True) as resp:
            if resp.status_code != 202:
                resp.failure(f"Submission failed: {resp.status_code}")
                return
            run_id = resp.json().get("run_id")

        # Poll status
        completed = False
        while time.time() - start_time < 60:
            time.sleep(0.5)
            with self.client.get(f"/v1/screenings/{run_id}", catch_response=True) as poll_resp:
                if poll_resp.status_code == 200:
                    data = poll_resp.json()
                    if data.get("status") in ["answered", "escalated"]:
                        completed = True
                        break

        if not completed:
            self.environment.events.request.fire(
                request_type="POLL",
                name="complete_run_latency",
                response_time=(time.time() - start_time) * 1000,
                response_length=0,
                exception=Exception("Run exceeded 60s SLO deadline")
            )

    @task(1)
    def submit_malformed_case(self):
        """
        Verifies boundary quarantine rejection under load (HTTP 422).
        """
        bad_payload = {
            "project_name": "Malformed Capacity",
            "description": "Negative capacity test.",
            "sector_hint": "cement",
            "capacity": {"value": -5.0, "unit": "million_tonnes_per_annum"},
            "location": {"state": "Karnataka", "district": "Bellary"}
        }
        with self.client.post("/v1/screenings", json=bad_payload, catch_response=True) as resp:
            if resp.status_code == 422:
                resp.success()
            else:
                resp.failure(f"Expected 422, got {resp.status_code}")
