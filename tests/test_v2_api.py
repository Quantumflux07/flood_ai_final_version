"""Integration tests for FlowShield V2 REST API endpoints."""

from __future__ import annotations

from src.api.handlers import FlowShieldAPIHandler
from src.engine.state_manager import FlowShieldV2Manager


class TestV2APIEndpoints:
    """Test all V2 API handlers."""

    def setup_method(self):
        self.manager = FlowShieldV2Manager()
        self.api = FlowShieldAPIHandler(manager=self.manager)

    def test_post_analyze_input_accept(self):
        code, data = self.api.handle_analyze_input({
            "text": "37 people are trapped near the hospital in W12-C",
        })
        assert code == 200
        assert data["status"] == "accept"
        assert data["envelope"]["facts"]["people_trapped"] == 37

    def test_post_analyze_input_clarify(self):
        code, data = self.api.handle_analyze_input({
            "text": "Send help to the school",
        })
        assert code == 200
        assert data["status"] == "clarify"
        assert len(data["envelope"]["missing_information"]) > 0

    def test_post_analyze_input_reject(self):
        code, data = self.api.handle_analyze_input({
            "text": "Earthquake in Ahmedabad magnitude 6.5",
        })
        assert code == 200
        assert data["status"] == "reject"

    def test_post_analyze_input_missing_text(self):
        code, data = self.api.handle_analyze_input({})
        assert code == 400
        assert data["code"] == "MISSING_INPUT_TEXT"

    def test_post_execute_input_incident(self):
        code, data = self.api.handle_execute_input({
            "text": "25 people trapped at City High School in W12-N",
        })
        assert code == 200
        assert data["status"] == "success"
        assert data["intent"] == "incident"
        assert "incident" in data
        assert "allocations" in data
        assert "response_plan" in data

    def test_post_execute_input_resource_update(self):
        code, data = self.api.handle_execute_input({
            "text": "Pump Unit A is unavailable",
        })
        assert code == 200
        assert data["status"] == "success"
        assert data["new_status"] == "unavailable"

    def test_post_execute_input_query(self):
        code, data = self.api.handle_execute_input({
            "text": "Which incident is most urgent?",
        })
        assert code == 200
        assert data["status"] == "success"
        assert data["intent"] == "query"
        assert "urgent" in data["answer"].lower()

    def test_get_state(self):
        code, data = self.api.handle_get_state()
        assert code == 200
        assert "overall_severity" in data
        assert "zones" in data
        assert "incidents" in data
        assert "resources" in data

    def test_get_incidents(self):
        code, data = self.api.handle_get_incidents()
        assert code == 200
        assert "incidents" in data
        assert data["incident_count"] >= 1

    def test_get_resources(self):
        code, data = self.api.handle_get_resources()
        assert code == 200
        assert "resources" in data
        assert data["resource_count"] == 5

    def test_get_decisions(self):
        code, data = self.api.handle_get_decisions()
        assert code == 200
        assert "actions" in data
        assert "response_plan" in data

    def test_get_allocations(self):
        code, data = self.api.handle_get_allocations()
        assert code == 200
        assert "assignments" in data
        assert "assignment_count" in data

    def test_post_state_update(self):
        code, data = self.api.handle_state_update({
            "zone_id": "W12-C",
            "rainfall_mm_hr": 140.0,
            "water_level_m": 2.5,
        })
        assert code == 200
        assert data["status"] == "success"

    def test_post_simulation(self):
        code, data = self.api.handle_simulation({
            "text": "What happens if Pump Unit A fails?",
            "resource_unavailable": "pump-A",
        })
        assert code == 200
        assert data["status"] == "success"
        assert data["simulation"]["live_state_modified"] is False

    def test_post_reset(self):
        code, data = self.api.handle_reset()
        assert code == 200
        assert data["status"] == "success"
