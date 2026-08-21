"""Unit tests for FlowShield V2 simulation safety and state isolation."""

from __future__ import annotations

from src.engine.state_manager import FlowShieldV2Manager
from src.models.resource import ResourceStatus


class TestSimulationSafety:
    """Verify that simulations run on deep snapshots and NEVER mutate live state."""

    def test_simulation_does_not_mutate_live_resources(self):
        manager = FlowShieldV2Manager()

        # Pump Unit A is initially AVAILABLE in live state
        assert manager.resources["pump-A"].status == ResourceStatus.AVAILABLE
        initial_live_assignments = len(manager.optimization_result.assignments)

        # Run what-if simulation: "What happens if Pump Unit A fails?"
        sim_res = manager.simulate({
            "text": "What happens if Pump Unit A fails?",
            "resource_unavailable": "pump-A",
        })

        assert sim_res["live_state_modified"] is False
        assert sim_res["scenario"] == "What happens if Pump Unit A fails?"
        assert "assignments" in sim_res
        assert "response_plan" in sim_res

        # CRITICAL ASSERTION: Live state resource must REMAIN available!
        assert manager.resources["pump-A"].status == ResourceStatus.AVAILABLE

        # Live assignments count must NOT have changed
        assert len(manager.optimization_result.assignments) == initial_live_assignments

    def test_simulation_via_natural_language_execute(self):
        manager = FlowShieldV2Manager()
        assert manager.resources["pump-A"].status == ResourceStatus.AVAILABLE

        res = manager.execute_input("What happens if Pump Unit A fails?")
        assert res["status"] == "success"
        assert res["intent"] == "simulation"
        assert "simulation" in res

        # Verify live state remains untouched
        assert manager.resources["pump-A"].status == ResourceStatus.AVAILABLE
