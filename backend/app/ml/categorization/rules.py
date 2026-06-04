"""Rule-based transaction categorization — first stage of the cascade.

Cascade order is **rules → ML → fallback "Other"**. This module is the rules
layer. Each entry is `(compiled regex, category name)` where the regex
matches anywhere in the transaction's description (case-insensitive).

Romanian merchants are first-class — they're listed before global brands so
the bank-statement vocabulary takes precedence over generic strings.

Anonymized: no real-customer data, no PII. Patterns are based on common
Romanian retail/utility/online merchant names that any Romanian bank statement
will contain.
"""
from __future__ import annotations

import re

# (pattern_string, category) tuples. Compiled once at module load.
_RAW_RULES: list[tuple[str, str]] = [
    # ----- Groceries ----------------------------------------------------
    (r"\bcarrefour\b",                              "Groceries"),
    (r"\bauchan\b",                                 "Groceries"),
    (r"\bkaufland\b",                               "Groceries"),
    (r"\blidl\b",                                   "Groceries"),
    (r"\bmega\s*image\b",                           "Groceries"),
    (r"\bprofi\b",                                  "Groceries"),
    (r"\bpenny\b",                                  "Groceries"),
    (r"\bselgros\b",                                "Groceries"),
    (r"\bmetro\s+cash\b",                           "Groceries"),
    (r"\bla\s*doi\s*pasi\b",                        "Groceries"),
    (r"\bcora\b",                                   "Groceries"),
    (r"\bdm\s+(drogerie|markt)\b",                  "Groceries"),  # health & beauty mostly groceries-adjacent

    # ----- Restaurants & food delivery ---------------------------------
    (r"\bglovo\b",                                  "Restaurants"),
    (r"\bwolt\b",                                   "Restaurants"),
    (r"\btazz\b",                                   "Restaurants"),
    (r"\bfoodpanda\b",                              "Restaurants"),
    (r"\buber\s*eats\b",                            "Restaurants"),
    (r"\bbringo\b",                                 "Restaurants"),
    (r"\bmcdonald'?s?\b|mcdonalds",                 "Restaurants"),
    (r"\bkfc\b",                                    "Restaurants"),
    (r"\bsubway\b",                                 "Restaurants"),
    (r"\bstarbucks\b",                              "Restaurants"),
    (r"\bdomino'?s?\b",                             "Restaurants"),
    (r"\bpizza\s*hut\b",                            "Restaurants"),
    (r"\b(restaurant|bistro|cafenea|caffe|coffee\s*shop|pub)\b", "Restaurants"),
    (r"\b5\s*to\s*go\b",                            "Restaurants"),

    # ----- Transport (rideshare, public transit, fuel, parking) --------
    (r"\bbolt(?:\.eu)?\b",                          "Transport"),
    (r"\buber(?!\s*eats)\b",                        "Transport"),
    (r"\bfreenow\b",                                "Transport"),
    (r"\bblack\s*cab\b",                            "Transport"),
    (r"\bstb\b",                                    "Transport"),     # Bucharest public transport
    (r"\bmetrorex\b",                               "Transport"),
    (r"\bcfr\b",                                    "Transport"),     # railways
    (r"\bratb\b",                                   "Transport"),
    (r"\b(omv|petrom|mol|rompetrol|lukoil|socar)\b", "Transport"),    # fuel
    (r"\b(parcare|parking)\b",                      "Transport"),
    (r"\b(autostrada|rovinieta)\b",                 "Transport"),
    (r"\b(blue\s*air|wizz\s*air|tarom|ryanair|lufthansa|klm)\b", "Travel"),  # airlines → Travel

    # ----- Housing / rent ----------------------------------------------
    (r"\b(chirie|rent)\b",                          "Housing"),
    (r"\basocia[tț]ie\s+de\s+proprietari\b",        "Housing"),
    (r"\b(intretinere|întreținere)\b",              "Housing"),

    # ----- Utilities ---------------------------------------------------
    (r"\b(enel|e[\s-]?on|electrica|cez|hidroelectrica)\b", "Utilities"),
    (r"\b(engie|distrigaz|gaze)\b",                 "Utilities"),
    (r"\b(apa\s*nova|apa\s*regnault|raja)\b",       "Utilities"),
    (r"\b(rcs(?:\s|-)?rds|digi|upc|telekom|orange\s+(romania|fixed))\b", "Utilities"),
    (r"\bvodafone\b",                               "Utilities"),
    (r"\borange(?:\s+pre[\s-]*pay)?\b",             "Utilities"),

    # ----- Health & pharmacy -------------------------------------------
    (r"\b(farmacia|farmacie|pharmacy|catena|sensiblu|dona|help[\s-]?net)\b", "Health"),
    (r"\b(regina\s*maria|medicover|medlife|sanador|synevo)\b", "Health"),
    (r"\b(medical|clinica|dentist|stomatolog)\b",   "Health"),

    # ----- Entertainment ----------------------------------------------
    (r"\bcinema\s*city\b",                          "Entertainment"),
    (r"\b(steam|epic\s*games|playstation|xbox|nintendo|gog\.com)\b", "Entertainment"),
    (r"\b(eventim|biletmaster|iabilet)\b",          "Entertainment"),

    # ----- Subscriptions ----------------------------------------------
    (r"\bspotify\b",                                "Subscriptions"),
    (r"\bnetflix\b",                                "Subscriptions"),
    (r"\bhbo(?:\s+max)?\b",                         "Subscriptions"),
    (r"\bdisney\s*\+?\b",                           "Subscriptions"),
    (r"\byoutube\s*(premium|music)\b",              "Subscriptions"),
    (r"\b(google\s*one|google\s*storage)\b",        "Subscriptions"),
    (r"\b(icloud|apple\.com/bill)\b",               "Subscriptions"),
    (r"\b(github|notion|figma|linear|vercel|netlify|cloudflare|digitalocean)\b", "Subscriptions"),
    (r"\b(claude|anthropic|openai|chatgpt)\b",      "Subscriptions"),
    (r"\b(audible|kindle\s*unlimited)\b",           "Subscriptions"),

    # ----- Education ---------------------------------------------------
    (r"\b(udemy|coursera|edx|datacamp|pluralsight|frontendmasters)\b", "Education"),
    (r"\b(libraria|bookstore|carturesti)\b",        "Education"),
    (r"\b(universitate|facultate|colegiu|liceu)\b", "Education"),

    # ----- Travel ------------------------------------------------------
    (r"\b(booking\.com|airbnb|hotels?\.com|trivago|expedia)\b", "Travel"),
    (r"\b(hotel|hostel|motel|pensiune|vila)\b",     "Travel"),

    # ----- Salary / income --------------------------------------------
    (r"\b(salar(iu|y)|payroll|payslip|wage)\b",     "Salary"),
    (r"\bdirect\s+deposit\b",                       "Salary"),

    # ----- Transfer / bank moves --------------------------------------
    (r"\b(transfer|virament|incasare|încasare)\b",  "Transfer"),
    (r"\bp2p\b",                                    "Transfer"),
    (r"\b(revolut|bcr|brd|ing|raiffeisen|banca\s+transilvania|cec\s*bank|otp\s*bank)\b", "Transfer"),

    # ----- Investments -------------------------------------------------
    (r"\b(trading\s*212|etoro|interactive\s*brokers|degiro|xtb|revolut\s+invest)\b", "Investments"),
    (r"\b(coinbase|binance|kraken|crypto\.com)\b",  "Investments"),
    (r"\b(broker|brokerage|stock|equity|etf)\b",    "Investments"),
]


# Compile once. Each entry: (compiled_regex, category_name).
RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), c) for p, c in _RAW_RULES
]


def categorize_by_rules(description: str) -> str | None:
    """Return the first category whose rule matches the description, else None."""
    if not description:
        return None
    for pattern, category in RULES:
        if pattern.search(description):
            return category
    return None


def rule_count() -> int:
    """Total active rules. Used by tests to enforce the §7 lower bound."""
    return len(RULES)
