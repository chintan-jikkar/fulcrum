"""Brand logos from Logo.dev, fetched on the server and kept on disk (D-067).

A viewer's browser asks this API for `/brands/{key}/logo`, never Logo.dev, so no third party
learns which merchants a user buys from. Each logo is downloaded once, the first time anyone
asks, using the secret key and Logo.dev's brand API (which allows storing the file). Logos stay
their owners' trademarks and are shown only to identify the brand.

Each logo is stored twice, `{key}.png` and `{key}.dark.png` (Logo.dev lightens dark marks for
dark backgrounds), after `tidy` has fitted it to a square tile. Files live in settings.logo_dir,
outside git (the repo is public). With no secret key set, every logo is 404 and the web shows
the brand-colour tile instead.

ponytail: a logo is never refreshed once stored. Delete the folder to refetch; add Logo.dev's
etag check or brand.updated webhook if logos go stale in practice.
"""

import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

from app.brands import BRANDS
from app.config import settings

# The site Logo.dev looks each brand up by. Keys match app.brands.BRANDS.
DOMAINS: dict[str, str] = {
    "chase": "chase.com",
    "bankofamerica": "bankofamerica.com",
    "wellsfargo": "wellsfargo.com",
    "citi": "citi.com",
    "capitalone": "capitalone.com",
    "amex": "americanexpress.com",
    "discover": "discover.com",
    "usbank": "usbank.com",
    "pnc": "pnc.com",
    "td": "td.com",
    "ally": "ally.com",
    "applecard": "apple.com",
    "schwab": "schwab.com",
    "marcus": "marcus.com",
    "sofi": "sofi.com",
    "navyfederal": "navyfederal.org",
    "visa": "visa.com",
    "mastercard": "mastercard.com",
    "target": "target.com",
    "walmart": "walmart.com",
    "costco": "costco.com",
    "traderjoes": "traderjoes.com",
    "wholefoods": "wholefoodsmarket.com",
    "bestbuy": "bestbuy.com",
    "amazon": "amazon.com",
    "cvs": "cvs.com",
    "walgreens": "walgreens.com",
    "apple": "apple.com",
    "subway": "subway.com",
    "starbucks": "starbucks.com",
    "dunkin": "dunkindonuts.com",
    "mcdonalds": "mcdonalds.com",
    "chipotle": "chipotle.com",
    "chickfila": "chick-fil-a.com",
    "doordash": "doordash.com",
    "ubereats": "ubereats.com",
    "mta": "mta.info",
    "njtransit": "njtransit.com",
    "uber": "uber.com",
    "lyft": "lyft.com",
    "netflix": "netflix.com",
    "spotify": "spotify.com",
    "claude": "claude.ai",
    "gemini": "gemini.google.com",
    "chatgpt": "chatgpt.com",
    "youtube": "youtube.com",
}
assert set(DOMAINS) == {b.key for b in BRANDS}, "every brand needs a domain"

API = "https://api.logo.dev/v2/brands"
NO_LOGO_RETRY = 7 * 24 * 3600  # a brand Logo.dev had no logo for is asked again after a week
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SIZE = 256  # stored square; the tile is 34 CSS px, so this stays sharp on 3x screens
MARGIN = 0.12  # breathing room around a transparent mark, as a share of SIZE


class TryLater(Exception):
    """Logo.dev could not answer now (indexing, an error, a timeout). Nothing is stored."""


