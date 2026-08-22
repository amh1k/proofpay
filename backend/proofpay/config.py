"""Application configuration.

Configuration, secrets, thresholds and rule versions are injected through the
deployment environment (system_design.md 19). Every setting has a working
default so the application starts with no `.env` file present.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROOFPAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    secret_key: str = "dev-insecure-change-me"

    # Relational state.
    database_url: str = "sqlite:///./proofpay.db"

    # Private object storage for proof images.
    storage_backend: Literal["local", "oss"] = "local"
    storage_local_path: str = "./storage"

    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None

    # Receipt understanding.
    receipt_extractor: Literal["qwen", "deterministic"] = "deterministic"
    qwen_model: str = "qwen-vl-max"
    dashscope_api_key: str | None = None

    # Upload limits (system_design.md 15.2).
    max_upload_bytes: int = 8 * 1024 * 1024

    def effective_receipt_extractor(self) -> Literal["qwen", "deterministic"]:
        """Resolve the extractor that can actually run.

        A missing credential must degrade quality, never break the pipeline
        (system_design.md 16). Asking for Qwen without a key silently falls
        back to the deterministic extractor.
        """
        if self.receipt_extractor == "qwen" and not self.dashscope_api_key:
            return "deterministic"
        return self.receipt_extractor


@lru_cache
def get_settings() -> Settings:
    return Settings()
