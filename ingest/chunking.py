"""
Structure-aware chunking of the EIA corpus (Requirement L1).

Why not fixed-size chunks: the difficulty in this corpus (PS section 3) is that the
Schedule row and the General Condition that modifies it live in different places.
A fixed 500-character window would cut Schedule rows in half and could split the
General Condition from its 10 km proviso. So the consolidated notification is cut
along its own legal structure:

    para:<n>[(<sub>)]   one chunk per paragraph / roman sub-paragraph, e.g. para:4(iii)
    schedule:<item>     one chunk per Schedule row, e.g. schedule:3(b)
    schedule:gc         the General Condition, as its own chunk
    schedule:sc         the Specific Condition
    footnote:<n>        each amendment footnote (who substituted what, and whether it is in force)
    appendix:<n>#<k>    appendices, split by length

Every chunk records the cross-references found in its text (`references`,
`footnote_refs`, `gc_applies`). find_modifiers() follows those links at query
time, which is how the agent reaches the General Condition from a Schedule row
even though the request never mentions it.

Amendments and office memoranda have no stable internal structure, so they are
split by length with overlap and keep their gazette number and date.
"""
import hashlib
import re
from typing import Dict, List, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingest.pdf_text import strip_page_number


CHUNKER_VERSION = "2"

FOOTNOTE_START = re.compile(r"^(\d{1,3})\s+(\S.*)$")
FOOTNOTE_HINT = re.compile(
    r"vide|S\.\s?O\.?|G\.S\.R|dated|substitut|insert|omit|amend|renumber|quashed",
    re.IGNORECASE
)
PARA_HEAD = re.compile(r"^(\d{1,2}A?)\.\s*(\d*)\s+(\S.*)$")
SUB_PARA_HEAD = re.compile(r"^\((i|ii|iii|iiia|iv|v|vi|vii|viii|ix|x)\)\s*(.*)$")
SCHEDULE_ITEM_HEAD = re.compile(r"^(\d{1,2})\s?\(([a-z])\)\s?(\d*)\s*(.*)$")
SCHEDULE_NOISE = re.compile(r"^\(?\d?\)?\s*\(\d\)\s*\(\d\)\s*\(\d\)|^A B$|^Project or Activity Category")
APPENDIX_HEAD = re.compile(r"^APPENDIX\s*[–-]?\s*([IVX]+(?:\s?A)?)")
ITEM_REFERENCE = re.compile(r"\b(\d{1,2})\s?\(([a-z])\)")

GC_APPLIES = re.compile(r"general\s+conditions?\s+(?:as\s+well\s+as\s+specific\s+conditions?\s+)?shall\s+apply", re.I)
GC_NOT_APPLIES = re.compile(r"general\s+conditions?\s+shall\s+not\s+apply", re.I)
SC_APPLIES = re.compile(r"specific\s+conditions?\s+shall\s+apply", re.I)

MAX_PARA_CHARS = 2400

_splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _item_references(text: str) -> List[str]:
    return sorted({f"{m.group(1)}({m.group(2)})" for m in ITEM_REFERENCE.finditer(text)})


def _make_chunk(
    chunk_id: str,
    doc_meta: Dict,
    section: str,
    clause: str,
    text: str,
    page_start: int,
    page_end: int,
    **extra
) -> Dict:
    text = _clean(text)
    chunk = {
        "chunk_id": chunk_id,
        "doc_id": doc_meta["doc_id"],
        "doc": doc_meta["title"],
        "doc_version": f"{doc_meta['number']} ({doc_meta['date']})",
        "doc_type": doc_meta["doc_type"],
        "section": section,
        "clause": clause,
        "text": text,
        "page_start": page_start,
        "page_end": page_end,
        "references": _item_references(text),
        "footnote_refs": [],
        "gc_applies": None,
        "sc_applies": False,
        "in_force": True,
    }
    chunk.update(extra)
    chunk["content_hash"] = _hash(CHUNKER_VERSION, chunk_id, clause, text)
    return chunk


# ---------------------------------------------------------
# CONSOLIDATED NOTIFICATION
# ---------------------------------------------------------

def _split_footnotes(pages: List[str]) -> Tuple[List[Tuple[int, str]], Dict[int, Dict]]:
    """
    Separate body lines from the amendment footnotes printed at the bottom of each page.
    Footnotes are numbered sequentially through the document, which is what lets us tell
    "8 Words substituted vide ..." (footnote) apart from "4 Materials Processing" (Schedule heading).
    """
    body: List[Tuple[int, str]] = []
    footnotes: Dict[int, Dict] = {}
    next_expected = 1

    for page_no, raw in enumerate(pages, start=1):
        current: Optional[int] = None
        for line in strip_page_number(raw).split("\n"):
            match = FOOTNOTE_START.match(line.strip())
            if match:
                number = int(match.group(1))
                if next_expected <= number <= next_expected + 12 and FOOTNOTE_HINT.search(line):
                    current = number
                    footnotes[number] = {"text": match.group(2).strip(), "page": page_no}
                    next_expected = number + 1
                    continue
            if current is not None:
                footnotes[current]["text"] += " " + line.strip()
            else:
                body.append((page_no, line))

    return body, footnotes


