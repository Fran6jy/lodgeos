"""Schema validation for OpenClaw records."""

from typing import Any, Dict, List, Tuple


REQUIRED_FIELDS = {"domain", "type", "entities", "description", "raw_input", "confidence"}
VALID_INTENTS = {
    "expense", "income", "task", "event", "inventory_update",
    "care_log", "education_record", "property_transaction", "general_note",
}
VALID_DOMAINS = {
    "finance", "property", "education", "healthcare",
    "inventory", "personal_life", "field_operations", "general",
}


class ValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class SchemaValidator:
    """Validates records against the OpenClaw record contract."""

    def validate(self, record: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Return (is_valid, list_of_errors)."""
        errors = []

        # Required fields
        for field in REQUIRED_FIELDS:
            if field not in record:
                errors.append(f"Missing required field: {field}")

        # Type checks
        if "confidence" in record:
            c = record["confidence"]
            if not isinstance(c, (int, float)) or not (0.0 <= c <= 1.0):
                errors.append(f"confidence must be float 0–1, got {c!r}")

        if "domain" in record and record["domain"] not in VALID_DOMAINS:
            errors.append(f"Unknown domain: {record['domain']!r}")

        if "type" in record and record["type"] not in VALID_INTENTS:
            errors.append(f"Unknown type: {record['type']!r}")

        if "amount" in record and record["amount"] is not None:
            if not isinstance(record["amount"], (int, float)):
                errors.append(f"amount must be numeric, got {type(record['amount']).__name__}")
            # Negative amounts are permitted: they represent refunds/returns that
            # offset prior spend in the ledger (see document-parsing rule 5).

        if "entities" in record and not isinstance(record["entities"], dict):
            errors.append("entities must be a dict")

        return len(errors) == 0, errors

    def validate_or_raise(self, record: Dict[str, Any]) -> None:
        valid, errors = self.validate(record)
        if not valid:
            raise ValidationError(errors)
