# Yapı Backend — optimised Python FastAPI container (Section 13.2)
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint system dependencies (PDF rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8000

# Health check hits GET /health (Section 13.2)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx,os; httpx.get('http://localhost:'+os.getenv('PORT','8000')+'/health').raise_for_status()"

# On boot: apply DB migrations (idempotent), then start the server.
#   * alembic upgrade head — keeps the prod schema in sync with the models;
#     without this, new columns/tables (e.g. companies.logo_url) are missing
#     and every query against them 500s.
#   * --proxy-headers + --forwarded-allow-ips=* — makes uvicorn trust Railway's
#     X-Forwarded-Proto. Otherwise the app sees scheme=http behind the
#     TLS-terminating proxy, HTTPSRedirectMiddleware issues a 307 redirect loop,
#     and the browser reports it as a (false) CORS / ERR_FAILED error.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
