"""Brand logos from Logo.dev, fetched once on the server and served by the API (D-067)."""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine

from app import logos
from app.brands import BRANDS
from app.config import settings
from tests.test_idempotency import client_for


def png(
    size: tuple[int, int],
    bg: tuple[int, ...],
    box: tuple[int, int, int, int] | None = None,
    fg: tuple[int, ...] = (200, 20, 20, 255),
) -> bytes:
    """A made-up logo: a `bg` canvas with an `fg` rectangle at `box` (left, top, right, bottom)."""
    im = Image.new("RGBA", size, bg)
    if box:
        im.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), fg), box[:2])
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


def px(im: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    pixel = im.getpixel(xy)
    assert isinstance(pixel, tuple)
    return pixel


PNG = png((64, 64), (0, 0, 0, 0), (8, 8, 56, 56))
DARK = png((64, 64), (0, 0, 0, 0), (8, 8, 56, 56), fg=(240, 240, 240, 255))


class FakeLogoDev:
    """Stands in for the network: records calls and answers from a table."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.answers: dict[str, Any] = {}

    def __call__(self, domain: str, secret: str) -> tuple[bytes, bytes] | None:
        self.calls.append(domain)
        answer = self.answers.get(domain, (PNG, DARK))
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[no-any-return]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeLogoDev:
    f = FakeLogoDev()
    monkeypatch.setattr(logos, "fetch", f)
    monkeypatch.setattr(settings, "logo_dir", tmp_path)
    monkeypatch.setattr(settings, "logo_dev_secret_key", "sk_test")
    return f


@pytest.fixture
def anon(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A caller with no sign-in at all: logos are public brand assets, like a favicon."""
    monkeypatch.setattr(settings, "dev_auth_sub", None)
    with client_for(engine, fake_auth=False) as c:
        yield c


def test_every_brand_has_a_domain_to_look_up() -> None:
    assert {b.key for b in BRANDS} == set(logos.DOMAINS)
    assert all("." in d and "/" not in d for d in logos.DOMAINS.values())


def test_a_logo_is_fetched_once_then_served_from_disk(
    fake: FakeLogoDev, anon: TestClient, tmp_path: Path
) -> None:
    first = anon.get("/brands/netflix/logo")
    second = anon.get("/brands/netflix/logo")

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert "max-age" in first.headers["cache-control"]
    assert first.content == second.content == PNG
    assert anon.get("/brands/netflix/logo?theme=dark").content == DARK
    assert fake.calls == ["netflix.com"]  # one lookup stores both versions
    assert (tmp_path / "netflix.png").read_bytes() == PNG
    assert (tmp_path / "netflix.dark.png").read_bytes() == DARK


def test_an_unknown_brand_is_404_and_never_looked_up(fake: FakeLogoDev, anon: TestClient) -> None:
    assert anon.get("/brands/not-a-brand/logo").status_code == 404
    assert anon.get("/brands/..%2Fetc/logo").status_code == 404
    assert fake.calls == []


def test_without_a_secret_key_there_are_no_logos(
    fake: FakeLogoDev, anon: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "logo_dev_secret_key", None)

    assert anon.get("/brands/netflix/logo").status_code == 404
    assert fake.calls == []


def test_a_brand_with_no_logo_is_remembered(fake: FakeLogoDev, anon: TestClient) -> None:
    fake.answers["mta.info"] = None

    assert anon.get("/brands/mta/logo").status_code == 404
    assert anon.get("/brands/mta/logo").status_code == 404
    assert fake.calls == ["mta.info"]


def test_a_failed_fetch_is_retried_next_time(fake: FakeLogoDev, anon: TestClient) -> None:
    fake.answers["netflix.com"] = logos.TryLater("timed out")
    assert anon.get("/brands/netflix/logo").status_code == 404

    del fake.answers["netflix.com"]
    assert anon.get("/brands/netflix/logo").status_code == 200
    assert fake.calls == ["netflix.com", "netflix.com"]


# --- The Logo.dev calls themselves, with the network replaced --------------------------------


class FakeHttp:
    def __init__(self, replies: list[tuple[int, str, bytes]]) -> None:
        self.replies = replies
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, str, bytes]:
        self.requests.append((url, headers))
        return self.replies.pop(0)


def _brand(logo_url: str | None) -> bytes:
    logo = None if logo_url is None else {"url": logo_url}
    return json.dumps({"data": {"status": "ready", "logo": logo}}).encode()


def test_fetch_asks_for_the_brand_then_downloads_light_and_dark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = FakeHttp(
        [
            (200, "application/json", _brand("https://img.logo.dev/assets/TOKEN")),
            (200, "image/png", PNG),
            (200, "image/png", DARK),
        ]
    )
    monkeypatch.setattr(logos, "_get", http)

    light, dark = logos.fetch("netflix.com", "sk_test") or (b"", b"")

    lookup, light_dl, dark_dl = http.requests
    assert lookup == (
        "https://api.logo.dev/v2/brands?domain=netflix.com",
        {"Authorization": "Bearer sk_test"},
    )
    # The signed link is the credential; the key stays home.
    assert light_dl == ("https://img.logo.dev/assets/TOKEN?size=256&format=png", {})
    assert dark_dl == ("https://img.logo.dev/assets/TOKEN?size=256&format=png&theme=dark", {})
    # Both come back tidied to the tile size, the mark centred.
    assert opened(light).size == opened(dark).size == (256, 256)
    assert px(opened(light), (128, 128)) == (200, 20, 20, 255)
    assert px(opened(dark), (128, 128)) == (240, 240, 240, 255)


