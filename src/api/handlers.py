"""API request handlers and response dispatchers for FlowShield V2.

Provides clean, structured HTTP handler methods usable by standard library
HTTPServer, FastAPI, or test callers.
"""

from __future__ import annotations

import logging
from typing import Any

from src.engine.state_manager import FlowShieldV2Manager, to_json_dict

logger = logging.getLogger(__name__)


class FlowShieldAPIHandler:
    """Dispatches API requests to FlowShieldV2Manager and formats standardized JSON responses."""

    def __init__(self, manager: FlowShieldV2Manager | None = None) -> None:
        self.manager = manager or FlowShieldV2Manager()

    # ── Input Intelligence Routes ────────────────────────────────────────────

    def handle_analyze_input(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """POST /api/input/analyze"""
        text = body.get("text") or body.get("report_text") or body.get("raw_input", "")
        if not text or not str(text).strip():
            return 400, {
                "status": "error",
                "code": "MISSING_INPUT_TEXT",
                "message": "Field 'text' or 'report_text' is required.",
            }

        zone_hint = body.get("zone_id_hint") or body.get("zone_id")
        envelope = self.manager.analyze_input(str(text), zone_hint)
        return 200, {
            "status": envelope.status.value,
            "envelope": to_json_dict(envelope),
            "source": envelope.source,
            "confidence": envelope.confidence,
        }

    def handle_execute_input(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """POST /api/input/execute"""
        text = body.get("text") or body.get("report_text") or body.get("raw_input")
        envelope_data = body.get("envelope")
        zone_hint = body.get("zone_id_hint") or body.get("zone_id")

        if not text and not envelope_data:
            return 400, {
                "status": "error",
                "code": "MISSING_INPUT",
                "message": "Either 'text' or 'envelope' object is required.",
            }

        try:
            result = self.manager.execute_input(envelope_data or text, zone_hint)
            status_code = 200
            if result.get("status") == "error":
                status_code = 400
            return status_code, result
        except Exception as exc:
            logger.exception("execute_input failed: %s", exc)
            return 500, {
                "status": "error",
                "code": "EXECUTION_FAILURE",
                "message": str(exc),
            }

    # ── Operational State Routes ─────────────────────────────────────────────

    def handle_get_state(self) -> tuple[int, dict[str, Any]]:
        """GET /api/state"""
        return 200, self.manager.get_summary_dict()

    def handle_get_incidents(self) -> tuple[int, dict[str, Any]]:
        """GET /api/incidents"""
        return 200, {
            "city": self.manager.city,
            "incident_count": len(self.manager.incidents),
            "incidents": [to_json_dict(i) for i in self.manager.incidents.values()],
        }

    def handle_get_resources(self) -> tuple[int, dict[str, Any]]:
        """GET /api/resources"""
        return 200, {
            "city": self.manager.city,
            "resource_count": len(self.manager.resources),
            "resources": [to_json_dict(r) for r in self.manager.resources.values()],
        }

    def handle_get_decisions(self) -> tuple[int, dict[str, Any]]:
        """GET /api/decisions"""
        return 200, {
            "city": self.manager.city,
            "actions": [to_json_dict(a) for a in self.manager.actions],
            "response_plan": to_json_dict(self.manager.response_plan),
            "why_panel": self.manager.why_panel,
        }

    def handle_get_allocations(self) -> tuple[int, dict[str, Any]]:
        """GET /api/allocations"""
        opt = self.manager.optimization_result
        return 200, {
            "city": self.manager.city,
            "assignments": to_json_dict(opt.assignments) if opt else [],
            "unassigned_gaps": to_json_dict(opt.unassigned_incidents) if opt else [],
            "assignment_count": len(opt.assignments) if opt else 0,
            "gap_count": len(opt.unassigned_incidents) if opt else 0,
        }

    # ── State Update & Replan ────────────────────────────────────────────────

    def handle_state_update(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """POST /api/state/update"""
        if not body:
            return 400, {
                "status": "error",
                "code": "MISSING_REQUEST_BODY",
                "message": "JSON body required for state update.",
            }

        # Resource status update
        if "resource_id" in body and "status" in body:
            res = self.manager.resources.get(body["resource_id"])
            if not res:
                return 404, {
                    "status": "error",
                    "code": "RESOURCE_NOT_FOUND",
                    "message": f"Resource '{body['resource_id']}' not found.",
                }
            return self.handle_execute_input({
                "text": f"Resource {res.name} is {body['status']}",
            })

        # Zone weather/water update
        if "zone_id" in body:
            zone_id = body["zone_id"]
            rainfall = body.get("rainfall_mm_hr")
            water_level = body.get("water_level_m")
            text_parts = [f"Zone {zone_id} status update"]
            if rainfall is not None:
                text_parts.append(f"Rainfall {rainfall} mm/hr")
            if water_level is not None:
                text_parts.append(f"Water level {water_level} m")
            return self.handle_execute_input({
                "text": ", ".join(text_parts),
                "zone_id_hint": zone_id,
            })

        # Fallback text
        if "text" in body:
            return self.handle_execute_input(body)

        return 400, {
            "status": "error",
            "code": "INVALID_UPDATE_PAYLOAD",
            "message": "Specify 'resource_id' + 'status' or 'zone_id' + readings or 'text'.",
        }

    # ── Safe Simulation ──────────────────────────────────────────────────────

    def handle_simulation(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        """POST /api/simulation"""
        if not body:
            body = {"text": "General Simulation Scenario"}
        sim_res = self.manager.simulate(body)
        return 200, {
            "status": "success",
            "simulation": to_json_dict(sim_res),
        }

    # ── Reset ────────────────────────────────────────────────────────────────

    def handle_reset(self) -> tuple[int, dict[str, Any]]:
        """POST /api/reset"""
        self.manager.reset()
        return 200, {
            "status": "success",
            "message": "Operational simulation reset successfully.",
        }
