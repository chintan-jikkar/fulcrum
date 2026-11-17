"""Brand recognition from a memo or an account name (D-066)."""

import pytest

from app.brands import bank_of, merchant_of


@pytest.mark.parametrize(
    ("memo", "key"),
    [
        ("Target", "target"),
        ("TARGET T-1234 BROOKLYN", "target"),
        ("Trader Joe's", "traderjoes"),
        ("TRADER JOES #552", "traderjoes"),
        ("Whole Foods Market", "wholefoods"),
        ("Amazon.com order", "amazon"),
        ("AMZN Mktp US", "amazon"),
        ("Best Buy", "bestbuy"),
        ("Costco gas", "costco"),
        ("Walmart Supercenter", "walmart"),
        ("Subway lunch", "subway"),
        ("MTA OMNY", "mta"),
        ("NJ Transit monthly", "njtransit"),
        ("Netflix", "netflix"),
        ("Claude Pro", "claude"),
        ("Anthropic", "claude"),
        ("Google Gemini Advanced", "gemini"),
        ("Starbucks", "starbucks"),
        ("Dunkin'", "dunkin"),
        ("Dunkin Donuts", "dunkin"),
    ],
)
def test_merchant_of_recognises_the_brand(memo: str, key: str) -> None:
    brand = merchant_of(memo)
    assert brand is not None and brand.key == key


@pytest.mark.parametrize("memo", ["", "Bagels", "Rent", "Subwaysurfers", "Targets met", "Chase"])
def test_merchant_of_leaves_the_rest_alone(memo: str) -> None:
    assert merchant_of(memo) is None


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Chase Checking", "chase"),
        ("Bank of America Savings", "bankofamerica"),
        ("Amex Gold", "amex"),
        ("American Express", "amex"),
        ("Apple Card", "applecard"),
        ("Capital One Venture", "capitalone"),
    ],
)
def test_bank_of_recognises_the_bank(name: str, key: str) -> None:
    brand = bank_of(name)
    assert brand is not None and brand.key == key


def test_bank_of_leaves_made_up_names_alone() -> None:
    assert bank_of("Harbor Checking") is None
    assert bank_of("Netflix") is None  # merchants are not banks


def test_every_brand_has_a_colour_and_a_short_mark() -> None:
    from app.brands import BRANDS

    assert len({b.key for b in BRANDS}) == len(BRANDS)
    for b in BRANDS:
        assert b.color.startswith("#") and len(b.color) == 7, b.key
        assert 1 <= len(b.mark) <= 3, b.key


@pytest.mark.parametrize(
    ("card", "key"),
    [
        ("Sapphire Preferred", "chase"),
        ("Freedom Unlimited", "chase"),
        ("Venture X", "capitalone"),
        ("Quicksilver", "capitalone"),
        ("SavorOne", "capitalone"),
        ("Blue Cash Everyday", "amex"),
        ("Double Cash", "citi"),
        ("Custom Cash", "citi"),
        ("Active Cash", "wellsfargo"),
        ("Autograph", "wellsfargo"),
        ("Customized Cash Rewards", "bankofamerica"),
        ("Altitude Go", "usbank"),
        ("Discover it", "discover"),
        # The issuer wins over the network; the network is the fallback.
        ("Chase Sapphire Visa", "chase"),
        ("My Visa", "visa"),
        ("Work Mastercard", "mastercard"),
    ],
)
def test_bank_of_knows_card_products_and_networks(card: str, key: str) -> None:
    brand = bank_of(card)
    assert brand is not None and brand.key == key


def test_card_words_are_not_merchants() -> None:
    assert merchant_of("Visa") is None
    assert merchant_of("Freedom Tower tickets") is None
