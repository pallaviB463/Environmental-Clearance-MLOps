import time

from fastapi.testclient import TestClient

from tests.conftest import needs_index


VALID = {
    "description": "Integrated cement plant of 0.8 MTPA located 2.0 km from Gir National Park.",
    "sector_hint": "cement",
    "capacity": {"value": 0.8, "unit": "mtpa"},
    "location": {"state": "Gujarat", "district": "Gir Somnath"},
    "proximity": [{"feature": "protected_area", "subtype": "national_park", "distance_km": 2.0}],
}


def client():
    from api.app import app
    return TestClient(app)


def test_malformed_request_is_quarantined_without_a_run():
    response = client().post("/v1/screenings", json={**VALID, "capacity": {"value": -1, "unit": "mtpa"}})
    assert response.status_code == 422
    body = response.json()
    assert body["agent_started"] is False and "run_id" not in body
    assert body["quarantine_id"].startswith("quar_")


def test_contract_is_published():
    body = client().get("/v1/contract").json()
    assert "screening_submission" in body and body["screening_submission"]["additionalProperties"] is False


@needs_index
def test_submit_poll_trace_and_feedback():
    c = client()
    response = c.post("/v1/screenings", json=VALID, headers={"X-Correlation-ID": "corr_test_123"})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert response.headers["X-Correlation-ID"] == "corr_test_123"

    for _ in range(60):
        record = c.get(f"/v1/screenings/{run_id}").json()
        if record["status"] not in ("queued", "running"):
            break
        time.sleep(0.5)
    assert record["status"] == "answered"
    assert record["result"]["route"] == "category_a_central"

    trace = c.get(f"/v1/screenings/{run_id}/trace").json()
    kinds = {e["kind"] for e in trace["events"]}
    assert {"tool_call", "llm_call", "verification", "run_end"} <= kinds
    assert trace["prompt_hashes"]["screener"]

    assert c.post(f"/v1/screenings/{run_id}/feedback", json={"satisfactory": False}).status_code == 422
    assert c.post(f"/v1/screenings/{run_id}/feedback", json={"satisfactory": True}).status_code == 200
    assert c.get("/v1/feedback/summary").json()["total"] >= 1
