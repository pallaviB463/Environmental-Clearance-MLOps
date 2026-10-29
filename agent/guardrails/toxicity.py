import re
from typing import Any, Dict, List, Tuple


TOXIC_PATTERNS = [
    # Bribery / Regulatory coercion
    (r"\b(bribe|kickback|payoff|under the table|grease\s+hands?)\b", "regulatory_corruption"),
    (r"\b(threaten|extort|blackmail|destroy\s+career)\b", "coercion_threat"),
    # Harassment / Profanity
    (r"\b(bastard|bitch|idiot|moron|stupid|asshole|corrupt\s+officials?)\b", "hostile_language"),
    # Compliance falsification directives
    (r"\b(fake\s+the\s+data|forge|falsify|hide\s+pollution|fudge\s+numbers?)\b", "fraudulent_compliance")
]


def check_toxicity(text: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Scans input text for toxic, threatening, or fraudulent compliance directives (Requirement L4).

    Returns:
        (is_toxic, details_dict)
    """
    if not text:
        return False, {"is_toxic": False, "score": 0.0, "flagged": []}

    flagged = []
    text_lower = text.lower()

    for pattern, category in TOXIC_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            flagged.append({
                "category": category,
                "matched_text": match.group(0)
            })

    is_toxic = len(flagged) > 0
    score = min(1.0, len(flagged) * 0.4)

    return is_toxic, {
        "is_toxic": is_toxic,
        "score": score,
        "flagged": flagged,
        "detail": f"Detected {len(flagged)} safety/toxicity violations." if is_toxic else "Clean"
    }
