"""Known banks and merchants, recognised from an account name or a transaction memo (D-066).

The UI draws each as a tile in the brand's colour with a short mark. Not logos: those are
trademarks, and CLAUDE.md §10 asks for a licensed source or monogram tiles. Swapping in real
logos later means changing the web's BrandTile only; the keys here stay.

ponytail: keyword matching on the memo. Add a merchant column when statement import (P5) gives
cleaner payee names than hand-typed memos.
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class Brand:
    key: str
    name: str
    kind: Literal["bank", "merchant"]
    color: str  # tile background
    mark: str  # one to three characters on the tile
    words: tuple[str, ...]  # matched as whole words, case and punctuation ignored


def _b(
    kind: Literal["bank", "merchant"], key: str, name: str, color: str, mark: str, *words: str
) -> Brand:
    return Brand(key, name, kind, color, mark, words or (name,))


BRANDS: tuple[Brand, ...] = (
    # Banks and card issuers, with card product names that point to their issuer
    _b("bank", "chase", "Chase", "#117aca", "C", "chase", "sapphire", "freedom"),
    _b(
        "bank",
        "bankofamerica",
        "Bank of America",
        "#e31837",
        "BA",
        "bank of america",
        "bofa",
        "customized cash",
        "premium rewards",
    ),
    _b(
        "bank",
        "wellsfargo",
        "Wells Fargo",
        "#d71e28",
        "WF",
        "wells fargo",
        "active cash",
        "autograph",
    ),
    _b("bank", "citi", "Citi", "#056dae", "Ci", "citi", "citibank", "double cash", "custom cash"),
    _b(
        "bank",
        "capitalone",
        "Capital One",
        "#004879",
        "C1",
        "capital one",
        "venture",
        "quicksilver",
        "savor",
        "savorone",
    ),
    _b(
        "bank", "amex", "American Express", "#016fd0", "AX", "amex", "american express", "blue cash"
    ),
    _b("bank", "discover", "Discover", "#ff6000", "D"),
    _b("bank", "usbank", "U.S. Bank", "#0c2074", "US", "us bank", "u s bank", "altitude"),
    _b("bank", "pnc", "PNC", "#ef7622", "P"),
    _b("bank", "td", "TD Bank", "#34a853", "TD", "td", "td bank"),
    _b("bank", "ally", "Ally", "#650360", "A"),
    _b("bank", "applecard", "Apple Card", "#1d1d1f", "AC", "apple card"),
    _b("bank", "schwab", "Charles Schwab", "#00a0df", "S", "schwab"),
    _b("bank", "marcus", "Marcus", "#1a2b49", "M"),
    _b("bank", "sofi", "SoFi", "#00a2c7", "So"),
    _b("bank", "navyfederal", "Navy Federal", "#003a70", "NF", "navy federal"),
    # Card networks last: an issuer named in the same card name wins (first match).
    _b("bank", "visa", "Visa", "#1a1f71", "V"),
    _b("bank", "mastercard", "Mastercard", "#eb001b", "MC"),
    # Shops and groceries
    _b("merchant", "target", "Target", "#cc0000", "◎"),
    _b("merchant", "walmart", "Walmart", "#0071ce", "W"),
    _b("merchant", "costco", "Costco", "#e31837", "Co"),
    _b("merchant", "traderjoes", "Trader Joe's", "#c8102e", "TJ", "trader joes", "trader joe"),
    _b("merchant", "wholefoods", "Whole Foods", "#00674b", "WF", "whole foods"),
    _b("merchant", "bestbuy", "Best Buy", "#0046be", "BB", "best buy"),
    _b("merchant", "amazon", "Amazon", "#ff9900", "a", "amazon", "amzn"),
    _b("merchant", "cvs", "CVS", "#cc0000", "CVS"),
    _b("merchant", "walgreens", "Walgreens", "#e31837", "Wg"),
    _b("merchant", "apple", "Apple", "#1d1d1f", "A", "apple", "apple com"),
    # Food and coffee
    _b("merchant", "subway", "Subway", "#008938", "S"),
    _b("merchant", "starbucks", "Starbucks", "#00704a", "Sb"),
    _b("merchant", "dunkin", "Dunkin'", "#ff671f", "D", "dunkin", "dunkin donuts"),
    _b("merchant", "mcdonalds", "McDonald's", "#da291c", "M", "mcdonalds", "mcdonald"),
    _b("merchant", "chipotle", "Chipotle", "#441500", "Ch"),
    _b("merchant", "chickfila", "Chick-fil-A", "#e51636", "CfA", "chick fil a"),
    _b("merchant", "doordash", "DoorDash", "#ff3008", "DD"),
    _b("merchant", "ubereats", "Uber Eats", "#06c167", "UE", "uber eats"),
    # Getting around
    _b("merchant", "mta", "MTA", "#0039a6", "M", "mta", "omny", "metrocard"),
    _b("merchant", "njtransit", "NJ Transit", "#1a3a6e", "NJT", "nj transit", "njt"),
    _b("merchant", "uber", "Uber", "#000000", "U"),
    _b("merchant", "lyft", "Lyft", "#ff00bf", "L"),
    # Subscriptions
    _b("merchant", "netflix", "Netflix", "#e50914", "N"),
    _b("merchant", "spotify", "Spotify", "#1db954", "Sp"),
    _b("merchant", "claude", "Claude", "#d97757", "C", "claude", "anthropic"),
    _b("merchant", "gemini", "Gemini", "#4285f4", "G", "gemini"),
    _b("merchant", "chatgpt", "ChatGPT", "#10a37f", "AI", "chatgpt", "openai"),
    _b("merchant", "youtube", "YouTube", "#ff0000", "▶", "youtube"),
)


def _norm(text: str) -> str:
    """'Trader Joe's #552' -> ' trader joes 552 ': apostrophes dropped, other punctuation is a
    space, padded so a word match is a plain substring test."""
    return (
        " "
        + " ".join(
            re.sub(r"[^a-z0-9]+", " ", text.lower().replace("'", "").replace("’", "")).split()
        )
        + " "
    )


_WORDS = [(b, _norm(w)) for b in BRANDS for w in b.words]


def _find(text: str, kind: str) -> Brand | None:
    t = _norm(text)
    return next((b for b, w in _WORDS if b.kind == kind and w in t), None)


def merchant_of(memo: str) -> Brand | None:
    return _find(memo, "merchant")


def bank_of(account_name: str) -> Brand | None:
    return _find(account_name, "bank")


class BrandOut(BaseModel):
    """What the API sends: enough for the web to draw the tile."""

    key: str
    name: str
    color: str
    mark: str


def brand_out(brand: Brand | None) -> BrandOut | None:
    if brand is None:
        return None
    return BrandOut(key=brand.key, name=brand.name, color=brand.color, mark=brand.mark)
