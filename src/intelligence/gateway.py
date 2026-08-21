"""GrokInputGateway — primary entry point for natural language input intelligence.

Wires together Grok LLM client and deterministic fallback parser.
Enforces the Validation Gate: ACCEPT / CLARIFY / REJECT.
"""

from __future__ import annotations

import json
import logging

from src.intelligence.fallback import DeterministicInputFallback
from src.intelligence.grok_client import GrokClient, GrokUnavailable
from src.intelligence.models import (
    ExtractedFacts,
    GateStatus,
    InputEnvelope,
    InputIntent,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are FLOWSHIELD Input Intelligence Gateway.
Analyze the user input and output a valid JSON object with the following schema:

{
  "intent": "incident" | "state_update" | "resource_update" | "simulation" |
            "query" | "unsupported" | "clarification_required",
  "domain": "flood_response" | "unsupported",
  "status": "accept" | "clarify" | "reject",
  "confidence": 0.0 to 1.0,
  "facts": {
    "people_at_risk": int or null,
    "people_trapped": int or null,
    "water_depth_m": float or null,
    "rainfall_mm_hr": float or null,
    "critical_facility": string or null,
    "road_blocked": bool or null,
    "resource_id": string or null,
    "resource_name": string or null,
    "resource_status": "available" | "unavailable" | "deployed" | "standby" | null,
    "incident_type": string or null,
    "severity": "low" | "medium" | "high" | "critical" | null,
    "zone_id": string or null,
    "location_name": string or null,
    "query_topic": string or null,
    "simulation_scenario": string or null
  },
  "location": string or null,
  "affected_areas": [string],
  "requested_operation": string or null,
  "missing_information": [string],
  "rejection_reason": string or null,
  "clarification_prompt": string or null
}

RULES:
1. "earthquake", "wildfire", etc. MUST be intent="unsupported", status="reject".
2. "what if", "simulate", "what happens if" MUST be intent="simulation", status="accept".
3. "crew/pump unavailable/offline" MUST be intent="resource_update", status="accept".
4. "which incident is most urgent", "status", "who is at risk" -> intent="query", status="accept".
5. Vague inputs like "send help", "urgent" -> intent="clarification_required", status="clarify".
6. Never invent resource IDs or zone IDs not mentioned or hinted.
7. Output ONLY the JSON object.
"""


class GrokInputGateway:
    """Classifies natural language input and extracts structured operational facts."""

    def __init__(
        self,
        grok_client: GrokClient | None = None,
        fallback_parser: DeterministicInputFallback | None = None,
    ) -> None:
        self._grok = grok_client or GrokClient()
        self._fallback = fallback_parser or DeterministicInputFallback()

    def process(
        self,
        raw_input: str,
        zone_id_hint: str | None = None,
        city: str = "Ahmedabad",
    ) -> InputEnvelope:
        """Process natural-language input through Grok with deterministic fallback."""
        if not raw_input or not raw_input.strip():
            return self._fallback.parse(raw_input or "", zone_id_hint, city)

        text = raw_input.strip()

        # Try Grok API if configured
        if self._grok.is_configured:
            try:
                prompt = (
                    f"City context: {city}\n"
                    f"Zone ID hint: {zone_id_hint or 'None'}\n"
                    f"User Input: \"{text}\""
                )
                raw_json = self._grok.complete(prompt=prompt, system_prompt=_SYSTEM_PROMPT)
                data = json.loads(raw_json)

                # Construct and validate InputEnvelope
                envelope = InputEnvelope(
                    raw_input=text,
                    intent=InputIntent(data["intent"]),
                    domain=data.get("domain", "flood_response"),
                    facts=ExtractedFacts(**data.get("facts", {})),
                    location=data.get("location"),
                    affected_areas=data.get("affected_areas", []),
                    requested_operation=data.get("requested_operation"),
                    missing_information=data.get("missing_information", []),
                    confidence=float(data.get("confidence", 1.0)),
                    status=GateStatus(data["status"]),
                    rejection_reason=data.get("rejection_reason"),
                    clarification_prompt=data.get("clarification_prompt"),
                    source="grok",
                )
                return envelope
            except (GrokUnavailable, json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.info("Grok gateway fallback activated due to: %s", exc)

        # Graceful deterministic fallback
        return self._fallback.parse(text, zone_id_hint, city)