def _get(url: str, headers: dict[str, str]) -> tuple[int, str, bytes]:
    """One GET: (status, content type, body). The tests replace this."""
    request = urllib.request.Request(url, headers={"User-Agent": "parity-api", **headers})
    try:
        with urllib.request.urlopen(request, timeout=20) as r:  # noqa: S310 (fixed https hosts)
            return r.status, r.headers.get_content_type(), r.read(2_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get_content_type(), e.read(10_000)
    except OSError as e:  # DNS, refused, timeout
        raise TryLater(str(e)) from e


def _near_white(pixel: tuple[int, ...]) -> bool:
    return min(pixel[:3]) >= 235 and pixel[3] == 255


def tidy(data: bytes) -> bytes:
    """Fit a downloaded logo to a SIZE square tile, so every brand reads at the same weight.

    - A mark on a white background loses the background (flood-filled from the corners), so
      no white box shows on the tile.
    - A mark on transparency is trimmed to its edges and centred with a small margin, so a
      file that is mostly empty space (Netflix's) still fills the tile.
    - A logo that is its own solid square (Best Buy's blue, Spotify's black), even one floating
      in empty margins, fills the whole tile edge to edge, like an app icon.
    """
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = im.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    if all(_near_white(im.getpixel(c)) for c in corners):  # type: ignore[arg-type]
        for c in corners:
            ImageDraw.floodfill(im, c, (0, 0, 0, 0), thresh=40)

    # Trim to the mark's edges, ignoring faint anti-aliasing haze.
    box = im.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    mark = im.crop(box) if box else im
    w, h = mark.size

    # Share of the trimmed box that is solid: about 1.0 for a square, 0.95 for a rounded
    # square (app-icon shape), 0.79 for a circle.
    solid = mark.getchannel("A").point(lambda a: 255 if a > 240 else 0).histogram()[255] / (w * h)
    if solid >= 0.9 and max(w, h) <= 1.15 * min(w, h):
        # A solid, roughly square block (its own coloured background, maybe with rounded
        # corners): fill the tile edge to edge, padding the last few pixels with its corner.
        # A wide solid banner falls through to the margin case instead of becoming a big
        # coloured square.
        square = Image.new("RGBA", (max(w, h),) * 2, mark.getpixel((0, 0)))
        square.paste(mark, ((max(w, h) - w) // 2, (max(w, h) - h) // 2))
        out = square.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    else:
        # A mark on transparency: centre it with a margin so it clears the rounded corners.
        scale = SIZE * (1 - 2 * MARGIN) / max(w, h)
        mark = mark.resize(
            (max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS
        )
        out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        out.paste(mark, ((SIZE - mark.width) // 2, (SIZE - mark.height) // 2), mark)

    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _download(url: str, domain: str) -> bytes:
    status, kind, image = _get(url, {})
    if status != 200 or kind != "image/png" or not image.startswith(PNG_MAGIC):
        raise TryLater(f"logo download for {domain} was not a PNG ({status}, {kind})")
    try:
        return tidy(image)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise TryLater(f"logo for {domain} could not be read: {e}") from e


def fetch(domain: str, secret: str) -> tuple[bytes, bytes] | None:
    """The brand's logo for light and dark backgrounds, tidied, or None if Logo.dev has none."""
    status, _, body = _get(
        f"{API}?{urllib.parse.urlencode({'domain': domain})}",
        {"Authorization": f"Bearer {secret}"},
    )
    if status == 404:
        return None
    if status != 200:  # 202 still indexing, 4xx/5xx trouble
        raise TryLater(f"logo.dev answered {status} for {domain}")
    logo = json.loads(body).get("data", {}).get("logo")
    if not logo or not logo.get("url"):
        return None
    # The download link is signed and expires; it carries its own credential, so no key here.
    url = f"{logo['url']}?size={SIZE}&format=png"
    return _download(url, domain), _download(f"{url}&theme=dark", domain)


def logo_file(key: str, dark: bool = False) -> Path | None:
    """The stored logo for a brand key, fetching both versions the first time. None: no logo."""
    domain = DOMAINS.get(key)
    secret = settings.logo_dev_secret_key
    if domain is None or not secret:
        return None
    folder = Path(settings.logo_dir)
    light_png, dark_png = folder / f"{key}.png", folder / f"{key}.dark.png"
    missing = folder / f"{key}.none"
    wanted = dark_png if dark else light_png
    if wanted.exists():
        return wanted
    if missing.exists() and time.time() - missing.stat().st_mtime < NO_LOGO_RETRY:
        return None
    try:
        images = fetch(domain, secret)
    except TryLater:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    if images is None:
        missing.touch()
        return None
    # Write then rename, so a reader never sees half a file, and two first requests racing
    # each write a whole copy of the same image.
    for path, image in ((light_png, images[0]), (dark_png, images[1])):
        part = folder / f"{path.name}.{os.getpid()}.part"
        part.write_bytes(image)
        part.replace(path)
    return wanted
