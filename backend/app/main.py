from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.logos import logo_file
from app.routers import book, transactions

app = FastAPI(title="Parity API")
app.include_router(transactions.router)
app.include_router(book.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/brands/{key}/logo", tags=["brands"], response_class=FileResponse)
def brand_logo(key: str, theme: Literal["light", "dark"] = "light") -> FileResponse:
    """A brand's logo (D-067). Public, like a favicon: it is the same for everyone and says
    nothing about the caller. Only keys from the brand table are looked up."""
    path = logo_file(key, dark=theme == "dark")
    if path is None:
        raise HTTPException(status_code=404, detail="no logo")
    # A day in the browser's cache, so a scroll through Activity asks once per brand.
    return FileResponse(
        path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"}
    )
