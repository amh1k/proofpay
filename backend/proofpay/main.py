"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from proofpay import __version__
from proofpay.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ProofPay",
        version=__version__,
        description="AI-powered payment verification and reconciliation",
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.env,
            "receipt_extractor": settings.effective_receipt_extractor(),
        }

    return app


app = create_app()
