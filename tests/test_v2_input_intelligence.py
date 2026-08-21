"""Unit tests for Grok Input Intelligence gateway, fallback parser, and validation gate."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.intelligence.fallback import DeterministicInputFallback
from src.intelligence.gateway import GrokInputGateway
from src.intelligence.grok_client import GrokClient, GrokConfig, GrokUnavailable
from src.intelligence.models import GateStatus, InputIntent


class TestDeterministicFallbackClassification:
    """Test all 7 required classifications through deterministic NLP fallback."""

    def setup_method(self):
        self.fallback = DeterministicInputFallback()

    def test_incident_classification(self):
        env = self.fallback.parse("37 people are trapped near the hospital in W12-C")
        assert env.intent == InputIntent.INCIDENT
        assert env.status == GateStatus.ACCEPT
        assert env.facts.people_trapped == 37
        assert env.facts.critical_facility == "Hospital"
        assert env.facts.zone_id == "W12-C"
        assert env.source == "fallback"

    def test_resource_update_classification(self):
        env = self.fallback.parse("Rescue Crew Alpha is unavailable")
        assert env.intent == InputIntent.RESOURCE_UPDATE
        assert env.status == GateStatus.ACCEPT
        assert env.facts.resource_status == "unavailable"
        assert env.facts.resource_name is not None
        assert env.source == "fallback"

    def test_state_update_classification(self):
        env = self.fallback.parse("Rainfall increased to 180 mm/hr in W12-N")
        assert env.intent == InputIntent.STATE_UPDATE
        assert env.status == GateStatus.ACCEPT
        assert env.facts.rainfall_mm_hr == 180.0
        assert env.facts.zone_id == "W12-N"
        assert env.source == "fallback"

    def test_simulation_classification(self):
        env = self.fallback.parse("What happens if Pump Unit A fails?")
        assert env.intent == InputIntent.SIMULATION
        assert env.status == GateStatus.ACCEPT
        assert env.requested_operation == "simulation_dry_run"
        assert env.source == "fallback"

    def test_query_classification(self):
        env = self.fallback.parse("Which incident is most urgent?")
        assert env.intent == InputIntent.QUERY
        assert env.status == GateStatus.ACCEPT
        assert env.source == "fallback"

    def test_clarification_required_vague_school(self):
        env = self.fallback.parse("Send help to the school")
        assert env.intent == InputIntent.CLARIFICATION_REQUIRED
        assert env.status == GateStatus.CLARIFY
        assert len(env.missing_information) > 0
        assert env.clarification_prompt is not None

    def test_clarification_required_garbage_hello(self):
        env = self.fallback.parse("hello")
        assert env.intent == InputIntent.CLARIFICATION_REQUIRED
        assert env.status == GateStatus.CLARIFY

    def test_unsupported_earthquake_rejection(self):
        env = self.fallback.parse("There was an earthquake in Ahmedabad")
        assert env.intent == InputIntent.UNSUPPORTED
        assert env.status == GateStatus.REJECT
        assert env.rejection_reason is not None
        assert "flood" in env.rejection_reason.lower()


class TestGrokClientAndGateway:
    """Test GrokClient configuration, error handling and gateway fallback."""

    def test_unconfigured_client_raises_unavailable(self):
        client = GrokClient(config=GrokConfig(api_key=""))
        assert not client.is_configured
        try:
            client.complete("hello")
            assert False, "Should have raised GrokUnavailable"
        except GrokUnavailable as exc:
            assert "GROK_API_KEY" in str(exc)

    def test_gateway_fallback_when_grok_unconfigured(self):
        client = GrokClient(config=GrokConfig(api_key=""))
        gateway = GrokInputGateway(grok_client=client)
        env = gateway.process("37 people trapped near hospital in W12-C")
        assert env.status == GateStatus.ACCEPT
        assert env.source == "fallback"
        assert env.facts.people_trapped == 37

    def test_gateway_grok_success_sets_grok_source(self):
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.complete.return_value = (
            '{"intent": "incident", "domain": "flood_response", "status": "accept", '
            '"confidence": 0.98, "facts": {"people_trapped": 37, "critical_facility": "Hospital", '
            '"zone_id": "W12-C"}, "location": "Civil Hospital", "affected_areas": ["W12-C"], '
            '"missing_information": []}'
        )

        gateway = GrokInputGateway(grok_client=mock_client)
        env = gateway.process("37 people trapped near hospital in W12-C")

        assert env.status == GateStatus.ACCEPT
        assert env.source == "grok"
        assert env.facts.people_trapped == 37
        assert env.facts.critical_facility == "Hospital"

    def test_gateway_falls_back_on_malformed_json(self):
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client.complete.return_value = "This is not valid JSON string"

        gateway = GrokInputGateway(grok_client=mock_client)
        env = gateway.process("37 people trapped near hospital in W12-C")

        assert env.status == GateStatus.ACCEPT
        assert env.source == "fallback"
        assert env.facts.people_trapped == 37
