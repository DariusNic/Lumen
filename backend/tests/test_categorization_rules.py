"""Rule-based categorization sanity. Plan §C.2 expects ≥60 patterns."""
import pytest

from app.ml.categorization.predict import categorize
from app.ml.categorization.rules import categorize_by_rules, rule_count


def test_at_least_60_rules():
    """Minimum corpus of 60–80 patterns."""
    assert rule_count() >= 60


@pytest.mark.parametrize(
    "description,expected",
    [
        # Romanian groceries
        ("CARREFOUR BANEASA", "Groceries"),
        ("Profi Floreasca", "Groceries"),
        ("KAUFLAND PROMENADA", "Groceries"),
        ("LIDL DRUMUL TABEREI", "Groceries"),
        ("Mega Image Plata POS", "Groceries"),
        # Restaurants / delivery
        ("GLOVO Bucuresti", "Restaurants"),
        ("Wolt courier fee", "Restaurants"),
        ("foodpanda online order", "Restaurants"),
        ("MCDONALDS Cotroceni", "Restaurants"),
        ("Starbucks Lipscani", "Restaurants"),
        # Transport
        ("BOLT.EU/O abonament", "Transport"),
        ("STB Abonament Lunar", "Transport"),
        ("OMV Otopeni", "Transport"),
        ("ROMPETROL FILL UP", "Transport"),
        ("PARCARE PIATA VICTORIEI", "Transport"),
        # Travel
        ("Wizz Air booking", "Travel"),
        ("BLUE AIR ticket", "Travel"),
        # Housing
        ("CHIRIE Aviatorilor 28", "Housing"),
        ("Asociatie de proprietari Bloc 5", "Housing"),
        # Utilities
        ("ENEL ENERGIE factura aprilie", "Utilities"),
        ("Vodafone abonament", "Utilities"),
        ("DIGI internet", "Utilities"),
        ("Apa Nova plata", "Utilities"),
        # Health
        ("FARMACIA TEI", "Health"),
        ("CATENA STORE 14", "Health"),
        ("REGINA MARIA consultatie", "Health"),
        # Subscriptions
        ("SPOTIFY*PREMIUM family", "Subscriptions"),
        ("NETFLIX.COM monthly", "Subscriptions"),
        ("HBO MAX", "Subscriptions"),
        ("github.com pro", "Subscriptions"),
        ("anthropic api credits", "Subscriptions"),
        # Education
        ("UDEMY course", "Education"),
        ("CARTURESTI Verona", "Education"),
        # Salary / income
        ("SALARIU ACME SRL", "Salary"),
        ("Direct Deposit ACME", "Salary"),
        # Transfer
        ("Transfer Revolut to BCR", "Transfer"),
        ("INCASARE de la Ion", "Transfer"),
        # Investments
        ("Coinbase deposit", "Investments"),
        ("Trading 212 buy AAPL", "Investments"),
    ],
)
def test_rules_hit_expected_category(description, expected):
    assert categorize_by_rules(description) == expected


def test_unknown_description_returns_none_from_rules():
    assert categorize_by_rules("Asd qwerty random text") is None


def test_cascade_falls_back_to_other(client):
    # client fixture not strictly needed but proves the cascade works in app context
    assert categorize("Asd qwerty random text") == "Other"


def test_cascade_returns_rule_hit_when_match(client):
    assert categorize("Glovo lunch") == "Restaurants"


def test_empty_description_returns_other():
    assert categorize("") == "Other"


def test_case_insensitive():
    assert categorize_by_rules("carrefour") == "Groceries"
    assert categorize_by_rules("CARREFOUR") == "Groceries"
    assert categorize_by_rules("CarReFoUr") == "Groceries"


def test_uber_eats_is_restaurants_not_transport():
    assert categorize_by_rules("UBER EATS pizza") == "Restaurants"


def test_uber_ride_is_transport():
    assert categorize_by_rules("UBER ride downtown") == "Transport"
