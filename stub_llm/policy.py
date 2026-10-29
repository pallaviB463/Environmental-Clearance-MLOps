"""
Scripted behaviour of the stub LLM (Requirement D6: the LLM is replaced by a stub that
returns fixed responses after a realistic delay, so load tests measure our system and
not the provider's rate limits).

It speaks the OpenAI Chat Completions format, including tool calls, and follows the
same tool sequence a well-behaved model would:

    screener:  get_request_fields -> search_corpus -> find_modifiers -> (get_clause ...) -> final JSON
    verifier:  final JSON verdict

The final screener answer is composed by the rule engine, so responses are plausible.

Without the find_modifiers tool the stub behaves like a naive single-pass RAG model: it
answers from the Schedule row alone and ignores the General Condition (the PS 4.1 failure).
When the Verifier rejects that draft, the retry prompt says so and the stub changes strategy
and fetches the provisions named in the feedback. This makes the Verifier's catch-and-retry
reproducible for demo item 6 and for the `--change no_find_modifiers` evaluation.
"""
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agent.fallback import rules
from agent.state import ExtractedEntities


def _block(text: str, tag: str) -> Optional[Dict]:
    match = re.search(rf"<{tag}>\s*(\{{.*?\}})\s*</{tag}>", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _tool_call(name: str, arguments: Dict) -> Dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _history(messages: List[Dict]) -> Tuple[List[str], set]:
    """Names of tools already called, and chunk ids already returned by tools."""
    called, seen_ids = [], set()
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                called.append(call["function"]["name"])
        if message.get("role") == "tool":
            seen_ids.update(re.findall(r'"chunk_id":\s*"([^"]+)"', message.get("content") or ""))
    return called, seen_ids


class _RowOnlyStore:
    """What a model that never looks past the Schedule row 'knows': no modifying provisions."""

    def __init__(self, store):
        self.store = store

    def get(self, chunk_id):
        return self.store.get(chunk_id)

    def modifiers(self, chunk_id):
        return []


def _screener_turn(messages: List[Dict], tools: List[Dict], store, tool_choice: str = "auto") -> Dict:
    user_text = next((m["content"] for m in messages if m["role"] == "user"), "")
    project = _block(user_text, "project_data") or {}
    entities = ExtractedEntities(**(_block(user_text, "extracted_entities") or {}))
    called, seen_ids = _history(messages)

    available = {t["function"]["name"] for t in tools or []}
    retry = "REJECTED by the Verifier" in user_text
    naive = "find_modifiers" not in available and not retry

    sector = rules.resolve_sector(entities.sector)
    sector_rules = rules.THRESHOLDS["sectors"].get(sector or "", {})

    if tool_choice != "none" and "get_request_fields" not in called:
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("get_request_fields", {})]}

    if tool_choice != "none" and "search_corpus" not in called:
        query = f"{project.get('sector_description') or entities.sector or project.get('description', '')} Schedule item category threshold"
        return {"role": "assistant", "content": "",
                "tool_calls": [_tool_call("search_corpus", {"query": query[:200], "section": "Schedule"})]}

    row_id = f"schedule:{sector_rules['item']}" if sector_rules else None
    if tool_choice != "none" and row_id and "find_modifiers" in available and "find_modifiers" not in called:
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("find_modifiers", {"chunk_id": row_id})]}

    if naive:
        draft, _ = rules.screen(entities, project.get("description", ""), _RowOnlyStore(store))
    else:
        draft, _ = rules.screen(entities, project.get("description", ""), store)
    if tool_choice == "none":
        return {"role": "assistant", "content": json.dumps(draft.model_dump(exclude={"produced_by"}))}
    missing = [c.chunk_id for c in draft.citations if c.chunk_id not in seen_ids]
    if retry:
        named = set(m.rstrip(".") for m in re.findall(r"\b((?:schedule|para|footnote):[\w().~#-]+)", user_text.split("Previous draft:")[0]))
        if "general condition" in user_text.lower():
            named.add("schedule:gc")
        missing += sorted(cid for cid in named if cid not in seen_ids and cid not in missing)
    if missing:
        return {"role": "assistant", "content": "",
                "tool_calls": [_tool_call("get_clause", {"chunk_id": cid}) for cid in missing]}

    answer = draft.model_dump(exclude={"produced_by"})
    return {"role": "assistant", "content": json.dumps(answer)}


def _verifier_turn(messages: List[Dict]) -> Dict:
    verdict = {"supported": True, "unsupported_claims": [], "ignored_provisions": [],
               "comment": "Stub verifier: deterministic checks decide."}
    return {"role": "assistant", "content": json.dumps(verdict)}


def respond(messages: List[Dict[str, Any]], store, tools: Optional[List[Dict]] = None,
            tool_choice: str = "auto") -> Tuple[Dict, int, int]:
    system = messages[0].get("content", "") if messages else ""
    if "AGENT: verifier" in system:
        message = _verifier_turn(messages)
    else:
        message = _screener_turn(messages, tools or [], store, tool_choice)

    prompt_chars = sum(len(json.dumps(m)) for m in messages)
    completion_chars = len(json.dumps(message))
    return message, prompt_chars // 4, completion_chars // 4