def _footnote_refs(digits: str, known: Dict[int, Dict]) -> List[int]:
    """'64' -> [64]; '5657' -> [56, 57]: superscript markers glued to a Schedule item number."""
    if not digits:
        return []
    if len(digits) <= 3 and int(digits) in known:
        return [int(digits)]
    for width in (2, 3):
        if len(digits) % width == 0:
            parts = [int(digits[i:i + width]) for i in range(0, len(digits), width)]
            if all(p in known for p in parts):
                return parts
    return []


def _gc_flag(text: str) -> Optional[bool]:
    if GC_NOT_APPLIES.search(text):
        return False
    if GC_APPLIES.search(text):
        return True
    return None


def _find_line(lines: List[Tuple[int, str]], predicate, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if predicate(lines[index][1].strip()):
            return index
    return len(lines)


def _join(lines: List[Tuple[int, str]]) -> Tuple[str, int, int]:
    text = "\n".join(line for _, line in lines)
    pages = [page for page, _ in lines] or [0]
    return text, min(pages), max(pages)


def _unique_ids(chunks: List[Dict]) -> List[Dict]:
    """para 7 restarts (i), (ii) ... for each stage; suffix repeats so every chunk_id is unique."""
    seen: Dict[str, int] = {}
    for chunk in chunks:
        base = chunk["chunk_id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            chunk["chunk_id"] = f"{base}~{seen[base]}"
            chunk["content_hash"] = _hash(CHUNKER_VERSION, chunk["chunk_id"], chunk["clause"], chunk["text"])
    return chunks


def _chunk_paragraphs(lines, doc_meta) -> List[Dict]:
    chunks = []
    heads = [
        (i, m) for i, (_, line) in enumerate(lines)
        if (m := PARA_HEAD.match(line.strip())) and len(m.group(3)) > 3
    ]
    for n, (start, match) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        para_no = match.group(1)
        title = re.split(r"[:\-–]\s*$", match.group(3).strip())[0].strip(" :-")
        block = lines[start:end]

        subs = [
            (i, m) for i, (_, line) in enumerate(block)
            if (m := SUB_PARA_HEAD.match(line.strip()))
        ]
        if subs:
            pieces = [(f"para:{para_no}", f"Paragraph {para_no} - {title}", block[:subs[0][0]])]
            for k, (sub_start, sub_match) in enumerate(subs):
                sub_end = subs[k + 1][0] if k + 1 < len(subs) else len(block)
                label = sub_match.group(1)
                pieces.append((
                    f"para:{para_no}({label})",
                    f"Paragraph {para_no}({label}) - {title}",
                    block[sub_start:sub_end]
                ))
        else:
            pieces = [(f"para:{para_no}", f"Paragraph {para_no} - {title}", block)]

        for chunk_id, clause, piece in pieces:
            text, p0, p1 = _join(piece)
            if len(text.strip()) < 40:
                continue
            parts = [text] if len(text) <= MAX_PARA_CHARS else _splitter.split_text(text)
            for k, part in enumerate(parts, start=1):
                cid = chunk_id if len(parts) == 1 else f"{chunk_id}#{k}"
                chunks.append(_make_chunk(cid, doc_meta, "Notification Paragraphs", clause, part, p0, p1))

    # The text before paragraph 2 is the operative preamble: listed projects need prior EC
    if heads:
        text, p0, p1 = _join(lines[:heads[0][0]])
        for k, part in enumerate(_splitter.split_text(text), start=1):
            chunks.append(_make_chunk(f"para:preamble#{k}", doc_meta, "Notification Paragraphs",
                                      "Preamble - prior environmental clearance for projects listed in the Schedule",
                                      part, p0, p1))
    return _unique_ids(chunks)


def _chunk_schedule(lines, doc_meta, footnotes) -> List[Dict]:
    chunks = []
    sector_title = ""
    current = None

    def flush():
        if current is None:
            return
        text, p0, p1 = _join(current["lines"])
        item_id = current["item_id"]
        refs = set(current["refs"])
        refs |= {n for n, fn in footnotes.items() if re.search(rf"(?<![\d(]){re.escape(item_id)}", fn["text"])}
        chunks.append(_make_chunk(
            f"schedule:{item_id}",
            doc_meta,
            "Schedule",
            f"Schedule item {item_id} - {current['title']}",
            f"Schedule item {item_id}{current['sector']}: {text}",
            p0, p1,
            footnote_refs=sorted(refs),
            gc_applies=_gc_flag(text),
            sc_applies=bool(SC_APPLIES.search(text)),
        ))

    for page, line in lines:
        stripped = line.strip()
        if not stripped or SCHEDULE_NOISE.search(stripped):
            continue
        item = SCHEDULE_ITEM_HEAD.match(stripped)
        if item and 1 <= int(item.group(1)) <= 10:
            flush()
            item_id = f"{item.group(1)}({item.group(2)})"
            title = re.sub(r"[“”\"]", "", item.group(4)).strip() or item_id
            current = {
                "item_id": item_id,
                "title": title[:80],
                "refs": _footnote_refs(item.group(3), footnotes),
                "sector": f" ({sector_title})" if sector_title.split(" ")[0] == item.group(1) else "",
                "lines": [(page, item.group(4))],
            }
            continue
        heading = re.match(r"^(\d{1,2})\s+([A-Z][A-Za-z ,/&()-]{3,})$", stripped)
        if heading and 1 <= int(heading.group(1)) <= 10:
            flush()
            current = None
            sector_title = f"{heading.group(1)} {heading.group(2).strip()}"
            continue
        if current is not None:
            current["lines"].append((page, line))

    flush()

    # Keep the first occurrence if a row number is repeated across a page break
    seen, unique = set(), []
    for chunk in chunks:
        if chunk["chunk_id"] not in seen:
            seen.add(chunk["chunk_id"])
            unique.append(chunk)
    return unique


def _chunk_conditions(lines, doc_meta, footnotes) -> List[Dict]:
    sc_start = _find_line(lines, lambda s: s.startswith("Specific Condition (SC)"))
    chunks = []
    for chunk_id, clause, block in (
        ("schedule:gc", "General Condition (GC) - note following the Schedule", lines[:sc_start]),
        ("schedule:sc", "Specific Condition (SC) - note following the Schedule", lines[sc_start:]),
    ):
        text, p0, p1 = _join(block)
        refs = [int(n) for n in re.findall(r"\((?:GC|SC)\)\s?(\d{2,3})", text) if int(n) in footnotes]
        chunks.append(_make_chunk(chunk_id, doc_meta, "General Condition" if chunk_id.endswith("gc") else "Specific Condition",
                                  clause, text, p0, p1, footnote_refs=refs))
    return chunks


def _chunk_appendices(lines, doc_meta) -> List[Dict]:
    chunks = []
    heads = [(i, m) for i, (_, line) in enumerate(lines) if (m := APPENDIX_HEAD.match(line.strip()))]
    for n, (start, match) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        name = match.group(1).replace(" ", "")
        text, p0, p1 = _join(lines[start:end])
        for k, part in enumerate(_splitter.split_text(text), start=1):
            chunks.append(_make_chunk(f"appendix:{name}#{k}", doc_meta, "Appendix", f"Appendix {name} (part {k})", part, p0, p1))
    return chunks


def chunk_consolidated(pages: List[str], doc_meta: Dict) -> List[Dict]:
    body, footnotes = _split_footnotes(pages)

    schedule_start = _find_line(body, lambda s: s == "SCHEDULE")
    gc_start = _find_line(body, lambda s: s.startswith("General Condition (GC)"), schedule_start)
    appendix_start = _find_line(body, lambda s: bool(APPENDIX_HEAD.match(s)), gc_start)

    chunks = []
    chunks += _chunk_paragraphs(body[:schedule_start], doc_meta)
    chunks += _chunk_schedule(body[schedule_start:gc_start], doc_meta, footnotes)
    chunks += _chunk_conditions(body[gc_start:appendix_start], doc_meta, footnotes)
    chunks += _chunk_appendices(body[appendix_start:], doc_meta)

    for number, fn in sorted(footnotes.items()):
        text = f"Footnote {number}: {fn['text']}"
        in_force = not re.search(r"quashed|not in force", fn["text"], re.I)
        chunks.append(_make_chunk(f"footnote:{number}", doc_meta, "Footnotes", f"Amendment footnote {number}",
                                  text, fn["page"], fn["page"], in_force=in_force))
    return chunks


# ---------------------------------------------------------
# AMENDMENTS AND OFFICE MEMORANDA
# ---------------------------------------------------------

def chunk_generic(pages: List[str], doc_meta: Dict) -> List[Dict]:
    chunks = []
    section = "Office Memorandum" if doc_meta["doc_type"].startswith("om") else "Gazette Notification"
    counter = 0
    for page_no, page in enumerate(pages, start=1):
        for part in _splitter.split_text(page):
            if len(part.strip()) < 80:
                continue
            counter += 1
            chunks.append(_make_chunk(
                f"{doc_meta['doc_id']}#c{counter:03d}",
                doc_meta,
                section,
                f"{doc_meta['number']} dated {doc_meta['date']} (page {page_no})",
                part,
                page_no,
                page_no,
            ))
    return chunks
