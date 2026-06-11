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
    "₦": "NGN",
    "Fr": "CHF",
    "kr": "SEK",
    "zł": "PLN",
    "R": "ZAR",
}

CODE_SYMBOLS = {v: k for k, v in SYMBOL_MAP.items()}

# Spoken currency names ("5,000 naira", "20 pounds", "10 bucks").
WORD_MAP = {
    "naira": "NGN",
    "pound": "GBP", "pounds": "GBP", "quid": "GBP",
    "dollar": "USD", "dollars": "USD", "bucks": "USD",
    "euro": "EUR", "euros": "EUR",
    "rupee": "INR", "rupees": "INR",
    "cedi": "GHS", "cedis": "GHS",
    "shilling": "KES", "shillings": "KES",
    "rand": "ZAR",
}


def extract_amount_and_currency(text: str, default_currency: str = "GBP") -> Tuple[Optional[float], str]:
    """Extract numeric amount and ISO currency code from a string."""
    text = text.strip()

    # Match patterns like £4.50, $100, ₦5,000, 50 GBP, USD 100, "5,000 naira"
    word_alt = "|".join(WORD_MAP)
    patterns = [
        r"([£$€¥₹₩₦])(\d+(?:[.,]\d+)*)",  # symbol before
        r"(\d+(?:[.,]\d+)*)\s*([£$€¥₹₩₦])",  # symbol after
        r"(\d+(?:[.,]\d+)*)\s*(GBP|USD|EUR|JPY|INR|NGN|CHF|SEK|PLN|ZAR|AUD|CAD|NZD|GHS|KES)",  # code after
        r"(GBP|USD|EUR|JPY|INR|NGN|CHF|SEK|PLN|ZAR|AUD|CAD|NZD|GHS|KES)\s*(\d+(?:[.,]\d+)*)",  # code before
        rf"(\d+(?:[.,]\d+)*)\s*({word_alt})\b",  # spoken name after ("5,000 naira")
    ]

    def _to_code(token: str) -> str:
        return SYMBOL_MAP.get(token) or WORD_MAP.get(token.lower()) or token.upper()

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            g1, g2 = match.group(1), match.group(2)
            # Determine which is amount vs currency
            try:
                amount = float(g1.replace(",", ""))
                return amount, _to_code(g2)
            except ValueError:
                try:
                    amount = float(g2.replace(",", ""))
                    return amount, _to_code(g1)
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
