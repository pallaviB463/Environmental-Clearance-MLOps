from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------
# INPUT MODELS (Published Data Contract D1 / F1)
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
    run_id: str
    correlation_id: str

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
    in_critically_polluted_area: bool = False
    eco_sensitive_zone: Optional[str] = None

    confidence: float = 0.0
    missing_fields: List[str] = Field(default_factory=list)


# ---------------------------------------------------------
# ANALYST OUTPUT
# ---------------------------------------------------------

class DraftDetermination(BaseModel):
    category: Optional[Literal["A", "B", "NO_CLEARANCE"]] = None

    route: Optional[
        Literal[
            "no_clearance",
            "category_b_state",
            "category_a_central",
            "escalate_to_human"
        ]
    ] = None

    basis: str = ""

    cited_chunk_ids: List[str] = Field(default_factory=list)


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

    # Original validated request
    request: ProjectRequest

    # Extractor output
    extracted_entities: Optional[ExtractedEntities] = None

    # Chunks retrieved during run
    retrieved_chunks: Dict[str, Chunk] = Field(default_factory=dict)

    # Analyst output
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

    # Counters required for bounded agent execution
    steps: int = 0
    tool_calls: int = 0
    verification_retries: int = 0

    # Timing
    start_time: Optional[float] = None

    # Prompt tracking
    prompt_version: str = "v1"

    # LLM usage tracking
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    # Additional internal information
    metadata: Dict[str, Any] = Field(default_factory=dict)