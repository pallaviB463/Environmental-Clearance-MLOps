import json
import re
from typing import Any, Dict, Iterable, Optional


_DECODER = json.JSONDecoder()


def extract_json_object(text: str, expected_keys: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """
    Return the last JSON object in a model reply, preferring one that has any of
    `expected_keys`. Tolerates <think> blocks, code fences and prose around the JSON,
    which reasoning models often emit before the answer.
    """
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)

    found = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = _DECODER.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)

    keys = set(expected_keys)
    preferred = [obj for obj in found if keys & set(obj)] if keys else found
    return (preferred or found or [None])[-1]
