from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------
# INPUT MODELS (built from the validated contract payload)
# ---------------------------------------------------------

class Capacity(BaseModel):
    value: float
    unit: str


class Location(BaseModel):
    state: str
    district: str


class ProtectedArea(BaseModel):
    type: str
    name: Optional[str] = None
    distance_km: Optional[float] = None
    basis: Optional[str] = "surveyed"  # "surveyed" or "estimated"


class ProjectRequest(BaseModel):
    run_id: Optional[str] = None
    correlation_id: Optional[str] = None

    description: str
    project_name: Optional[str] = None
    activity: Optional[str] = "new"
    sector_description: Optional[str] = None
    sector_hint: Optional[str] = None

    capacity: Optional[Capacity] = None
    area_ha: Optional[float] = None
    project_area_ha: Optional[float] = None

    location: Optional[Location] = None
    nearest_protected_area: Optional[ProtectedArea] = None

    proximity: Optional[List[Dict[str, Any]]] = None
    in_critically_polluted_area: Optional[bool] = False
    eco_sensitive_zone: Optional[str] = None


# ---------------------------------------------------------
# RETRIEVED KNOWLEDGE
# ---------------------------------------------------------

class Chunk(BaseModel):
    chunk_id: str
    doc: str
    doc_version: str
    section: str
    clause: str
    text: str
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------
# EXTRACTOR OUTPUT
# ---------------------------------------------------------

class ExtractedEntities(BaseModel):
    sector: Optional[str] = None
    capacity_value: Optional[float] = None
    capacity_unit: Optional[str] = None
    area_ha: Optional[float] = None

    state: Optional[str] = None
    district: Optional[str] = None

    protected_area_type: Optional[str] = None
    protected_area_name: Optional[str] = None
    protected_area_distance_km: Optional[float] = None
    proximity_basis: str = "surveyed"

    interstate_distance_km: Optional[float] = None
    eco_sensitive_distance_km: Optional[float] = None
    in_critically_polluted_area: bool = False
    eco_sensitive_zone: Optional[str] = None

    confidence: float = 0.0
    missing_fields: List[str] = Field(default_factory=list)


# ---------------------------------------------------------
# SCREENER OUTPUT (hand-off contract to the Verifier)
# ---------------------------------------------------------

class Citation(BaseModel):
    chunk_id: str
    quote: str = ""


class DraftDetermination(BaseModel):
    decision: Literal["determination", "escalate"] = "determination"

    category: Optional[Literal["A", "B", "NO_CLEARANCE"]] = None

    route: Optional[
        Literal[
            "no_clearance",
            "category_b_state",
            "category_a_central",
            "escalate_to_human"
        ]
    ] = None

    schedule_item: Optional[str] = None
    basis: str = ""
    citations: List[Citation] = Field(default_factory=list)
    modifiers_checked: List[str] = Field(default_factory=list)

    escalation_reason_code: Optional[str] = None
    escalation_detail: Optional[str] = None

    produced_by: str = "screener_llm"  # or "rule_engine" on the degraded path

    @property
    def cited_chunk_ids(self) -> List[str]:
        return [c.chunk_id for c in self.citations]


# ---------------------------------------------------------
# VERIFIER OUTPUT
# ---------------------------------------------------------

class VerificationResult(BaseModel):
    passed: bool = False

    verdict: Literal[
        "pass",
        "retry",
        "escalate"
    ] = "retry"

    checks: List[str] = Field(default_factory=list)

    reason: Optional[str] = None

    # What the Screener should do differently on a retry
    feedback: Optional[str] = None


# ---------------------------------------------------------
# ESCALATION
# ---------------------------------------------------------

class Escalation(BaseModel):
    reason_code: str
    detail: str


# ---------------------------------------------------------
# MAIN LANGGRAPH STATE
# ---------------------------------------------------------

class AgentState(BaseModel):

    run_id: Optional[str] = None
    correlation_id: Optional[str] = None

    # Original validated request
    request: ProjectRequest

    # Extractor output
    extracted_entities: Optional[ExtractedEntities] = None

    # Chunks retrieved during run (citations must resolve to these)
    retrieved_chunks: Dict[str, Chunk] = Field(default_factory=dict)

    # Screener output
    draft_answer: Optional[DraftDetermination] = None

    # Verifier output
    verification: Optional[VerificationResult] = None

    # Final run state
    status: Literal[
        "running",
        "answered",
        "escalated",
        "failed"
    ] = "running"

    escalation: Optional[Escalation] = None

    # "agentic" normally; "degraded" when the provider is unavailable and the
    # rule engine produced a provisional opinion instead
    mode: Literal["agentic", "degraded"] = "agentic"
    llm_unavailable: bool = False
    provisional_opinion: Optional[DraftDetermination] = None

    # Counters required for bounded agent execution (A1)
    steps: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    screener_attempts: int = 0
    verification_retries: int = 0

    # Timing
    start_time: Optional[float] = None
    deadline: Optional[float] = None

    # Prompt tracking (L2)
    prompt_version: str = "v1"

    # LLM usage tracking, totals and per step (L5)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    usage_by_step: List[Dict[str, Any]] = Field(default_factory=list)

    # Additional internal information
    metadata: Dict[str, Any] = Field(default_factory=dict)
