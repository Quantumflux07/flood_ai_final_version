"""FlowShieldV2Manager — Unified operational state manager, replanner & simulation engine.

Flow:
  InputEnvelope (Accepted) → State Update → Life-Safety Priority → Resource Optimizer
  → Response Plan → Action & Outcome → Synchronous Replan
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src.agents.response_plan import ResponsePlan
from src.agents.response_planning_agent import ResponsePlanningAgent
from src.engine.engine import SituationEngine
from src.engine.optimizer import GreedyResourceOptimizer
from src.engine.optimizer_request import DEFAULT_CAPABILITIES, OptimizationRequest
from src.engine.optimizer_result import OptimizationResult
from src.engine.priority_context import IncidentContext
from src.engine.priority_engine import IncidentPriorityEngine
from src.engine.priority_result import PriorityResult
from src.intelligence.gateway import GrokInputGateway
from src.intelligence.models import GateStatus, InputEnvelope, InputIntent
from src.knowledge.documents import FLOWSHIELD_KB
from src.models import Action, Incident, Outcome, Resource, SituationState
from src.models.action import ActionStatus
from src.models.event import RawEvent, RawEventType
from src.models.evidence import Evidence, EvidenceSource
from src.models.incident import IncidentStatus, SeverityLevel
from src.models.resource import ResourceStatus
from src.models.situation import ZoneSeverity
from src.reasoning.reasoning_layer import GraniteReasoningLayer
from src.workflow.scenario_ward12 import (
    CITY,
    DISTANCES,
    INCIDENT_CONTEXT,
    make_events,
    make_resources,
)

logger = logging.getLogger(__name__)


def to_json_dict(obj: Any) -> Any:
    """Recursively convert Pydantic/dataclass/enum objects to JSON-serializable types."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "value"):  # StrEnum / Enum
        return to_json_dict(obj.value)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            res = obj.model_dump(mode="json")
        except Exception:
            res = obj.model_dump()
        res = to_json_dict(res)
        if isinstance(obj, SituationState):
            res["overall_severity"] = str(obj.overall_severity)
            res["zones"] = {zid: to_json_dict(z) for zid, z in obj.zones.items()}
        return res
    if hasattr(obj, "__dict__"):
        res = {}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            res[k] = to_json_dict(v)
        return res
    if isinstance(obj, (list, tuple, set)):
        return [to_json_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): to_json_dict(v) for k, v in obj.items()}
    return obj


