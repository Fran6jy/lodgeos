"""Tests for the domain router."""

import pytest
from unittest.mock import MagicMock
from openclaw.core.router import Router


@pytest.fixture
def router():
    r = Router()
    finance = MagicMock()
    finance.domain = "finance"
    general = MagicMock()
    general.domain = "general"
    r.register("finance", finance)
    r.register("general", general)
    return r


class TestRouter:
    def test_routes_finance_domain(self, router):
        record = {"domain": "finance", "confidence": 0.9}
        plugin, domain = router.route(record)
        assert domain == "finance"

    def test_falls_back_on_low_confidence(self, router):
        record = {"domain": "finance", "confidence": 0.1}
        plugin, domain = router.route(record)
        assert domain == "general"

    def test_falls_back_unknown_domain(self, router):
        record = {"domain": "healthcare", "confidence": 0.9}
        plugin, domain = router.route(record)
        assert domain == "general"

    def test_no_fallback_raises(self):
        r = Router()
        finance = MagicMock()
        r.register("finance", finance)
        with pytest.raises(RuntimeError):
            r.route({"domain": "unknown", "confidence": 0.9})

    def test_multi_route_expense(self, router):
        record = {"domain": "finance", "intents": ["expense"], "confidence": 0.9}
        routes = router.route_multi(record)
        domains = [d for _, d in routes]
        assert "finance" in domains

    def test_list_domains(self, router):
        assert set(router.list_domains()) == {"finance", "general"}

    def test_intent_to_domain_mapping(self):
        assert Router._intent_to_domain("expense") == "finance"
        assert Router._intent_to_domain("income") == "finance"
        assert Router._intent_to_domain("care_log") == "healthcare"
        assert Router._intent_to_domain("education_record") == "education"
        assert Router._intent_to_domain("unknown_intent") == "general"
