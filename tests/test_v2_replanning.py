"""Unit tests for FlowShield V2 replanning upon state and resource changes."""

from __future__ import annotations

from src.engine.state_manager import FlowShieldV2Manager
from src.models.resource import ResourceStatus


class TestReplanning:
    """Test that accepted state changes trigger synchronous replanning."""

    def test_resource_unavailable_triggers_reallocation(self):
        manager = FlowShieldV2Manager()
        initial_assignments = {a.resource_id: a.incident_id for a in manager.optimization_result.assignments}

        # Check that crew-alpha was initially assigned
        assert "crew-alpha" in initial_assignments

        # Operator reports crew-alpha unavailable
        res = manager.execute_input("Rescue Crew Alpha is unavailable due to mechanical failure")
        assert res["status"] == "success"
        assert res["intent"] == "resource_update"

        # Verify resource state updated
        assert manager.resources["crew-alpha"].status == ResourceStatus.UNAVAILABLE

        # Verify replanning ran: crew-alpha is no longer assigned
        new_assigned_resources = [a.resource_id for a in manager.optimization_result.assignments]
        assert "crew-alpha" not in new_assigned_resources

        # Verify another resource (e.g. crew-beta or crew-gamma) picked up the work
        assert len(new_assigned_resources) >= 1

    def test_new_urgent_incident_reorders_priorities(self):
        manager = FlowShieldV2Manager()

        # Ingest urgent report with 45 trapped people
        res = manager.execute_input("45 people are trapped in the basement of Metro Station in W12-C")
        assert res["status"] == "success"
        assert res["intent"] == "incident"

        # Verify new incident created
        new_inc_id = res["incident"]["id"]
        assert new_inc_id in manager.incidents
        assert manager.incidents[new_inc_id].people_trapped == 45

        # Verify #1 priority is now this new trapped incident
        top_priority = manager.priority_results[0]
        assert top_priority.incident_id == new_inc_id
        assert top_priority.level == "critical"
        assert "PEOPLE_TRAPPED" in top_priority.reason_codes

        # Verify response plan includes this incident
        assert manager.response_plan is not None
        plan_action_incs = [pa.incident_id for pa in manager.response_plan.plan_actions]
        assert new_inc_id in plan_action_incs