@pytest.mark.parametrize(
    ("replies", "want"),
    [
        ([(404, "application/json", b"{}")], None),  # no such brand
        ([(200, "application/json", _brand(None))], None),  # a brand without a logo
        (
            [
                (200, "application/json", _brand("https://img.logo.dev/assets/T")),
                (200, "text/html", b"<html>"),
            ],
            logos.TryLater,
        ),  # not an image: keep nothing, try again later
        ([(202, "application/json", b"{}")], logos.TryLater),  # still indexing
        ([(500, "text/plain", b"oops")], logos.TryLater),
    ],
)
def test_fetch_outcomes(
    monkeypatch: pytest.MonkeyPatch, replies: list[tuple[int, str, bytes]], want: Any
) -> None:
    monkeypatch.setattr(logos, "_get", FakeHttp(replies))

    if want is None:
        assert logos.fetch("example.com", "sk_test") is None
    else:
        with pytest.raises(want):
            logos.fetch("example.com", "sk_test")


# --- Tidying: what makes a logo sit well in a small square tile --------------------------------


def content_box(im: Image.Image) -> tuple[int, int, int, int]:
    box = im.getchannel("A").getbbox()
    assert box is not None
    return box


def test_tidy_trims_empty_margins_and_centres_the_mark() -> None:
    # A small mark off in one corner of a big transparent canvas, like the Netflix file.
    im = opened(logos.tidy(png((256, 256), (0, 0, 0, 0), (150, 30, 190, 110))))

    left, top, right, bottom = content_box(im)
    assert im.width == im.height == 256
    assert bottom - top >= 0.75 * 256  # the tall side nearly fills the tile
    assert abs((left + right) / 2 - 128) <= 2  # centred
    assert abs((top + bottom) / 2 - 128) <= 2


def test_tidy_makes_a_white_background_transparent() -> None:
    # A wordmark on opaque white, like the Costco file.
    im = opened(logos.tidy(png((200, 200), (255, 255, 255, 255), (40, 80, 160, 120))))

    assert px(im, (0, 0))[3] == 0  # the white is gone
    assert px(im, (128, 128)) == (200, 20, 20, 255)  # the mark is kept, now centred
    left, _, right, _ = content_box(im)
    assert right - left >= 0.75 * 256  # the wide side nearly fills the tile


def test_tidy_keeps_a_coloured_background_to_fill_the_tile() -> None:
    # A logo that is its own coloured square, like Best Buy's blue.
    blue = (0, 70, 190, 255)
    im = opened(logos.tidy(png((200, 200), blue, (60, 60, 140, 140), fg=(255, 255, 255, 255))))

    assert (im.width, im.height) == (256, 256)
    assert px(im, (0, 0)) == blue
    assert px(im, (255, 255)) == blue


def test_tidy_pads_a_wide_image_to_a_square() -> None:
    im = opened(logos.tidy(png((300, 100), (0, 0, 0, 0), (10, 10, 290, 90))))

    assert (im.width, im.height) == (256, 256)
    assert px(im, (128, 2))[3] == 0  # empty above the wide mark


def test_tidy_lets_a_square_inside_empty_margins_fill_the_tile() -> None:
    # A solid black square floating in transparent margins, like the Spotify file.
    im = opened(logos.tidy(png((256, 256), (0, 0, 0, 0), (40, 40, 216, 216), fg=(0, 0, 0, 255))))

    assert px(im, (0, 0)) == (0, 0, 0, 255)  # edge to edge, no inset box
    assert px(im, (255, 255)) == (0, 0, 0, 255)


def test_tidy_fills_the_tile_with_a_rounded_square_but_not_a_circle() -> None:
    # A black square with clipped (transparent) corners, like Spotify's app-icon shape.
    rounded = Image.new("RGBA", (200, 200), (0, 0, 0, 255))
    for x, y in ((0, 0), (190, 0), (0, 190), (190, 190)):
        rounded.paste(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), (x, y))
    buf = io.BytesIO()
    rounded.save(buf, "PNG")
    filled = opened(logos.tidy(buf.getvalue()))

    circle = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(circle).ellipse((0, 0, 199, 199), fill=(0, 112, 74, 255))
    buf = io.BytesIO()
    circle.save(buf, "PNG")
    ringed = opened(logos.tidy(buf.getvalue()))

    assert px(filled, (128, 1)) == (0, 0, 0, 255)  # reaches the top edge
    assert px(ringed, (128, 1))[3] == 0  # the circle keeps its margin
