from typing import Dict, List


BLOCKED_PHRASES: List[str] = [
    "project is officially approved",
    "environmental clearance is granted",
    "clearance has been granted",
    "no further approval is required",
    "no further clearance is required",
    "this is an official determination",
]


ALLOWED_ROUTES = {
    "no_clearance",
    "category_b_state",
    "category_a_central"
}


DISCLAIMER = (
    "This is a screening opinion, not an authoritative "
    "environmental clearance determination."
)


def validate_output(
    text: str,
    route: str
) -> Dict:
    """
    Validate final output before it can be returned.
    """

    problems = []

    # ---------------------------------------------
    # Check route
    # ---------------------------------------------

    if route not in ALLOWED_ROUTES:
        problems.append(
            f"Invalid route: {route}"
        )

    # ---------------------------------------------
    # Check dangerous / authoritative claims
    # ---------------------------------------------

    normalized_text = text.lower()

    for phrase in BLOCKED_PHRASES:

        if phrase in normalized_text:
            problems.append(
                f"Blocked authoritative claim: {phrase}"
            )

    # ---------------------------------------------
    # Return validation result
    # ---------------------------------------------

    return {
        "safe": len(problems) == 0,
        "problems": problems,
        "disclaimer": DISCLAIMER
    }