class FlowShieldV2Manager:
    """Authoritative state core for FlowShield V2.

    Manages:
    - Zone-independent incident registry
    - Resource registry and lifecycle
    - Synchronous priority recomputation and replanning
    - Isolated simulation runs via snapshots
    """

    def __init__(self, city: str = CITY) -> None:
        self.city = city.strip()
        self.gateway = GrokInputGateway()
        self.priority_engine = IncidentPriorityEngine()
        self.optimizer = GreedyResourceOptimizer()
        self.planning_agent = ResponsePlanningAgent(city=self.city, knowledge_base=FLOWSHIELD_KB)
        self.reasoning_layer = GraniteReasoningLayer()

        self.reset()

    def reset(self) -> None:
        """Reset operational state to baseline Ward 12 scenario."""
        self.engine = SituationEngine(city=self.city)
        self.distances = copy.deepcopy(DISTANCES)
        self.resources: dict[str, Resource] = {}
        for r in make_resources():
            self.resources[r.id] = r
            self.engine.resources[r.id] = r

        # Populate initial baseline events
        self.timeline: list[dict[str, Any]] = []
        for evt in make_events():
            rec = self.engine.process(evt)
            self.timeline.append({
                "id": rec.id,
                "occurred_at": (
                    rec.occurred_at.isoformat()
                    if rec.occurred_at
                    else datetime.now(UTC).isoformat()
                ),
                "type": "event_ingestion",
                "title": f"Initial Event: {rec.raw_event_type}",
                "details": f"Zone: {rec.zone_id} | Type: {rec.raw_event_type}",
                "severity": str(rec.zone_severity_after or "normal"),
            })

        # Incidents stored by incident.id (Zone independence)
        self.incidents: dict[str, Incident] = {}
        self.incident_contexts: dict[str, IncidentContext] = {}

        # Copy auto-detected incidents from engine
        for inc in self.engine.incidents.values():
            self.incidents[inc.id] = inc
            ctx_kwargs = INCIDENT_CONTEXT.get(inc.zone_id, {})
            self.incident_contexts[inc.id] = IncidentContext(incident=inc, **ctx_kwargs)

        self.priority_results: list[PriorityResult] = []
        self.optimization_result: OptimizationResult | None = None
        self.actions: list[Action] = []
        self.outcomes: list[Outcome] = []
        self.response_plan: ResponsePlan | None = None
        self.why_panel: dict[str, Any] = {}

        self.replan()

    # ── Pipeline Recomputation (Replanning) ──────────────────────────────────

    def replan(self) -> dict[str, Any]:
        """Synchronously recompute priority, resource allocation, response plan and outcomes."""
        open_incidents = [
            inc for inc in self.incidents.values()
            if inc.status == IncidentStatus.OPEN
        ]

        # 1. Build IncidentContexts with life-safety attributes
        contexts: list[IncidentContext] = []
        for inc in open_incidents:
            ctx = self.incident_contexts.get(inc.id)
            if ctx is None:
                zone_ctx = INCIDENT_CONTEXT.get(inc.zone_id, {})
                fac_count = 1 if inc.critical_facility else zone_ctx.get(
                    "critical_facility_count", 0
                )
                pop = inc.people_at_risk or zone_ctx.get("affected_population")
                deadline = (
                    1.5
                    if (inc.people_trapped and inc.people_trapped > 0)
                    else zone_ctx.get("hours_until_deadline")
                )
                infra = len(inc.dependencies) or zone_ctx.get("infra_dependency_count", 0)

                ctx = IncidentContext(
                    incident=inc,
                    critical_facility_count=fac_count,
                    road_blocked=zone_ctx.get("road_blocked", False),
                    affected_population=pop,
                    people_at_risk=inc.people_at_risk,
                    people_trapped=inc.people_trapped or 0,
                    hours_until_deadline=deadline,
                    infra_dependency_count=infra,
                )
                self.incident_contexts[inc.id] = ctx
            else:
                ctx.incident = inc
                if inc.people_trapped and not ctx.people_trapped:
                    ctx.people_trapped = inc.people_trapped
                if inc.people_at_risk and not ctx.people_at_risk:
                    ctx.people_at_risk = inc.people_at_risk
            contexts.append(ctx)

        # 2. Score and Rank Priorities
        self.priority_results = self.priority_engine.rank(contexts)

        # 3. Available resources
        available = [
            r for r in self.resources.values()
            if r.status in (ResourceStatus.AVAILABLE, ResourceStatus.STANDBY)
        ]

        # 4. Resolve operational zones for optimizer
        incident_zones = {}
        for inc in open_incidents:
            zone = inc.zone_id
            if zone.startswith("UNKNOWN") or zone == "UNRESOLVED":
                zone = inc.affected_areas[0] if inc.affected_areas else "W12-C"
            incident_zones[inc.id] = zone

        resource_zones = {
            r.id: (r.current_zone_id or r.home_zone_id)
            for r in available
        }

        opt_request = OptimizationRequest(
            prioritized_incidents=self.priority_results,
            available_resources=available,
            incident_zones=incident_zones,
            resource_zones=resource_zones,
            capabilities=list(DEFAULT_CAPABILITIES),
            distances=self.distances,
            max_travel_minutes=60.0,
        )
        self.optimization_result = self.optimizer.optimize(opt_request)

        # 5. Generate Response Plan with policy grounding
        planning_result = self.planning_agent.plan(
            state=self.engine.state,
            priority_results=self.priority_results,
            opt_result=self.optimization_result,
            resources=list(self.resources.values()),
        )
        self.response_plan = planning_result.plan

        # 6. Generate Action objects
        actions: list[Action] = []
        for assignment in self.optimization_result.assignments:
            action = Action(
                id=str(uuid.uuid4()),
                incident_id=assignment.incident_id,
                resource_id=assignment.resource_id,
                decided_by="flowshield_v2_optimizer",
                decision_rationale=(
                    f"Assigned by GreedyResourceOptimizer. "
                    f"Reason: {', '.join(assignment.reason_codes)}. "
                    f"Fit score: {assignment.fit_score:.3f}. "
                    f"ETA: {assignment.estimated_travel_minutes} min."
                ),
                priority=1,
                status=ActionStatus.PENDING,
            )
            actions.append(action)
        self.actions = actions

        # 7. Generate Outcomes
        outcomes: list[Outcome] = []
        inc_map = {inc.id: inc for inc in open_incidents}
        pr_map = {pr.incident_id: pr for pr in self.priority_results}

        for action in self.actions:
            inc = inc_map.get(action.incident_id)
            pr = pr_map.get(action.incident_id)
            severity_before = str(inc.severity) if inc else "unknown"
            level = str(pr.level) if pr else "unknown"
            outcome = Outcome(
                id=str(uuid.uuid4()),
                action_id=action.id,
                incident_id=action.incident_id,
                success=True,
                severity_after=severity_before,
                notes=f"Action dispatched. Priority: {level}. Awaiting field execution.",
                effectiveness_score=None,
            )
            outcomes.append(outcome)
        self.outcomes = outcomes

        # 8. Reasoning Why Panel
        try:
            self.why_panel = {
                "reasoning_situation": to_json_dict(
                    self.reasoning_layer.summarize_situation(self.engine.state, open_incidents)
                ),
                "reasoning_priorities": to_json_dict(
                    self.reasoning_layer.explain_priorities(self.priority_results, open_incidents)
                ),
                "reasoning_assignments": to_json_dict(
                    self.reasoning_layer.explain_assignments(self.optimization_result, available)
                ),
                "operator_response": to_json_dict(
                    self.reasoning_layer.generate_response_plan(
                        self.optimization_result, self.priority_results, open_incidents
                    )
                ),
            }
        except Exception as exc:
            logger.warning("Why panel reasoning fallback: %s", exc)
            self.why_panel = {}

        return self.get_summary_dict()

    # ── Natural Language Input Flow ──────────────────────────────────────────

    def analyze_input(
        self,
        raw_input: str,
        zone_id_hint: str | None = None,
    ) -> InputEnvelope:
        """Run input through Grok Input Intelligence gateway and validation gate."""
        return self.gateway.process(raw_input, zone_id_hint=zone_id_hint, city=self.city)

    def execute_input(
        self,
        envelope_or_text: InputEnvelope | str,
        zone_id_hint: str | None = None,
    ) -> dict[str, Any]:
        """Execute an accepted structured input request through FlowShield core."""
        if isinstance(envelope_or_text, str):
            envelope = self.analyze_input(envelope_or_text, zone_id_hint)
        else:
            envelope = envelope_or_text

        # Gate Check
        if envelope.status == GateStatus.REJECT:
            return {
                "status": "rejected",
                "code": "UNSUPPORTED_DOMAIN",
                "reason": envelope.rejection_reason or "Input outside flood response domain.",
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        if envelope.status == GateStatus.CLARIFY:
            return {
                "status": "clarify",
                "code": "CLARIFICATION_REQUIRED",
                "missing_information": envelope.missing_information,
                "message": envelope.clarification_prompt or "Clarification required.",
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        facts = envelope.facts

        # ── Intent 1: Incident ──────────────────────────────────────────────
        if envelope.intent == InputIntent.INCIDENT:
            resolved_zone = facts.zone_id or zone_id_hint or envelope.location or "W12-C"
            if resolved_zone not in self.engine.state.zones and "-" not in resolved_zone:
                resolved_zone = "W12-C"

            water_depth = facts.water_depth_m or 1.2
            rainfall = facts.rainfall_mm_hr or 35.0
            if (
                facts.severity == "critical"
                or (facts.people_trapped and facts.people_trapped >= 5)
            ):
                water_depth = max(water_depth, 2.2)
                rainfall = max(rainfall, 70.0)

            try:
                ev = Evidence(
                    city=self.city,
                    zone_id=resolved_zone,
                    source=EvidenceSource.CITIZEN_REPORT,
                    observed_at=datetime.now(UTC),
                    rainfall_mm_hr=rainfall,
                    water_level_m=water_depth,
                    road_blocked=facts.road_blocked or False,
                    affected_population=facts.people_at_risk or facts.people_trapped or 500,
                    raw={"raw_input": envelope.raw_input},
                )
                self.engine._ingestor.apply(ev, self.engine.state)
            except Exception as exc:
                logger.warning("Evidence ingest warning: %s", exc)

            sev_level = SeverityLevel.HIGH
            if facts.severity:
                try:
                    sev_level = SeverityLevel(facts.severity.lower())
                except ValueError:
                    sev_level = SeverityLevel.HIGH
            elif facts.people_trapped and facts.people_trapped >= 5:
                sev_level = SeverityLevel.CRITICAL

            pop_calc = (
                facts.people_at_risk
                or (facts.people_trapped * 3 if facts.people_trapped else 100)
            )
            inc = Incident(
                id=str(uuid.uuid4()),
                city=self.city,
                zone_id=resolved_zone,
                affected_zone_ids=[resolved_zone],
                severity=sev_level,
                risk_score=0.85 if sev_level == SeverityLevel.CRITICAL else 0.65,
                title=(
                    f"[{sev_level.upper()}] {facts.location_name or 'Emergency'}: "
                    f"{envelope.raw_input[:60]}"
                ),
                description=envelope.raw_input,
                location=facts.location_name or envelope.location,
                affected_areas=[resolved_zone],
                people_at_risk=pop_calc,
                people_trapped=facts.people_trapped or 0,
                critical_facility=facts.critical_facility,
                source=f"grok_gateway_{envelope.source}",
                status=IncidentStatus.OPEN,
            )
            self.incidents[inc.id] = inc

            zone_status = self.engine.state.zones.get(resolved_zone)
            zone_road = zone_status.road_blocked if zone_status else False
            zone_ctx = INCIDENT_CONTEXT.get(resolved_zone, {})
            fac_count = 2 if facts.critical_facility else zone_ctx.get(
                "critical_facility_count", 0
            )
            deadline = (
                0.5
                if (inc.people_trapped and inc.people_trapped > 0)
                else zone_ctx.get("hours_until_deadline", 3.0)
            )
            is_road_blocked = (
                facts.road_blocked
                if facts.road_blocked is not None
                else (zone_road or zone_ctx.get("road_blocked", False))
            )

            ctx = IncidentContext(
                incident=inc,
                critical_facility_count=fac_count,
                road_blocked=is_road_blocked,
                affected_population=inc.people_at_risk,
                people_at_risk=inc.people_at_risk,
                people_trapped=inc.people_trapped or 0,
                hours_until_deadline=deadline,
                infra_dependency_count=zone_ctx.get("infra_dependency_count", 1),
            )
            self.incident_contexts[inc.id] = ctx

            self.timeline.append({
                "id": str(uuid.uuid4()),
                "occurred_at": datetime.now(UTC).isoformat(),
                "type": "incident_reported",
                "title": f"Incident: {inc.title}",
                "details": (
                    f"Location: {inc.location or inc.zone_id} | "
                    f"Trapped: {inc.people_trapped} | At Risk: {inc.people_at_risk}"
                ),
                "severity": str(inc.severity),
            })

            self.replan()

            return {
                "status": "success",
                "intent": "incident",
                "incident": to_json_dict(inc),
                "drivers": self.priority_engine.explain_drivers(ctx),
                "interpretation": to_json_dict(envelope),
                "allocations": to_json_dict(self.optimization_result),
                "response_plan": to_json_dict(self.response_plan),
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        # ── Intent 2: Resource Update ───────────────────────────────────────
        elif envelope.intent == InputIntent.RESOURCE_UPDATE:
            res_query = facts.resource_id or facts.resource_name or envelope.raw_input
            target_res = self._find_resource(res_query)
            if target_res is None:
                return {
                    "status": "error",
                    "code": "RESOURCE_NOT_FOUND",
                    "message": (
                        f"Resource matching '{facts.resource_name or envelope.raw_input}' "
                        f"was not found in active inventory."
                    ),
                    "next_action": "check_available_resources",
                }

            new_status_str = facts.resource_status or "unavailable"
            try:
                new_status = ResourceStatus(new_status_str.lower())
            except ValueError:
                new_status = ResourceStatus.UNAVAILABLE

            prev_status = target_res.status
            target_res.status = new_status
            target_res.updated_at = datetime.now(UTC)

            self.timeline.append({
                "id": str(uuid.uuid4()),
                "occurred_at": datetime.now(UTC).isoformat(),
                "type": "resource_update",
                "title": f"Resource Status Change: {target_res.name}",
                "details": f"Status changed from {prev_status} to {new_status}",
                "severity": "warning" if new_status == ResourceStatus.UNAVAILABLE else "normal",
            })

            self.replan()

            return {
                "status": "success",
                "intent": "resource_update",
                "resource_id": target_res.id,
                "previous_status": str(prev_status),
                "new_status": str(new_status),
                "interpretation": to_json_dict(envelope),
                "allocations": to_json_dict(self.optimization_result),
                "response_plan": to_json_dict(self.response_plan),
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        # ── Intent 3: State Update ──────────────────────────────────────────
        elif envelope.intent == InputIntent.STATE_UPDATE:
            target_zone = facts.zone_id or zone_id_hint or "W12-C"
            rainfall = facts.rainfall_mm_hr or 50.0
            water_level = facts.water_depth_m or 1.5

            raw_evt = RawEvent(
                event_type=(
                    RawEventType.RAINFALL
                    if facts.rainfall_mm_hr
                    else RawEventType.WATERLOGGING
                ),
                city=self.city,
                zone_id=target_zone,
                source="operator_state_update",
                occurred_at=datetime.now(UTC),
                payload={"rainfall_mm_hr": rainfall, "water_level_m": water_level},
            )
            rec = self.engine.process(raw_evt)

            self.timeline.append({
                "id": str(uuid.uuid4()),
                "occurred_at": datetime.now(UTC).isoformat(),
                "type": "state_update",
                "title": f"Zone Environmental Update: {target_zone}",
                "details": f"Rainfall: {rainfall} mm/hr | Water level: {water_level} m",
                "severity": str(rec.zone_severity_after or "warning"),
            })

            self.replan()

            z_sev = "normal"
            if target_zone in self.engine.state.zones:
                z_sev = str(self.engine.state.zones[target_zone].severity)

            return {
                "status": "success",
                "intent": "state_update",
                "zone_id": target_zone,
                "zone_severity": z_sev,
                "interpretation": to_json_dict(envelope),
                "allocations": to_json_dict(self.optimization_result),
                "response_plan": to_json_dict(self.response_plan),
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        # ── Intent 4: Simulation ────────────────────────────────────────────
        elif envelope.intent == InputIntent.SIMULATION:
            sim_res = self.simulate({"text": envelope.raw_input, "facts": facts})
            return {
                "status": "success",
                "intent": "simulation",
                "simulation": to_json_dict(sim_res),
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        # ── Intent 5: Query ─────────────────────────────────────────────────
        elif envelope.intent == InputIntent.QUERY:
            query_answer = self._handle_query(envelope.raw_input, facts)
            return {
                "status": "success",
                "intent": "query",
                "query": envelope.raw_input,
                "answer": query_answer,
                "state_summary": self.get_summary_dict(),
                "source": envelope.source,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        return {
            "status": "success",
            "message": "Input processed.",
            "source": envelope.source,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ── Simulation Safety (Snapshotting) ─────────────────────────────────────

    def simulate(self, scenario_params: dict[str, Any]) -> dict[str, Any]:
        """Execute what-if scenario on a deep copy of state; live state is unchanged."""
        sim_state = copy.deepcopy(self.engine.state)
        sim_incidents = copy.deepcopy(self.incidents)
        sim_contexts = copy.deepcopy(self.incident_contexts)
        sim_resources = copy.deepcopy(self.resources)
        sim_distances = copy.deepcopy(self.distances)

        scenario_desc = scenario_params.get("text", "Custom Simulation Scenario")
        facts = scenario_params.get("facts")

        if "resource_unavailable" in scenario_params:
            res_id = scenario_params["resource_unavailable"]
            if res_id in sim_resources:
                sim_resources[res_id].status = ResourceStatus.UNAVAILABLE
        elif facts and facts.resource_name:
            target = self._find_resource_in_dict(
                facts.resource_id or facts.resource_name, sim_resources
            )
            if target:
                target.status = ResourceStatus.UNAVAILABLE
        elif "pump" in scenario_desc.lower() and "fail" in scenario_desc.lower():
            target = self._find_resource_in_dict("pump", sim_resources)
            if target:
                target.status = ResourceStatus.UNAVAILABLE

        if "rainfall_increase" in scenario_params:
            spec = scenario_params["rainfall_increase"]
            zid = spec.get("zone_id", "W12-C")
            rain = spec.get("rainfall_mm_hr", 120.0)
            if zid in sim_state.zones:
                sim_state.zones[zid].latest_rainfall_mm_hr = rain
                sim_state.zones[zid].severity = ZoneSeverity.CRITICAL

        open_incs = [i for i in sim_incidents.values() if i.status == IncidentStatus.OPEN]
        contexts = [sim_contexts.get(i.id) or IncidentContext(incident=i) for i in open_incs]
        sim_priorities = self.priority_engine.rank(contexts)

        available = [
            r for r in sim_resources.values()
            if r.status in (ResourceStatus.AVAILABLE, ResourceStatus.STANDBY)
        ]
        incident_zones = {inc.id: inc.zone_id for inc in open_incs}
        resource_zones = {r.id: (r.current_zone_id or r.home_zone_id) for r in available}

        opt_req = OptimizationRequest(
            prioritized_incidents=sim_priorities,
            available_resources=available,
            incident_zones=incident_zones,
            resource_zones=resource_zones,
            capabilities=list(DEFAULT_CAPABILITIES),
            distances=sim_distances,
            max_travel_minutes=60.0,
        )
        sim_opt = self.optimizer.optimize(opt_req)

        planning_agent = ResponsePlanningAgent(city=self.city, knowledge_base=FLOWSHIELD_KB)
        sim_plan = planning_agent.plan(
            state=sim_state,
            priority_results=sim_priorities,
            opt_result=sim_opt,
            resources=list(sim_resources.values()),
        )

        return {
            "scenario": scenario_desc,
            "simulated_at": datetime.now(UTC).isoformat(),
            "live_state_modified": False,
            "assignments": to_json_dict(sim_opt.assignments),
            "unassigned_gaps": to_json_dict(sim_opt.unassigned_incidents),
            "response_plan": to_json_dict(sim_plan.plan),
            "gap_count": len(sim_opt.unassigned_incidents),
            "assigned_count": len(sim_opt.assignments),
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_resource(self, query: str) -> Resource | None:
        return self._find_resource_in_dict(query, self.resources)

    def _find_resource_in_dict(
        self, query: str, res_dict: dict[str, Resource]
    ) -> Resource | None:
        raw_q = query.lower().strip()
        norm_q = raw_q.replace("-", " ").replace("_", " ")

        if raw_q in res_dict:
            return res_dict[raw_q]
        if raw_q.replace(" ", "-") in res_dict:
            return res_dict[raw_q.replace(" ", "-")]

        for r in res_dict.values():
            r_id = r.id.lower()
            r_name = r.name.lower().replace("—", " ").replace("-", " ")
            if r_id in norm_q or norm_q in r_id:
                return r
            if r_name in norm_q or norm_q in r_name:
                return r

            tokens = [
                t for t in norm_q.split()
                if t not in ("is", "unavailable", "available", "the", "offline", "due", "to")
            ]
            if tokens and all(t in r_name or t in r_id for t in tokens):
                return r
        return None

    def _handle_query(self, query_text: str, facts: Any) -> str:
        lower = query_text.lower()
        if "most urgent" in lower or "priority" in lower:
            if not self.priority_results:
                return "There are currently no active open incidents."
            top = self.priority_results[0]
            inc = self.incidents.get(top.incident_id)
            title = inc.title if inc else top.incident_id
            return (
                f"The most urgent incident is '{title}' with priority level "
                f"{top.level.upper()} (score: {top.score:.3f})."
            )

        if "who is at risk" in lower or "people" in lower:
            total_trapped = sum(
                inc.people_trapped or 0
                for inc in self.incidents.values()
                if inc.status == IncidentStatus.OPEN
            )
            total_risk = sum(
                inc.people_at_risk or 0
                for inc in self.incidents.values()
                if inc.status == IncidentStatus.OPEN
            )
            return (
                f"Operational situation: {total_trapped} people trapped and "
                f"{total_risk} residents at direct flood risk across "
                f"{len(self.incidents)} incidents."
            )

        if "resource" in lower:
            avail = sum(
                1 for r in self.resources.values()
                if r.status in (ResourceStatus.AVAILABLE, ResourceStatus.STANDBY)
            )
            unavail = sum(
                1 for r in self.resources.values()
                if r.status == ResourceStatus.UNAVAILABLE
            )
            return (
                f"Resource status: {avail} available/standby units, "
                f"{unavail} unavailable units out of {len(self.resources)} total."
            )

        return (
            f"Operational state is currently {self.engine.state.overall_severity.upper()} "
            f"with {len(self.incidents)} open incidents and {len(self.actions)} active actions."
        )

    def get_summary_dict(self) -> dict[str, Any]:
        """Return full operational snapshot for API and Dashboard consumers."""
        return {
            "city": self.city,
            "overall_severity": str(self.engine.state.overall_severity),
            "zones": {zid: to_json_dict(z) for zid, z in self.engine.state.zones.items()},
            "incidents": [to_json_dict(i) for i in self.incidents.values()],
            "priority_results": [to_json_dict(p) for p in self.priority_results],
            "resources": [to_json_dict(r) for r in self.resources.values()],
            "optimization_result": to_json_dict(self.optimization_result),
            "actions": [to_json_dict(a) for a in self.actions],
            "outcomes": [to_json_dict(o) for o in self.outcomes],
            "response_plan": to_json_dict(self.response_plan),
            "why_panel": self.why_panel,
            "timeline": self.timeline,
        }
