"""
Tools the agents may choose to call (Requirement A1). Retrieval is a tool here, not a
fixed pipeline stage: the model decides when to search, what to search for, and
whether to follow a cross-reference.

    search_corpus(query, section?, k?)   semantic search over the FAISS index
    get_clause(chunk_id)                 exact lookup of a provision by identifier
    find_modifiers(chunk_id)             provisions that can change how a provision applies
    get_request_fields(fields?)          the validated request's own fields

Every call is bounded by a timeout and the run's tool-call budget, recorded in the run
trace (arguments, returned chunk ids, latency), and every returned passage is added to
the run's retrieved set: the only passages a citation may point to (A3).
"""
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional

from agent.config import settings
from agent.redis_client import get_redis
from agent.resilience.timeouts import run_with_timeout
from agent.retrieval.store import get_store
from agent.state import AgentState, Chunk
from observability.metrics import AGENT_STEP_SECONDS, TOOL_CALLS_TOTAL
from observability.recorder import get_recorder


PASSAGE_CHARS = 1800

TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_corpus": {
        "type": "function",
        "function": {
            "name": "search_corpus",
            "description": (
                "Semantic search over the EIA Notification 2006 (consolidated to March 2025), its "
                "amendments and office memoranda. Returns passages with chunk ids and similarity scores. "
                "Use section='Schedule' to search only Schedule rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, in plain words"},
                    "section": {
                        "type": "string",
                        "enum": ["Schedule", "General Condition", "Notification Paragraphs", "Footnotes",
                                 "Gazette Notification", "Office Memorandum", "Appendix"],
                        "description": "Optional: restrict to one part of the corpus",
                    },
                    "k": {"type": "integer", "minimum": 1, "maximum": 8, "description": "Passages to return (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    "get_clause": {
        "type": "function",
        "function": {
            "name": "get_clause",
            "description": (
                "Fetch one provision by its chunk id, e.g. 'schedule:3(b)', 'schedule:gc', "
                "'para:4(iii)', 'footnote:93'."
            ),
            "parameters": {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
            },
        },
    },
    "find_modifiers": {
        "type": "function",
        "function": {
            "name": "find_modifiers",
            "description": (
                "Given a provision's chunk id (usually a Schedule row), return the provisions that can "
                "change how it applies: the General or Specific Condition if the row says it applies, "
                "amendment footnotes (with whether they are in force), the routing paragraphs, and later "
                "notifications or office memoranda that cite the same item."
            ),
            "parameters": {
                "type": "object",
                "properties": {"chunk_id": {"type": "string"}},
                "required": ["chunk_id"],
            },
        },
    },
    "get_request_fields": {
        "type": "function",
        "function": {
            "name": "get_request_fields",
            "description": "Return the validated fields of the project request (capacity, area, location, proximity).",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {"type": "array", "items": {"type": "string"},
                               "description": "Optional subset of field names"},
                },
            },
        },
    },
}


class ToolBudgetExceeded(RuntimeError):
    pass


def _passage(chunk: Chunk) -> Dict[str, Any]:
    meta = chunk.metadata
    view = {
        "chunk_id": chunk.chunk_id,
        "section": chunk.section,
        "clause": chunk.clause,
        "source": chunk.doc_version,
        "score": chunk.score,
        "text": chunk.text[:PASSAGE_CHARS] + (" ..." if len(chunk.text) > PASSAGE_CHARS else ""),
    }
    if meta.get("gc_applies") is not None:
        view["general_condition_applies"] = meta["gc_applies"]
    if meta.get("in_force") is False:
        view["in_force"] = False
    return view


