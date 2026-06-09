"""Yapı FastAPI application entrypoint (Section 2.5, 8.1, 13.2)."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from app.config import settings
from app.middleware.errors import register_error_handlers
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

# Routers
from app.api import (
    ai,
    ai_import,
    audit,
    auth,
    cashflow,
    costs,
    custom_categories,
    equipment,
    imports,
    invoices,
    projects,
    reminders,
    reports,
    settings as settings_router,
    subcontractors,
    uploads,
    variations,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Yapı API",
    description="İnşaat Proje Yönetim Yazılımı — REST API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# --- Security middleware (Section 8.1) ---
if settings.is_production:
    app.add_middleware(HTTPSRedirectMiddleware)  # redirect HTTP -> HTTPS

app.add_middleware(SecurityHeadersMiddleware)  # CR-002-I: security headers
app.add_middleware(RateLimitMiddleware)

# CORS: only allow the Vercel frontend origin(s) (Section 8.1).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# --- Health check (Section 13.2) ---
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


# --- API v1 routers ---
API_PREFIX = "/api/v1"
for r in (
    auth.router,
    projects.router,
    costs.router,
    invoices.router,
    subcontractors.router,
    equipment.router,
    cashflow.router,
    imports.router,
    reminders.router,
    reports.router,
    ai.router,
    uploads.router,
    audit.router,
    settings_router.router,
    custom_categories.router,
    ai_import.router,
    variations.router,
):
    app.include_router(r, prefix=API_PREFIX)
