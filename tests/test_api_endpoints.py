import time
import httpx


BASE_URL = "http://127.0.0.1:8000"


def test_section_4_1_and_quarantine():
    print("=" * 60)
    print("RUNNING API VERIFICATION TEST SUITE")
    print("=" * 60)

    # 1. Health check
    r = httpx.get(f"{BASE_URL}/health")
    assert r.status_code == 200, f"Health check failed: {r.text}"
    print("[PASS] Health endpoint 200 OK")

    # 2. Section 4.1 Reference Case (Cement plant 0.8 MTPA, 2.0 km from Gir NP)
    payload_4_1 = {
        "project_name": "Greenfield cement plant — Kodinar",
        "activity": "new",
        "sector_description": "Integrated cement plant (clinker production and grinding)",
        "sector_hint": "cement",
        "description": "Integrated cement plant (clinker production and grinding) located 2.0 km from the boundary of Gir National Park.",
        "capacity": {"value": 0.8, "unit": "million_tonnes_per_annum"},
        "project_area_ha": 45.0,
        "location": {"state": "Gujarat", "district": "Gir Somnath"},
        "proximity": [
            {
                "feature": "protected_area",
                "subtype": "national_park",
                "name": "Gir National Park",
                "distance_km": 2.0,
                "basis": "surveyed"
            }
        ]
    }

    sub_res = httpx.post(f"{BASE_URL}/v1/screenings", json=payload_4_1)
    assert sub_res.status_code == 202, f"Submission failed: {sub_res.text}"
    sub_data = sub_res.json()
    run_id = sub_data["run_id"]
    print(f"[PASS] Section 4.1 Case submitted successfully. Run ID: {run_id}")

    # Poll status
    completed = False
    for attempt in range(15):
        time.sleep(0.5)
        poll_res = httpx.get(f"{BASE_URL}/v1/screenings/{run_id}")
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        if poll_data["status"] not in ["QUEUED", "RUNNING"]:
            completed = True
            break

    assert completed, "Run did not complete within timeout."
    print(f"[PASS] Run completed with status: {poll_data['status']}")
    print(f"       Category: {poll_data.get('category')} | Route: {poll_data.get('route')}")
    print(f"       Basis: {poll_data.get('basis')}")
    print(f"       Cited Chunk IDs: {poll_data.get('cited_chunk_ids')}")

    # Verify Section 4.1 requirements
    assert poll_data["category"] == "A", f"Expected Category A, got {poll_data['category']}"
    assert poll_data["route"] == "category_a_central", f"Expected Central route, got {poll_data['route']}"
    assert "schedule:3(b)" in poll_data["cited_chunk_ids"], "Must cite Schedule row 3(b)"
    assert "gc:s_o_1599_e_2014" in poll_data["cited_chunk_ids"], "Must cite General Condition"
    assert poll_data["verification"]["passed"] is True, "Verification must pass"
    print("[PASS] Section 4.1 Difficult Case correctly resolved to Category A Central citing both Schedule and GC!")

    # 3. Test Quarantine Boundary (RC-11: Negative capacity value)
    malformed_payload = {
        "project_name": "Illegal Capacity Test",
        "description": "Invalid cement plant with negative capacity.",
        "sector_hint": "cement",
        "capacity": {"value": -5.0, "unit": "million_tonnes_per_annum"},
        "location": {"state": "Karnataka", "district": "Bellary"}
    }
    quar_res = httpx.post(f"{BASE_URL}/v1/screenings", json=malformed_payload)
    assert quar_res.status_code == 422, f"Expected HTTP 422 for malformed input, got {quar_res.status_code}"
    quar_data = quar_res.json()
    print(f"[PASS] Malformed input quarantined at boundary. Quarantine ID: {quar_data.get('quarantine_id')}")

    # Verify quarantine store records it with agent_started == False
    q_audit = httpx.get(f"{BASE_URL}/v1/quarantine").json()
    assert q_audit["count"] >= 1
    latest_q = q_audit["records"][-1]
    assert latest_q["agent_started"] is False, "Proof that no agent run started!"
    print(f"[PASS] Quarantine audit verified: {q_audit['count']} records isolated, agent_started=False confirmed.")

    # 4. Feedback endpoint
    fb_res = httpx.post(f"{BASE_URL}/v1/screenings/{run_id}/feedback", json={
        "satisfactory": True,
        "reason": "Accurate legal citation and correct central appraisal route."
    })
    assert fb_res.status_code == 200
    fb_summary = httpx.get(f"{BASE_URL}/v1/feedback/summary").json()
    print(f"[PASS] Feedback endpoint recorded: {fb_summary}")

    # 5. Prometheus metrics
    metrics_res = httpx.get(f"{BASE_URL}/metrics")
    assert metrics_res.status_code == 200
    assert "eia_screening_requests_total" in metrics_res.text
    assert "eia_quarantine_records_total" in metrics_res.text
    print("[PASS] Prometheus metrics endpoint scraping successfully.")

    print("\n" + "=" * 60)
    print("ALL API VALIDATION CHECKS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    test_section_4_1_and_quarantine()
