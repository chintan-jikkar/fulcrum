from fastapi import FastAPI

from app.routers import transactions

app = FastAPI(title="Parity API")
app.include_router(transactions.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
