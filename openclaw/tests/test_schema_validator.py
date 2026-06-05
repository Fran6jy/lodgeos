"""Tests for schema validation."""

import pytest
from openclaw.core.schema_validator import SchemaValidator, ValidationError


@pytest.fixture
def validator():
    return SchemaValidator()


@pytest.fixture
def valid_record():
    return {
        "domain": "finance",
        "type": "expense",
        "entities": {"category": "Food & Drink"},
        "amount": 4.50,
        "currency": "GBP",
        "description": "Coffee at Nero",
        "raw_input": "Spent £4.50 at Nero",
        "confidence": 0.92,
        "timestamp": "2026-06-04T10:00:00",
    }


class TestSchemaValidator:
    def test_valid_record_passes(self, validator, valid_record):
        ok, errors = validator.validate(valid_record)
        assert ok
        assert errors == []

    def test_missing_required_field(self, validator, valid_record):
        del valid_record["domain"]
        ok, errors = validator.validate(valid_record)
        assert not ok
        assert any("domain" in e for e in errors)

    def test_invalid_confidence_range(self, validator, valid_record):
        valid_record["confidence"] = 1.5
        ok, errors = validator.validate(valid_record)
        assert not ok

    def test_negative_amount_allowed_for_refunds(self, validator, valid_record):
        # Refunds/returns are stored as negative amounts to offset prior spend.
        valid_record["amount"] = -10.0
        ok, errors = validator.validate(valid_record)
        assert ok

    def test_none_amount_is_valid(self, validator, valid_record):
        valid_record["amount"] = None
        ok, errors = validator.validate(valid_record)
        assert ok

    def test_unknown_domain_fails(self, validator, valid_record):
        valid_record["domain"] = "space_travel"
        ok, errors = validator.validate(valid_record)
        assert not ok

    def test_validate_or_raise_throws(self, validator):
        with pytest.raises(ValidationError):
            validator.validate_or_raise({"confidence": 999})

    def test_entities_must_be_dict(self, validator, valid_record):
        valid_record["entities"] = "not a dict"
        ok, errors = validator.validate(valid_record)
        assert not ok
