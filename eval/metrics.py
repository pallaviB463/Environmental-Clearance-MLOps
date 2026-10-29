"""
Evaluation metrics (Requirement L3). How each one is computed:

R = passages retrieved by tools during the run (the only text a citation may point to)
C = citations in the final draft, each (chunk_id, quote)
S = the scenario's supporting passages (chunk ids listed in eval/scenarios.json)

groundedness       mean over citations of [chunk_id in R and quote found verbatim in that
                   passage]. Citation-level: is each piece of evidence real?
context_relevance  |R ∩ (S ∪ cited)| / |R|. Share of retrieved passages that are either a
                   reference supporting passage or were used as evidence.
context_recall     |S ∩ R| / |S|. Did retrieval reach the passages the answer depends on?
                   (For PS 4.1 this is whether the General Condition was retrieved.)
faithfulness       run-level 0/1: the final draft passes the Verifier's deterministic checks
                   when re-run independently (citations resolve, quotes verbatim, category and
                   route agree, Schedule row cited, General Condition applied where its
                   distance is met). With --judge llm, also requires an LLM judge to find the
                   basis entailed by the cited passages.
hallucination_rate share of runs with at least one citation that does not resolve to retrieved
                   text or whose quote is not in the passage, i.e. fabricated evidence.
route_accuracy     share of scenarios whose final route (or escalation) matches the expected one.

The reference-free subset (no S needed) is used to score sampled live runs (L6).
"""
from typing import Dict, List, Optional

from agent.state import AgentState


def _citation_ok(state: AgentState, chunk_id: str, quote: str) -> bool:
    from agent.agents.verifier import quote_found
    chunk = state.retrieved_chunks.get(chunk_id)
    return chunk is not None and quote_found(quote, chunk.text)


def groundedness(state: AgentState) -> Optional[float]:
    draft = state.draft_answer
    if draft is None or not draft.citations:
        return None
    ok = [_citation_ok(state, c.chunk_id, c.quote) for c in draft.citations]
    return sum(ok) / len(ok)


def has_fabricated_evidence(state: AgentState) -> bool:
    draft = state.draft_answer
    if draft is None:
        return False
    return any(not _citation_ok(state, c.chunk_id, c.quote) for c in draft.citations)


def context_relevance(state: AgentState, supporting: List[str]) -> Optional[float]:
    retrieved = set(state.retrieved_chunks)
    if not retrieved:
        return None
    cited = set(state.draft_answer.cited_chunk_ids) if state.draft_answer else set()
    return len(retrieved & (set(supporting) | cited)) / len(retrieved)


def context_recall(state: AgentState, supporting: List[str]) -> Optional[float]:
    if not supporting:
        return None
    return len(set(supporting) & set(state.retrieved_chunks)) / len(supporting)


def faithful(state: AgentState) -> Optional[bool]:
    from agent.agents.verifier import deterministic_checks
    draft = state.draft_answer
    if draft is None or draft.decision == "escalate":
        return None
    return deterministic_checks(state, draft).verdict == "pass"


def reference_free_scores(state: AgentState) -> Dict[str, Optional[float]]:
    """Scores computable on a live run, with no expected answer."""
    retrieved = set(state.retrieved_chunks)
    cited = set(state.draft_answer.cited_chunk_ids) if state.draft_answer else set()
    is_faithful = faithful(state)
    return {
        "groundedness": groundedness(state),
        "context_utilisation": (len(retrieved & cited) / len(retrieved)) if retrieved else None,
        "faithfulness": None if is_faithful is None else float(is_faithful),
        "fabricated_evidence": float(has_fabricated_evidence(state)),
    }
