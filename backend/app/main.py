"""FastAPI application factory and router registration.

Boots the GTM Agent backend, wires up the v1 API routers, and exposes
a `/health` endpoint used by Docker, CI, and uptime checks.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import awards, companies, emails, feedback, matches, tenders
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="GTM Agent API",
        version="0.1.0",
        description="B2B lead-generation pipeline for the construction-tech sector.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tenders.router, prefix="/api/v1/tenders", tags=["tenders"])
    app.include_router(awards.router, prefix="/api/v1/awards", tags=["awards"])
    app.include_router(companies.router, prefix="/api/v1/companies", tags=["companies"])
    app.include_router(matches.router, prefix="/api/v1/matches", tags=["matches"])
    app.include_router(emails.router, prefix="/api/v1/emails", tags=["emails"])
    app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "gtm-agent-backend"}

    return app


app = create_app()
