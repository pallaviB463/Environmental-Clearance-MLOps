"""
Escalation path shown to the caller (A8 / F7): who should pick the case up, and what
they need to resolve it.
"""
from typing import Dict, Optional


REVIEW_QUEUE = "Accredited EIA consultant review queue"

NEXT_STEPS: Dict[str, str] = {
    "PROXIMITY_UNCERTAIN": "Obtain a certified survey of the distance to the protected-area boundary and resubmit with basis 'surveyed'.",
    "OUT_OF_CORPUS": "The activity is not covered by the indexed EIA corpus (e.g. CRZ Notification). A consultant must identify the governing notification.",
    "SECTOR_AMBIGUOUS": "Resubmit naming the specific activity (e.g. cement plant, thermal power plant) so a single Schedule item applies.",
    "AMENDMENT_CONFLICT": "The Schedule entry has amendments recorded as quashed or not in force. A consultant must confirm the operative text with MoEFCC / SEIAA.",
    "INSUFFICIENT_INFORMATION": "Resubmit with the capacity or area the Schedule threshold depends on.",
    "PROMPT_INJECTION_DETECTED": "Remove instruction-like text from the free-text fields and resubmit.",
    "TOXIC_INPUT": "Resubmit without abusive or coercive content.",
    "PROVIDER_UNAVAILABLE": "The model provider was unavailable. A reviewer can use the attached provisional opinion, or resubmit later.",
    "VERIFIER_UNAVAILABLE": "The verification step could not run, so no answer was released. Resubmit later.",
    "VERIFICATION_FAILED": "The draft could not be verified against the retrieved provisions. A consultant must screen this project.",
    "OUTPUT_GUARDRAIL_FAILED": "The draft failed output checks and was withheld. A consultant must screen this project.",
}


def escalation_path(escalation: Optional[Dict]) -> Optional[Dict]:
    if not escalation:
        return None
    code = escalation.get("reason_code", "")
    next_step = NEXT_STEPS.get(code)
    if next_step is None and code.startswith("LIMIT_"):
        next_step = "The run hit a safety limit (steps, tool calls or time) before reaching a verified answer. A consultant must screen this project."
    return {
        **escalation,
        "assigned_to": REVIEW_QUEUE,
        "next_step": next_step or "A consultant must screen this project.",
    }