class ToolBox:

    def __init__(self, state: AgentState, agent: str, enabled: Optional[List[str]] = None):
        self.state = state
        self.agent = agent
        self.store = get_store()
        self.enabled = enabled or list(TOOL_SCHEMAS)
        self.functions: Dict[str, Callable[..., Any]] = {
            "search_corpus": self.search_corpus,
            "get_clause": self.get_clause,
            "find_modifiers": self.find_modifiers,
            "get_request_fields": self.get_request_fields,
        }

    def schemas(self) -> List[Dict[str, Any]]:
        return [TOOL_SCHEMAS[name] for name in self.enabled]

    # -----------------------------------------------------
    # Dispatch
    # -----------------------------------------------------

    def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        recorder = get_recorder()

        if name not in self.enabled:
            TOOL_CALLS_TOTAL.labels(agent=self.agent, tool=name, outcome="unknown_tool").inc()
            recorder.event("tool_call", agent=self.agent, tool=name, arguments=arguments, outcome="unknown_tool")
            return {"error": f"Unknown tool '{name}'. Available: {self.enabled}"}

        if self.state.tool_calls >= settings.max_tool_calls:
            raise ToolBudgetExceeded(f"tool-call budget of {settings.max_tool_calls} exhausted")

        self.state.tool_calls += 1
        started = time.time()
        try:
            result = run_with_timeout(
                lambda: self.functions[name](**arguments),
                timeout_seconds=settings.tool_timeout_seconds,
            )
            outcome = "ok"
        except TypeError as error:
            result, outcome = {"error": f"bad arguments for {name}: {error}"}, "bad_arguments"
        except TimeoutError:
            result, outcome = {"error": f"{name} timed out after {settings.tool_timeout_seconds}s"}, "timeout"
        except Exception as error:
            result, outcome = {"error": f"{name} failed: {error}"}, "error"

        latency = time.time() - started
        TOOL_CALLS_TOTAL.labels(agent=self.agent, tool=name, outcome=outcome).inc()
        AGENT_STEP_SECONDS.labels(agent=self.agent, kind=f"tool:{name}").observe(latency)

        returned = [p["chunk_id"] for p in result.get("passages", [])] if isinstance(result, dict) else []
        recorder.event(
            "tool_call", agent=self.agent, tool=name, arguments=arguments, outcome=outcome,
            latency_ms=round(latency * 1000, 1), returned_chunk_ids=returned,
            returned_scores=[p.get("score") for p in result.get("passages", [])] if isinstance(result, dict) else [],
            cache_hit=result.get("cache_hit") if isinstance(result, dict) else None,
        )
        return result

    def _remember(self, chunks: List[Chunk]) -> None:
        for chunk in chunks:
            self.state.retrieved_chunks[chunk.chunk_id] = chunk

    # -----------------------------------------------------
    # Tools
    # -----------------------------------------------------

    def search_corpus(self, query: str, section: Optional[str] = None, k: int = 5) -> Dict[str, Any]:
        k = max(1, min(int(k), 8))
        cache_key = "eia:retrieval:" + hashlib.sha256(
            json.dumps([query.strip().lower(), section, k, self.store.index_version]).encode()
        ).hexdigest()

        # Retrieval cache (D7): identical searches against the same index version skip
        # the embedding model and FAISS
        cached_ids = None
        redis = get_redis()
        if settings.cache_enabled and redis is not None:
            try:
                raw = redis.get(cache_key)
                cached_ids = json.loads(raw) if raw else None
            except Exception:
                cached_ids = None

        if cached_ids is not None:
            chunks = [c for c in (self.store.to_chunk(cid, score) for cid, score in cached_ids) if c]
        else:
            chunks = self.store.search(query, k=k, section=section)
            if settings.cache_enabled and redis is not None:
                try:
                    redis.setex(cache_key, settings.run_cache_ttl_seconds,
                                json.dumps([[c.chunk_id, c.score] for c in chunks]))
                except Exception:
                    pass

        self._remember(chunks)
        return {
            "query": query,
            "cache_hit": cached_ids is not None,
            "best_score": chunks[0].score if chunks else 0.0,
            "passages": [_passage(c) for c in chunks],
        }

    def get_clause(self, chunk_id: str) -> Dict[str, Any]:
        chunk = self.store.get(chunk_id)
        if chunk is None:
            return {"error": f"No provision with chunk id '{chunk_id}'.", "passages": []}
        self._remember([chunk])
        return {"passages": [_passage(chunk)]}

    def find_modifiers(self, chunk_id: str) -> Dict[str, Any]:
        found = self.store.modifiers(chunk_id)
        if not found and self.store.get(chunk_id) is None:
            return {"error": f"No provision with chunk id '{chunk_id}'.", "passages": []}
        self._remember([chunk for chunk, _ in found])
        return {
            "provision": chunk_id,
            "passages": [{**_passage(chunk), "relation": relation} for chunk, relation in found],
            "note": "No modifying provisions recorded." if not found else "",
        }

    def get_request_fields(self, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        data = self.state.request.model_dump(exclude={"run_id", "correlation_id"}, exclude_none=True)
        if fields:
            data = {key: value for key, value in data.items() if key in fields}
        return {"fields": data}
