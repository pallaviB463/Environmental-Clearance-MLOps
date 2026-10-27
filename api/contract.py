from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


VALID_SECTORS = {
    "cement", "thermal_power", "power", "mining",
    "construction", "river_valley", "industrial",
    "crz_coastal", "infrastructure"
}

VALID_UNITS = {
    "million_tonnes_per_annum", "mtpa", "tpd", "tpa",
    "mw", "hectares", "ha", "sq_metres", "sqm"
}

VALID_PROXIMITY_FEATURES = {
    "protected_area", "national_park", "wildlife_sanctuary",
    "critically_polluted_area", "eco_sensitive_zone",
    "interstate_boundary", "international_boundary"
}


class CapacityInput(BaseModel):
    value: float = Field(..., description="Project capacity numerical value")
    unit: str = Field(..., description="Capacity unit (e.g., million_tonnes_per_annum, MW, TPD)")

    @model_validator(mode="after")
    def validate_capacity_range_and_unit(self):
        if self.value <= 0:
            raise ValueError(f"Capacity value must be positive (received {self.value}).")
        clean_unit = self.unit.strip().lower()
        if clean_unit not in VALID_UNITS:
            raise ValueError(f"Invalid capacity unit '{self.unit}'. Valid units: {sorted(VALID_UNITS)}")
        return self


class LocationInput(BaseModel):
    state: str = Field(..., min_length=2, description="Indian State")
    district: str = Field(..., min_length=2, description="District")


class ProximityItem(BaseModel):
    feature: str = Field(..., description="Feature type (e.g., protected_area, interstate_boundary)")
    subtype: Optional[str] = None
    name: Optional[str] = None
    distance_km: float = Field(..., description="Distance in kilometres")
    basis: Optional[str] = Field("surveyed", description="'surveyed' or 'estimated'")

    @model_validator(mode="after")
    def validate_proximity_range(self):
        if self.distance_km < 0:
            raise ValueError(f"Proximity distance cannot be negative (received {self.distance_km} km).")
        if self.distance_km > 500:
            raise ValueError(f"Proximity distance exceeds plausible screening range (received {self.distance_km} km).")
        return self


class ScreeningSubmission(BaseModel):
    project_name: Optional[str] = "EIA Clearance Project"
    activity: Optional[str] = "new"
    sector_description: Optional[str] = None
    sector_hint: Optional[str] = None

    description: str = Field(..., min_length=5, description="Full narrative description of the proposed project")

    capacity: Optional[CapacityInput] = None
    project_area_ha: Optional[float] = Field(None, description="Total project area in hectares")
    area_ha: Optional[float] = None

    location: Optional[LocationInput] = None
    proximity: Optional[List[ProximityItem]] = Field(default_factory=list)

    in_critically_polluted_area: Optional[bool] = False
    eco_sensitive_zone: Optional[str] = None

    @model_validator(mode="after")
    def cross_field_validations(self):
        # Cross-field: Project area cannot be negative
        area = self.project_area_ha or self.area_ha
        if area is not None and area <= 0:
            raise ValueError(f"Project area must be strictly positive (received {area} ha).")

        # Cross-field: Cement capacity unit sanity
        desc = f"{self.description} {self.sector_description or ''} {self.sector_hint or ''}".lower()
        if "cement" in desc and self.capacity:
            unit = self.capacity.unit.lower()
            if unit in ["mw", "sq_metres", "sqm"]:
                raise ValueError(f"Cross-field mismatch: unit '{self.capacity.unit}' is invalid for cement plants.")

        return self
