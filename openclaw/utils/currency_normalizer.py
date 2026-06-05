"""Currency detection and normalisation utilities."""

import re
from typing import Tuple, Optional

SYMBOL_MAP = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
    "₹": "INR",
    "₩": "KRW",
    "Fr": "CHF",
    "kr": "SEK",
    "zł": "PLN",
    "R": "ZAR",
}

CODE_SYMBOLS = {v: k for k, v in SYMBOL_MAP.items()}


def extract_amount_and_currency(text: str, default_currency: str = "GBP") -> Tuple[Optional[float], str]:
    """Extract numeric amount and ISO currency code from a string."""
    text = text.strip()

    # Match patterns like £4.50, $100, €20.00, 50 GBP, USD 100
    patterns = [
        r"([£$€¥₹₩])(\d+(?:[.,]\d+)?)",  # symbol before
        r"(\d+(?:[.,]\d+)?)\s*([£$€¥₹₩])",  # symbol after
        r"(\d+(?:[.,]\d+)?)\s*(GBP|USD|EUR|JPY|INR|CHF|SEK|PLN|ZAR|AUD|CAD|NZD)",  # code after
        r"(GBP|USD|EUR|JPY|INR|CHF|SEK|PLN|ZAR|AUD|CAD|NZD)\s*(\d+(?:[.,]\d+)?)",  # code before
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            g1, g2 = match.group(1), match.group(2)
            # Determine which is amount vs currency
            try:
                amount = float(g1.replace(",", ""))
                currency = SYMBOL_MAP.get(g2, g2.upper())
                return amount, currency
            except ValueError:
                try:
                    amount = float(g2.replace(",", ""))
                    currency = SYMBOL_MAP.get(g1, g1.upper())
                    return amount, currency
                except ValueError:
                    continue

    # Bare number fallback
    bare = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if bare:
        return float(bare.group(1).replace(",", "")), default_currency

    return None, default_currency


def format_amount(amount: float, currency: str = "GBP") -> str:
    symbol = CODE_SYMBOLS.get(currency, currency + " ")
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"
