"""Unit tests for FlowShield V2 zone independence."""

from __future__ import annotations

from src.engine.state_manager import FlowShieldV2Manager


class TestZoneIndependence:
    """Test that Incident is independent of Zone and multiple incidents can coexist."""

    def test_multiple_incidents_in_same_zone(self):
        manager = FlowShieldV2Manager()
        initial_count = len(manager.incidents)

        # Ingest incident 1 in W12-C
        res1 = manager.execute_input("Flooding near civil hospital in W12-C, water depth 1.5m")
        assert res1["status"] == "success"
        inc1_id = res1["incident"]["id"]

        # Ingest incident 2 ALSO in W12-C (independent incident at market)
        res2 = manager.execute_input("Underground market in W12-C submerged, 20 people trapped")
        assert res2["status"] == "success"
        inc2_id = res2["incident"]["id"]

        # Verify distinct identities
        assert inc1_id != inc2_id
        assert inc1_id in manager.incidents
        assert inc2_id in manager.incidents
        assert len(manager.incidents) == initial_count + 2

        # Both have zone W12-C but are distinct
        assert manager.incidents[inc1_id].zone_id == "W12-C"
        assert manager.incidents[inc2_id].zone_id == "W12-C"
        assert manager.incidents[inc2_id].people_trapped == 20

    def test_incident_with_unknown_location_resolved_gracefully(self):
        manager = FlowShieldV2Manager()
        res = manager.execute_input(
            "Flash flood at Riverside Promenade, water is 2 meters deep, 10 people trapped"
        )
        assert res["status"] == "success"
        inc = res["incident"]
        assert inc["location"] == "Riverside Promenade"
        # Engine resolved an operational zone
        assert inc["zone_id"] is not None
        assert inc["people_trapped"] == 10
