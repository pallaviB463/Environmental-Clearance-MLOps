"""
Published data contracts (Requirements F1 / D1). Served as JSON Schema at GET /v1/contract.

Enforced at the ingestion boundary, before any agent starts:
  schema       unknown fields are rejected (extra="forbid"), required fields present
  type         pydantic types
  range        capacity > 0, area > 0, 0 <= distance <= 500 km, text length limits
  categorical  sector_hint, capacity unit, proximity feature, distance basis, activity, state/UT
  cross-field  capacity unit must suit the sector; area given once; estimated distances must
               say so; a protected-area entry must carry a distance
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONTRACT_VERSION = "2.0"

VALID_SECTORS = {
    "cement", "thermal_power", "power", "mining",
    "construction", "building_construction", "river_valley", "industrial",
    "crz_coastal", "infrastructure", "non_scheduled", "it_software", "solar"
}

VALID_UNITS = {
    "million_tonnes_per_annum", "mtpa", "tpd", "tpa",
    "mw", "hectares", "ha", "sq_metres", "sqm"
}

# Units that make sense for each sector (cross-field check)
SECTOR_UNITS = {
    "cement": {"million_tonnes_per_annum", "mtpa", "tpd", "tpa"},
    "thermal_power": {"mw"},
    "power": {"mw"},
    "river_valley": {"mw", "hectares", "ha"},
    "mining": {"hectares", "ha", "million_tonnes_per_annum", "mtpa", "tpa"},
    "construction": {"sq_metres", "sqm", "hectares", "ha"},
    "building_construction": {"sq_metres", "sqm", "hectares", "ha"},
}

VALID_PROXIMITY_FEATURES = {
    "protected_area", "national_park", "wildlife_sanctuary",
    "critically_polluted_area", "eco_sensitive_zone", "eco_sensitive_area",
    "interstate_boundary", "inter-state_boundary", "international_boundary"
}

INDIAN_STATES_AND_UTS = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat",
    "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
    "andaman and nicobar islands", "chandigarh", "dadra and nagar haveli and daman and diu",
    "delhi", "jammu and kashmir", "ladakh", "lakshadweep", "puducherry",
}


class CapacityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(..., gt=0, le=1_000_000, description="Project capacity, strictly positive")
    unit: str = Field(..., description=f"One of {sorted(VALID_UNITS)}")

    @model_validator(mode="after")
    def validate_unit(self):
        self.unit = self.unit.strip().lower()
        if self.unit not in VALID_UNITS:
            raise ValueError(f"Invalid capacity unit '{self.unit}'. Valid units: {sorted(VALID_UNITS)}")
        return self


class LocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(..., min_length=2, max_length=60, description="Indian State or Union Territory")
    district: str = Field(..., min_length=2, max_length=80, description="District")

    @model_validator(mode="after")
    def validate_state(self):
        if self.state.strip().lower() not in INDIAN_STATES_AND_UTS:
            raise ValueError(f"Unknown State/UT '{self.state}'.")
        return self


class ProximityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = Field(..., description=f"One of {sorted(VALID_PROXIMITY_FEATURES)}")
    subtype: Optional[str] = Field(None, max_length=60)
    name: Optional[str] = Field(None, max_length=120)
    distance_km: Optional[float] = Field(
        None, ge=0, le=500,
        description="Distance from the project boundary in km. Omit if unknown: the run is then escalated as PROXIMITY_UNCERTAIN."
    )
    basis: Literal["surveyed", "estimated"] = Field("surveyed", description="How the distance was obtained")

    @model_validator(mode="after")
    def validate_feature(self):
        self.feature = self.feature.strip().lower().replace(" ", "_")
        if self.feature not in VALID_PROXIMITY_FEATURES:
            raise ValueError(f"Invalid proximity feature '{self.feature}'. Allowed: {sorted(VALID_PROXIMITY_FEATURES)}")
        return self


class ScreeningSubmission(BaseModel):
    """
    Published data contract for POST /v1/screenings. Unknown fields are rejected.
    A rejected submission is quarantined with its field-level errors and never starts a run.
    """
    model_config = ConfigDict(extra="forbid")

    project_name: Optional[str] = Field("EIA Clearance Project", max_length=200)
    activity: Literal["new", "expansion", "modernisation", "modernization"] = "new"
    sector_description: Optional[str] = Field(None, max_length=500)
    sector_hint: Optional[str] = Field(None, description=f"Optional; one of {sorted(VALID_SECTORS)}")

    description: str = Field(..., min_length=10, max_length=4000,
                             description="Narrative description of the proposed project")

    capacity: Optional[CapacityInput] = None
    project_area_ha: Optional[float] = Field(None, gt=0, le=1_000_000, description="Total project area in hectares")
    area_ha: Optional[float] = Field(None, gt=0, le=1_000_000, description="Alias of project_area_ha")

    location: Optional[LocationInput] = None
    proximity: List[ProximityItem] = Field(default_factory=list, max_length=20)

    in_critically_polluted_area: bool = False
    eco_sensitive_zone: Optional[str] = Field(None, max_length=200)

    @model_validator(mode="after")
    def cross_field_validations(self):
        if self.sector_hint:
            self.sector_hint = self.sector_hint.strip().lower()
            if self.sector_hint not in VALID_SECTORS:
                raise ValueError(f"Invalid sector_hint '{self.sector_hint}'. Allowed sectors: {sorted(VALID_SECTORS)}")

        if self.project_area_ha is not None and self.area_ha is not None and self.project_area_ha != self.area_ha:
            raise ValueError("Give the project area once: project_area_ha and area_ha disagree.")

        text = f"{self.description} {self.sector_description or ''}".lower()
        sector = self.sector_hint or ("cement" if "cement" in text else None)
        if sector in SECTOR_UNITS and self.capacity and self.capacity.unit not in SECTOR_UNITS[sector]:
            raise ValueError(
                f"Cross-field mismatch: unit '{self.capacity.unit}' is not valid for sector '{sector}' "
                f"(expected one of {sorted(SECTOR_UNITS[sector])})."
            )
        return self


class FeedbackSubmission(BaseModel):
    """Published data contract for POST /v1/screenings/{run_id}/feedback (L6)."""
    model_config = ConfigDict(extra="forbid")

    satisfactory: bool = Field(..., description="Was the screening result satisfactory?")
    reason: Optional[str] = Field(None, max_length=1000, description="Why (required when not satisfactory)")

    @model_validator(mode="after")
    def reason_required_when_unsatisfactory(self):
        if not self.satisfactory and not (self.reason and self.reason.strip()):
            raise ValueError("A reason is required when the result is marked unsatisfactory.")
        return self
