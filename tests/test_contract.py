import pytest
from pydantic import ValidationError

from api.contract import FeedbackSubmission, ScreeningSubmission


VALID = {
    "description": "Integrated cement plant 2 km from a national park.",
    "sector_hint": "cement",
    "capacity": {"value": 0.8, "unit": "MTPA"},
    "location": {"state": "Gujarat", "district": "Gir Somnath"},
    "proximity": [{"feature": "protected_area", "subtype": "national_park", "distance_km": 2.0}],
}


def test_valid_submission_is_accepted_and_normalised():
    submission = ScreeningSubmission(**VALID)
    assert submission.capacity.unit == "mtpa"
    assert submission.proximity[0].basis == "surveyed"


@pytest.mark.parametrize("change, field", [
    ({"capacity": {"value": -1, "unit": "mtpa"}}, "range"),
    ({"capacity": {"value": 1, "unit": "furlongs"}}, "categorical unit"),
    ({"capacity": {"value": 300, "unit": "mw"}}, "cross-field: MW for cement"),
    ({"location": {"state": "Atlantis", "district": "Somewhere"}}, "categorical state"),
    ({"proximity": [{"feature": "volcano", "distance_km": 1}]}, "categorical feature"),
    ({"proximity": [{"feature": "protected_area", "distance_km": 900}]}, "distance range"),
    ({"proximity": [{"feature": "protected_area", "distance_km": 2, "basis": "guess"}]}, "basis category"),
    ({"sector_hint": "spaceport"}, "sector category"),
    ({"surprise": True}, "unknown field"),
    ({"description": "short"}, "description length"),
    ({"project_area_ha": 10, "area_ha": 12}, "cross-field: area given twice"),
])
def test_invalid_submissions_are_rejected(change, field):
    with pytest.raises(ValidationError):
        ScreeningSubmission(**{**VALID, **change})


def test_missing_distance_is_allowed_so_the_run_can_escalate():
    submission = ScreeningSubmission(**{**VALID, "proximity": [{"feature": "protected_area", "subtype": "national_park"}]})
    assert submission.proximity[0].distance_km is None


def test_unsatisfactory_feedback_needs_a_reason():
    with pytest.raises(ValidationError):
        FeedbackSubmission(satisfactory=False)
    assert FeedbackSubmission(satisfactory=False, reason="wrong item").reason == "wrong item"
    assert FeedbackSubmission(satisfactory=True).reason is None
