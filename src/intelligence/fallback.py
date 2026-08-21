"""Deterministic fallback parser for input classification and fact extraction.

Provides 100% reliable, offline, rule-based NLP classification when Grok is
unavailable or disabled.
"""

from __future__ import annotations

import re

from src.intelligence.models import (
    ExtractedFacts,
    GateStatus,
    InputEnvelope,
    InputIntent,
)


class DeterministicInputFallback:
    """Rule-based pattern matching and validation gate for natural-language input."""

    # Non-flood / unsupported domain triggers
    UNSUPPORTED_PATTERNS = [
        r"\bearthquake\b",
        r"\bwildfire\b",
        r"\bforest\s+fire\b",
        r"\bvolcano\b",
        r"\btsunami\b",
        r"\bstock\s+market\b",
        r"\bpizza\b",
        r"\bjoke\b",
        r"\bweather\s+forecast\s+in\s+(?:london|paris|new\s+york|tokyo)\b",
        r"\bcricket\b",
        r"\bflight\s+booking\b",
    ]

    # Simulation triggers
    SIMULATION_PATTERNS = [
        r"\bwhat\s+(?:happens|if|would\s+happen)\b",
        r"\bsimulate\b",
        r"\bwhat\s+if\s+pump\b",
        r"\bscenario\s+test\b",
        r"\bhypothetical\b",
    ]

    # Resource update triggers
    RESOURCE_PATTERNS = [
        (
            r"\b(?:crew|pump|rescue|team|vehicle|unit)\s+[\w\-]+\s+is\s+"
            r"(?:unavailable|available|offline|deployed|standby|broken|operational)\b"
        ),
        r"\b(?:unavailable|offline|broken|out\s+of\s+service)\b",
        r"\bmark\s+(?:crew|pump|resource)\b",
        r"\bresource\s+status\b",
    ]

    # State / Sensor update triggers
    STATE_PATTERNS = [
        r"\brainfall\s+(?:increased|decreased|is|at|reached)\b",
        r"\b\d+\s*mm(?:/hr)?\b",
        r"\bwater\s+level\s+(?:is|at|reached|rose\s+to)\s+\d+(?:\.\d+)?\s*(?:m|meter|metres|cm|ft)\b",
        r"\bgauge\s+reading\b",
        r"\bsensor\s+update\b",
    ]

    # Query triggers
    QUERY_PATTERNS = [
        r"\bwhich\s+incident\s+is\s+(?:most\s+urgent|highest\s+priority|critical)\b",
        r"\bwhat\s+is\s+(?:happening|the\s+status|the\s+situation)\b",
        r"\bwho\s+is\s+at\s+risk\b",
        r"\bhow\s+many\s+(?:resources|incidents|pumps|crews)\b",
        r"\bstatus\s+of\b",
        r"\blist\s+(?:incidents|resources|decisions)\b",
    ]

    # Clarification required triggers (vague/incomplete reports)
    VAGUE_PATTERNS = [
        r"^send\s+help(?:\s+please)?\.?$",
        r"^help(?:\s+me)?\.?$",
        r"^hello\.?$",
        r"^urgent\.?$",
        r"^emergency\.?$",
        r"^send\s+help\s+to\s+the\s+school\.?$",
        r"^there\s+is\s+water\.?$",
    ]

    def parse(
        self,
        raw_input: str,
        zone_id_hint: str | None = None,
        city: str = "Ahmedabad",
    ) -> InputEnvelope:
        """Parse raw text and return a canonical InputEnvelope."""
        text = raw_input.strip()
        lower = text.lower()

        # 1. Check for completely unsupported domains (REJECT)
        for pat in self.UNSUPPORTED_PATTERNS:
            if re.search(pat, lower):
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.UNSUPPORTED,
                    domain="unsupported",
                    status=GateStatus.REJECT,
                    confidence=0.95,
                    rejection_reason="Input is outside the supported urban flood-response domain.",
                    source="fallback",
                )

        # 2. Check for vague / ambiguous input requiring clarification (CLARIFY)
        for pat in self.VAGUE_PATTERNS:
            if re.match(pat, lower):
                missing = ["location", "flood_severity", "people_at_risk"]
                if "school" in lower:
                    missing = ["specific_zone_or_school_name", "water_depth", "people_at_risk"]
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.CLARIFICATION_REQUIRED,
                    domain="flood_response",
                    status=GateStatus.CLARIFY,
                    confidence=0.85,
                    missing_information=missing,
                    clarification_prompt=(
                        "Please provide specific location/zone details, water level, "
                        "and whether people are trapped or at risk."
                    ),
                    source="fallback",
                )

        # 3. Classify simulation
        for pat in self.SIMULATION_PATTERNS:
            if re.search(pat, lower):
                facts = self._extract_facts(text, lower, zone_id_hint)
                facts.simulation_scenario = text
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.SIMULATION,
                    domain="flood_response",
                    facts=facts,
                    requested_operation="simulation_dry_run",
                    status=GateStatus.ACCEPT,
                    confidence=0.90,
                    source="fallback",
                )

        # 4. Classify queries
        for pat in self.QUERY_PATTERNS:
            if re.search(pat, lower):
                facts = self._extract_facts(text, lower, zone_id_hint)
                facts.query_topic = text
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.QUERY,
                    domain="flood_response",
                    facts=facts,
                    requested_operation="query_status",
                    status=GateStatus.ACCEPT,
                    confidence=0.90,
                    source="fallback",
                )

        # 5. Classify resource updates
        for pat in self.RESOURCE_PATTERNS:
            if re.search(pat, lower):
                facts = self._extract_facts(text, lower, zone_id_hint)
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.RESOURCE_UPDATE,
                    domain="flood_response",
                    facts=facts,
                    requested_operation="update_resource",
                    status=GateStatus.ACCEPT,
                    confidence=0.90,
                    source="fallback",
                )

        # 6. Classify state updates
        for pat in self.STATE_PATTERNS:
            if re.search(pat, lower):
                facts = self._extract_facts(text, lower, zone_id_hint)
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.STATE_UPDATE,
                    domain="flood_response",
                    facts=facts,
                    requested_operation="update_state",
                    status=GateStatus.ACCEPT,
                    confidence=0.90,
                    source="fallback",
                )

        # 7. Default to Incident classification if flood keywords or numbers present
        flood_keywords = [
            "flood", "trapped", "water", "drain", "waterlogging", "submerged",
            "rescue", "hospital", "school", "road", "rain",
        ]
        has_flood_keyword = any(kw in lower for kw in flood_keywords)

        if has_flood_keyword or len(text.split()) >= 3:
            facts = self._extract_facts(text, lower, zone_id_hint)
            
            # Check if incident has enough minimum info
            has_minimum = any([
                facts.zone_id,
                facts.location_name,
                facts.critical_facility,
                facts.people_trapped,
                facts.people_at_risk,
                facts.water_depth_m,
            ])
            if not has_minimum:
                return InputEnvelope(
                    raw_input=text,
                    intent=InputIntent.CLARIFICATION_REQUIRED,
                    domain="flood_response",
                    facts=facts,
                    status=GateStatus.CLARIFY,
                    confidence=0.70,
                    missing_information=["location", "severity_details"],
                    clarification_prompt="Please specify the location and flood condition details.",
                    source="fallback",
                )

            return InputEnvelope(
                raw_input=text,
                intent=InputIntent.INCIDENT,
                domain="flood_response",
                facts=facts,
                location=facts.location_name or facts.zone_id,
                affected_areas=[facts.zone_id] if facts.zone_id else [],
                requested_operation="ingest_incident",
                status=GateStatus.ACCEPT,
                confidence=0.85,
                source="fallback",
            )

        # If completely unclassifiable garbage
        return InputEnvelope(
            raw_input=text,
            intent=InputIntent.CLARIFICATION_REQUIRED,
            domain="unknown",
            status=GateStatus.CLARIFY,
            confidence=0.50,
            missing_information=["intent", "location", "details"],
            clarification_prompt="Input not recognized. Please provide flood emergency details.",
            source="fallback",
        )

    def _extract_facts(
        self,
        text: str,
        lower: str,
        zone_id_hint: str | None = None,
    ) -> ExtractedFacts:
        """Extract structured entities from text using regex."""
        facts = ExtractedFacts()

        # People trapped
        m_trap = re.search(
            r"(\d+)\s*(?:people|persons|residents|citizens)?\s*(?:are\s+)?trapped", lower
        )
        if not m_trap:
            m_trap = re.search(r"trapped\s*(?:count|is)?\s*(\d+)", lower)
        if m_trap:
            facts.people_trapped = int(m_trap.group(1))

        # People at risk
        m_risk = re.search(
            r"(\d+)\s*(?:people|persons|residents|citizens)?\s*(?:at\s+risk|affected|impacted)",
            lower,
        )
        if m_risk:
            facts.people_at_risk = int(m_risk.group(1))

        # Water depth (meters or feet)
        m_depth_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|meters|metre|metres)\b", lower)
        if m_depth_m:
            facts.water_depth_m = float(m_depth_m.group(1))
        else:
            m_depth_ft = re.search(r"(\d+(?:\.\d+)?)\s*(?:ft|feet|foot)\b", lower)
            if m_depth_ft:
                facts.water_depth_m = round(float(m_depth_ft.group(1)) * 0.3048, 2)

        # Rainfall mm/hr
        m_rain = re.search(r"(\d+(?:\.\d+)?)\s*(?:mm/hr|mm\s*per\s*hour|mm)\b", lower)
        if m_rain:
            facts.rainfall_mm_hr = float(m_rain.group(1))

        # Critical facilities
        if "hospital" in lower:
            facts.critical_facility = "Hospital"
        elif "school" in lower:
            facts.critical_facility = "School"
        elif "fire station" in lower:
            facts.critical_facility = "Fire Station"
        elif "shelter" in lower:
            facts.critical_facility = "Relief Shelter"

        # Road blocked
        blocked_cues = [
            "road blocked", "blocked road", "road closed",
            "traffic blocked", "submerged road",
        ]
        if any(w in lower for w in blocked_cues):
            facts.road_blocked = True

        # Zone ID extraction (e.g. W12-C, W12-N, W12-S, AMC-W07)
        m_zone = re.search(r"\b(W\d+-[NCS]|DEPOT|[A-Z]{2,5}-[A-Z0-9]+)\b", text)
        if m_zone:
            facts.zone_id = m_zone.group(1)
        elif zone_id_hint:
            facts.zone_id = zone_id_hint

        # Location name
        m_loc = re.search(
            r"(?:near|at|in|around)\s+(?:the\s+)?([A-Za-z0-9\s\-]+?)(?:,|;|\.|\band\b|$)",
            text,
        )
        if m_loc:
            facts.location_name = m_loc.group(1).strip()

        # Resource ID / Name / Status extraction
        res_pat = (
            r"\b(rescue[\s\-_]?(?:crew|team)[\s\-_]?[a-z0-9]+|"
            r"crew[\s\-_]?[a-z0-9]+|"
            r"pump[\s\-_]?(?:unit[\s\-_]?)?[a-z0-9]+|"
            r"unit[\s\-_]?[a-z0-9]+)\b"
        )
        m_res = re.search(res_pat, lower)
        if m_res:
            facts.resource_name = m_res.group(1).strip()
            facts.resource_id = m_res.group(1).strip().replace(" ", "-")

        if any(w in lower for w in ["unavailable", "offline", "broken", "out of service"]):
            facts.resource_status = "unavailable"
        elif any(w in lower for w in ["available", "ready", "online", "operational"]):
            facts.resource_status = "available"
        elif "deployed" in lower:
            facts.resource_status = "deployed"
        elif "standby" in lower:
            facts.resource_status = "standby"

        # Severity determination
        is_crit = (
            (facts.people_trapped and facts.people_trapped >= 5)
            or (facts.water_depth_m and facts.water_depth_m >= 2.0)
            or "critical" in lower
        )
        is_high = (
            (facts.water_depth_m and facts.water_depth_m >= 1.0)
            or (facts.people_trapped and facts.people_trapped > 0)
            or "high" in lower
        )
        if is_crit:
            facts.severity = "critical"
        elif is_high:
            facts.severity = "high"
        elif (facts.water_depth_m and facts.water_depth_m >= 0.5) or "medium" in lower:
            facts.severity = "medium"
        else:
            facts.severity = "low"

        return facts
