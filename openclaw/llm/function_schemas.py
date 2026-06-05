"""
JSON schemas for LLM structured output validation.
"""

RECORD_SCHEMA = {
    "type": "object",
    "required": ["domain", "type", "entities", "description", "raw_input", "confidence"],
    "properties": {
        "domain": {"type": "string"},
        "type": {"type": "string"},
        "timestamp": {"type": ["string", "null"]},
        "entities": {"type": "object"},
        "amount": {"type": ["number", "null"]},
        "currency": {"type": "string", "default": "GBP"},
        "description": {"type": "string"},
        "raw_input": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

INTENT_SCHEMA = {
    "type": "object",
    "required": ["intents", "primary_intent", "confidence", "domain"],
    "properties": {
        "intents": {"type": "array", "items": {"type": "string"}},
        "primary_intent": {"type": "string"},
        "confidence": {"type": "number"},
        "domain": {"type": "string"},
    },
}

VALID_INTENTS = {
    "expense", "income", "task", "event", "inventory_update",
    "care_log", "education_record", "property_transaction", "general_note",
}

VALID_DOMAINS = {
    "finance", "property", "education", "healthcare",
    "inventory", "personal_life", "field_operations", "general",
}

FINANCE_CATEGORIES = [
    "Food & Drink", "Transport", "Utilities", "Shopping",
    "Entertainment", "Health", "Education", "Rent", "Salary",
    "Freelance", "Investment", "Other",
]
