"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from proofpay import __version__
from proofpay.api.deps import SessionDep
from proofpay.api.errors import http_exception_handler, validation_exception_handler
from proofpay.api.v1.router import router as api_router
from proofpay.config import get_settings


def database_readiness(session: SessionDep) -> dict[str, str]:
    """Report readiness only after a database round-trip succeeds."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_UNAVAILABLE: Database is unavailable",
        ) from exc
    return {"status": "ready", "database": "ok"}


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ProofPay",
        version=__version__,
        description="AI-powered payment verification and reconciliation",
        openapi_tags=[
            {"name": "auth", "description": "Demo authentication contract."},
            {"name": "verifications", "description": "Payment-proof verification."},
            {"name": "claims", "description": "Deprecated claim route aliases."},
            {"name": "orders", "description": "Merchant orders."},
            {"name": "transactions", "description": "Merchant-side transaction feed."},
            {"name": "dashboard", "description": "Merchant dashboard summaries."},
            {"name": "reviews", "description": "Manual verification review workflow."},
            {"name": "demo", "description": "Development and demonstration controls."},
            {"name": "system", "description": "Service health."},
        ],
    )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(api_router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.env,
            "receipt_extractor": settings.effective_receipt_extractor(),
        }

    app.add_api_route(
        "/health/ready",
        database_readiness,
        methods=["GET"],
        tags=["system"],
    )

    return app


app = create_app()
