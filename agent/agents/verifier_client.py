"""
Hand-off from the Screener to the Verifier.

With VERIFIER_URL set (Docker Compose), the Verifier is a separate service: the worker
POSTs the run state, the verifier service runs verify_draft with its own model budget
and returns the updated state. Without it (local single-process mode) the same function
runs in-process.

If the verifier service cannot be reached, the run is escalated with
VERIFIER_UNAVAILABLE: an unverified draft is never returned.
"""
import time

import httpx

from agent.agents.verifier import verify_draft
from agent.config import settings
from agent.resilience.retry import retry_with_backoff
from agent.state import AgentState, VerificationResult
from observability.recorder import get_recorder
from observability.tracing import inject_context


VERIFIER_TIMEOUT_SECONDS = 60.0


def _remote_verify(state: AgentState) -> AgentState:
    # Wait as long as the run has left (the verifier enforces the same deadline itself).
    # Only a failed connection is retried: re-running a slow verification would double its cost.
    timeout = VERIFIER_TIMEOUT_SECONDS
    if state.deadline:
        timeout = max(5.0, state.deadline - time.time() + 5.0)

    def call():
        try:
            response = httpx.post(
                settings.verifier_url.rstrip("/") + "/v1/verify",
                json=state.model_dump(mode="json"),
                headers=inject_context(),
                timeout=httpx.Timeout(timeout, connect=5.0),
            )
        except httpx.ConnectError as error:
            raise TimeoutError(f"verifier unreachable: {error}") from error
        if response.status_code >= 500:
            raise TimeoutError(f"verifier HTTP {response.status_code}")
        response.raise_for_status()
        return response.json()

    returned = AgentState(**retry_with_backoff(call, max_retries=2))
    return returned


def run_verifier(state: AgentState) -> AgentState:
    if not settings.verifier_url:
        return verify_draft(state)
    try:
        return _remote_verify(state)
    except Exception as error:
        get_recorder().event("verifier_unavailable", agent="verifier", error=str(error)[:300])
        out_of_time = bool(state.deadline) and time.time() >= state.deadline
        state.verification = VerificationResult(
            passed=False, verdict="escalate", reason="LIMIT_WALL_CLOCK" if out_of_time else "VERIFIER_UNAVAILABLE",
            checks=[f"FAIL verifier service unreachable: {str(error)[:200]}"],
        )
        return state
