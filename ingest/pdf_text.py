import logging
import re
from pathlib import Path
from typing import List

from pypdf import PdfReader


logging.getLogger("pypdf").setLevel(logging.ERROR)

# Glyphs from the Symbol font that pypdf returns as private-use code points
SYMBOL_FONT_MAP = {
    "": "≥",
    "": "≤",
    "": "•",
    "": "-",
}

# A document whose first pages hold fewer characters than this is treated as scanned
MIN_TEXT_LAYER_CHARS = 200


def normalise(text: str) -> str:
    for glyph, replacement in SYMBOL_FONT_MAP.items():
        text = text.replace(glyph, replacement)
    text = text.replace(" ", " ")
    return text


def read_pages(path: Path) -> List[str]:
    """
    Return the text of every page. Scanned pages come back as empty strings;
    OCR is out of scope for this pipeline, so such documents are recorded and skipped.
    """
    reader = PdfReader(str(path))
    return [normalise(page.extract_text() or "") for page in reader.pages]


def has_text_layer(pages: List[str]) -> bool:
    return len("".join(pages[:3]).strip()) >= MIN_TEXT_LAYER_CHARS


def strip_page_number(page_text: str) -> str:
    """Drop the bare page-number line that pypdf puts at the top of each page."""
    lines = page_text.split("\n")
    if lines and re.fullmatch(r"\s*\d{1,3}\s*", lines[0]):
        lines = lines[1:]
    return "\n".join(lines)
