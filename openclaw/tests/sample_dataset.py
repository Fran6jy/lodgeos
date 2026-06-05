"""
Sample dataset for regression testing and demos.

Each entry: (input_message, expected_type, expected_domain, expected_amount_approx)
"""

SAMPLE_MESSAGES = [
    # --- Expenses ---
    ("Spent £4.50 at Nero for coffee",              "expense", "finance", 4.50),
    ("Coffee at Costa £3.20",                        "expense", "finance", 3.20),
    ("Paid £45 for Uber to the airport",             "expense", "finance", 45.00),
    ("Bought groceries at Tesco £67.30",             "expense", "finance", 67.30),
    ("Lunch £12 at Pret",                            "expense", "finance", 12.00),
    ("Netflix subscription £15.99",                  "expense", "finance", 15.99),
    ("Electric bill £120",                           "expense", "finance", 120.00),
    ("Amazon order £34.99",                          "expense", "finance", 34.99),
    ("Petrol £55",                                   "expense", "finance", 55.00),
    ("Gym membership £45 monthly",                   "expense", "finance", 45.00),
    ("Train to London £32.50",                       "expense", "finance", 32.50),
    ("Dentist £80",                                  "expense", "finance", 80.00),
    ("Spent 20 dollars on coffee",                   "expense", "finance", 20.00),
    ("Dinner at Wagamama £68",                       "expense", "finance", 68.00),
    ("Parking ticket £30",                           "expense", "finance", 30.00),

    # --- Income ---
    ("Received salary £3200",                        "income", "finance", 3200.00),
    ("Client paid invoice £500",                     "income", "finance", 500.00),
    ("Freelance project payment £1500",              "income", "finance", 1500.00),
    ("Got paid £250 for consulting",                 "income", "finance", 250.00),
    ("Dividend payment £45.20",                      "income", "finance", 45.20),

    # --- Edge cases ---
    ("Bought coffee",                                "expense", "finance", None),   # no amount
    ("Something happened today",                     "general_note", "general", None),
]

EXPECTED_CATEGORIES = {
    "Spent £4.50 at Nero for coffee":   "Food & Drink",
    "Paid £45 for Uber to the airport": "Transport",
    "Bought groceries at Tesco £67.30": "Groceries",
    "Netflix subscription £15.99":      "Entertainment",
    "Electric bill £120":               "Utilities",
    "Dentist £80":                      "Health",
    "Salary £3200":                     "Salary",
    "Petrol £55":                       "Transport",
}
