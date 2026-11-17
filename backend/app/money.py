"""Money at the serialization boundary (CLAUDE.md §6): integer minor units in, text out."""

from pydantic import BaseModel


def display(minor: int) -> str:
    """USD only in v1 (§14). 123456 -> "$1,234.56", -4000 -> "-$40.00"."""
    dollars, cents = divmod(abs(minor), 100)
    return f"{'-' if minor < 0 else ''}${dollars:,}.{cents:02d}"


class Money(BaseModel):
    """Every amount the API returns: the exact integer and the string the UI shows as is."""

    minor: int
    display: str


def money(minor: int) -> Money:
    return Money(minor=minor, display=display(minor))


def percent(bps: int) -> str:
    """Basis points as text: 3050 -> "30.50%"."""
    return f"{bps // 100}.{bps % 100:02d}%"
