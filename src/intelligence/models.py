"""Input Intelligence models — structured representation for arbitrary input.

Flow position:
  User / External Input → Input Intelligence (Grok / Fallback) → Validation Gate
  → InputEnvelope → FLOWSHIELD State Core
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class InputIntent(StrEnum):
    """Classification of external natural-language input."""

    INCIDENT = "incident"                       # New or reported incident
    STATE_UPDATE = "state_update"               # Environmental / sensor reading
    RESOURCE_UPDATE = "resource_update"         # Asset availability or status change
    SIMULATION = "simulation"                   # What-if scenario request
    QUERY = "query"                             # Operational question / status inquiry
    UNSUPPORTED = "unsupported"                 # Outside flood-response domain
    CLARIFICATION_REQUIRED = "clarification_required"  # Ambiguous / missing crucial details


class GateStatus(StrEnum):
    """Validation gate outcome for arbitrary input."""

    ACCEPT = "accept"   # Input is understood and valid for FlowShield
    CLARIFY = "clarify" # Input is flood-related but required info is missing
    REJECT = "reject"   # Input is outside supported flood-response domain


class ExtractedFacts(BaseModel):
    """Structured operational facts extracted from natural language."""

    people_at_risk: int | None = Field(default=None, ge=0)
    people_trapped: int | None = Field(default=None, ge=0)
    water_depth_m: float | None = Field(default=None, ge=0.0)
    rainfall_mm_hr: float | None = Field(default=None, ge=0.0)
    critical_facility: str | None = Field(default=None)
    road_blocked: bool | None = Field(default=None)
    resource_id: str | None = Field(default=None)
    resource_name: str | None = Field(default=None)
    resource_status: str | None = Field(default=None)
    incident_type: str | None = Field(default=None)
    severity: str | None = Field(default=None)
    zone_id: str | None = Field(default=None)
    location_name: str | None = Field(default=None)
    query_topic: str | None = Field(default=None)
    simulation_scenario: str | None = Field(default=None)
    extra_attributes: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": False, "extra": "allow"}


class InputEnvelope(BaseModel):
    """Canonical envelope representing parsed and validated external input."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_input: str = Field(..., min_length=1)
    intent: InputIntent = Field(...)
    domain: str = Field(default="flood_response")
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)
    location: str | None = Field(default=None)
    affected_areas: list[str] = Field(default_factory=list)
    requested_operation: str | None = Field(default=None)
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: GateStatus = Field(...)
    rejection_reason: str | None = Field(default=None)
    clarification_prompt: str | None = Field(default=None)
    source: str = Field(default="fallback", description="'grok' or 'fallback'")
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"frozen": False, "extra": "forbid"}
