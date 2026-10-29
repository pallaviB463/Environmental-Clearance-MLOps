"""
Optional LLM judge for faithfulness (`--judge llm`): is the draft's basis entailed by the
cited passages? Uses the same gateway (and so the same provider, timeouts and breaker).
"""
import json

from agent.llm.client import LLMUnavailableError
from agent.llm.gateway import get_gateway
from agent.llm.json_extract import extract_json_object
from agent.state import AgentState


JUDGE_PROMPT = """AGENT: judge
You check whether a conclusion follows from legal passages. Answer only from the passages.
Reply with only JSON: {"entailed": true or false, "reason": "one sentence"}"""


def judge_entailment(state: AgentState) -> bool:
    draft = state.draft_answer
    passages = {c.chunk_id: state.retrieved_chunks[c.chunk_id].text
                for c in draft.citations if c.chunk_id in state.retrieved_chunks}
    facts = state.extracted_entities.model_dump(exclude_none=True) if state.extracted_entities else {}
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": json.dumps({"facts": facts, "conclusion": draft.basis,
                                                 "category": draft.category, "passages": passages})},
    ]
    try:
        response = get_gateway().complete(messages, None, agent="judge", step="eval.judge", prompt_version="judge")
    except LLMUnavailableError:
        return False
    verdict = extract_json_object(response["content"], expected_keys=("entailed",))
    return bool(verdict and verdict.get("entailed"))
