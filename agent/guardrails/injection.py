import re
from typing import Dict, List


INJECTION_PATTERNS: List[str] = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"disregard\s+(all\s+)?previous\s+instructions",
    r"forget\s+(all\s+)?previous\s+instructions",
    r"override\s+(the\s+)?system",
    r"reveal\s+(the\s+)?system\s+prompt",
    r"show\s+(me\s+)?your\s+system\s+prompt",
    r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
]


def check_prompt_injection(text: str) -> Dict:
    """
    Perform a deterministic first-pass prompt-injection check.

    This is not the only security layer; it catches common
    instruction-override patterns before text reaches an LLM.
    """

    detected_patterns = []

    normalized_text = text.lower().strip()

    for pattern in INJECTION_PATTERNS:

        if re.search(
            pattern,
            normalized_text,
            flags=re.IGNORECASE
        ):
            detected_patterns.append(pattern)

    return {
        "safe": len(detected_patterns) == 0,
        "detected_patterns": detected_patterns
    }