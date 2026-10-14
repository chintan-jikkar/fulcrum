FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.11.23
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

# Migrations run on start so a fresh `docker compose up` always has the current schema.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
