"""
Versioned prompts (Requirement L2). Each agent's prompt is a file under prompts/<version>/.
The version and a hash of the exact text are recorded with every LLM call and every result,
so a response can always be traced to the prompt that produced it.
"""
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Tuple


PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(agent: str, version: str) -> Tuple[str, str]:
    """Return (text, short sha256) for prompts/<version>/<agent>.txt."""
    path = PROMPTS_DIR / version / f"{agent}.txt"
    if not path.exists():
        raise FileNotFoundError(f"No prompt '{agent}' for version '{version}' at {path}")
    text = path.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def available_versions() -> list:
    return sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))
