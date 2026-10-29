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
    # Role / instruction hijacking
    r"\byou\s+are\s+now\b",
    r"\bnew\s+instructions?\b",
    r"(?m)^\s*(system|assistant|developer)\s*:",
    r"\b(system|developer)\s+(prompt|message)\b",
    r"ignore\s+(the\s+)?(rules|schedule|general\s+condition|above|everything)",
    r"disregard\s+(the\s+)?(rules|schedule|general\s+condition|above)",
    # Attempts to dictate the outcome to the model
    r"\b(classify|categori[sz]e|mark|route|treat)\s+(this(\s+project)?|it|the\s+project)\s+as\s+(category\s+[ab]|no[\s_-]clearance|exempt)",
    r"\b(grant|approve)\s+(the\s+)?clearance\b",
    r"\b(do\s+not|don't|never)\s+(escalate|cite|check|verify)",
    # Breaking out of the data delimiters used in the prompt
    r"</?\s*(project_data|extracted_entities|system|instructions?)\s*>",
    r"\bcall\s+(the\s+)?(tool|function)\b",
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