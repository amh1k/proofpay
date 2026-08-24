"""Extraction service — composes preprocess → extractor → normalize → PaymentClaim.

This is the single entry point for the rest of the application. It accepts
raw image bytes and a claim_id, and returns a fully normalised PaymentClaim
that the verification engine can consume unchanged.

Selection logic: DASHSCOPE_API_KEY set → DashScope OCR adapter.
                 No key → OfflineStubExtractor (degraded but working).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from proofpay.core.models import PaymentClaim
from proofpay.extraction.errors import (
    ExtractionError,
    ExtractionRefused,
)
from proofpay.extraction.normalize import (
    normalize_msisdn,
    parse_amount,
    parse_timestamp,
)
from proofpay.extraction.preprocess import PreparedImage, prepare
from proofpay.extraction.schema import ExtractionResult, RawClaim

__all__ = ["ExtractionService", "build_extractor"]

logger = logging.getLogger(__name__)

# Path to the demo manifest for the offline stub
_MANIFEST_PATH = Path(__file__).parents[2] / ".." / "fixtures" / "demo" / "manifest.json"


def build_extractor(api_key: str | None = None, mode: str = "auto"):
    """Factory: build the right extractor based on configuration.

    Modes:
        "auto"    — DashScope if key present, else offline stub
        "offline" — Always offline stub (no network)
        "cloud"   — DashScope only (fails if no key)
    """
    if mode == "offline":
        from proofpay.extraction.stub import OfflineStubExtractor

        manifest = _MANIFEST_PATH.resolve()
        return OfflineStubExtractor(manifest)

    if mode == "cloud" or (mode == "auto" and api_key):
        from proofpay.extraction.dashscope_ocr import DashScopeOcrExtractor

        return DashScopeOcrExtractor(api_key=api_key)

    # Fallback: offline stub
    from proofpay.extraction.stub import OfflineStubExtractor

    manifest = _MANIFEST_PATH.resolve()
    return OfflineStubExtractor(manifest)


class ExtractionService:
    """High-level service composing the full extraction pipeline.

    Usage:
        service = ExtractionService()
        claim = service.extract(image_bytes, claim_id="abc-123")
    """

    def __init__(
        self,
        api_key: str | None = None,
        mode: str = "auto",
    ):
        self.mode = mode
        self._extractor = None
        self._api_key = api_key

    @property
    def extractor(self):
        if self._extractor is None:
            self._extractor = build_extractor(
                api_key=self._api_key, mode=self.mode
            )
        return self._extractor

    def extract(self, image_bytes: bytes, claim_id: str) -> PaymentClaim:
        """Full pipeline: raw bytes → preprocessed → extracted → normalised → PaymentClaim."""
        t0 = time.monotonic()

        # Step 1: Preprocess
        prepared = prepare(image_bytes)
        logger.info(
            "Preprocessed image: %dx%d, ~%d tokens, sha256=%s",
            prepared.width,
            prepared.height,
            prepared.est_image_tokens,
            prepared.source_sha256[:12],
        )

        # Step 2: Extract
        try:
            result = self._extract_with_fallback(prepared, claim_id)
        except ExtractionRefused:
            # Content filter — do NOT retry, create a minimal claim
            return PaymentClaim(
                claim_id=claim_id,
                notes=("content_filtered",),
                parser_version="refused",
            )

        # Step 3: Normalise raw claim into PaymentClaim
        claim = self._normalise(result.claim, claim_id, prepared, result)

        elapsed = int((time.monotonic() - t0) * 1000)
        logger.info(
            "Extraction complete: %s, %dms total, extractor=%s, degraded=%s",
            claim_id,
            elapsed,
            result.extractor_id,
            result.degraded,
        )

        return claim

    def _extract_with_fallback(
        self, prepared: PreparedImage, claim_id: str
    ) -> ExtractionResult:
        """Try primary extractor, fall back to offline on failure."""
        try:
            ext = self.extractor

            # If the extractor is the DashScope adapter, use PreparedImage
            if hasattr(ext, "extract") and hasattr(ext, "id"):
                # DashScope adapter expects PreparedImage
                from proofpay.extraction.dashscope_ocr import DashScopeOcrExtractor

                if isinstance(ext, DashScopeOcrExtractor):
                    return ext.extract(prepared)

            # OfflineStubExtractor expects raw bytes + claim_id
            from proofpay.extraction.stub import OfflineStubExtractor

            if isinstance(ext, OfflineStubExtractor):
                # Convert to the legacy format
                stub_claim = ext.extract(prepared.png_bytes, claim_id)
                return ExtractionResult(
                    claim=RawClaim(
                        provider_hint=_str_to_maybe(stub_claim.provider),
                        amount_text=_str_to_maybe(
                            str(stub_claim.amount.minor) if stub_claim.amount else None
                        ),
                        reference_id=_str_to_maybe(stub_claim.reference_id),
                        sender_name=_str_to_maybe(stub_claim.sender_name),
                        receiver_name=_str_to_maybe(stub_claim.receiver_name),
                    ),
                    extractor_id="offline_stub_v1",
                    preproc_version=prepared.preproc_version,
                )

        except ExtractionRefused:
            raise  # Never retry content filter
        except ExtractionError as e:
            logger.warning("Primary extractor failed: %s, falling back", e)
            # Fall back to offline
            return ExtractionResult(
                claim=RawClaim(),
                extractor_id="fallback_empty",
                preproc_version=prepared.preproc_version,
                degraded=True,
                degraded_reason=str(e),
            )

        # Should not reach here, but safety net
        return ExtractionResult(
            claim=RawClaim(),
            extractor_id="unknown",
            preproc_version=prepared.preproc_version,
            degraded=True,
            degraded_reason="No extractor matched",
        )

    def _normalise(
        self,
        raw: RawClaim,
        claim_id: str,
        prepared: PreparedImage,
        result: ExtractionResult,
    ) -> PaymentClaim:
        """Convert raw strings into typed domain objects."""
        # Parse amount
        amount = None
        if raw.amount_text.ok:
            amount = parse_amount(raw.amount_text.value)

        # Parse timestamp
        occurred_at = None
        if raw.timestamp_text.ok:
            occurred_at = parse_timestamp(raw.timestamp_text.value)

        # Parse receiver account (phone number)
        receiver_account = None
        if raw.receiver_account.ok:
            receiver_account = normalize_msisdn(raw.receiver_account.value)
            if receiver_account is None:
                # Might be an IBAN, keep raw
                receiver_account = raw.receiver_account.value

        # Build notes from observations
        notes = []
        if result.degraded:
            notes.append(f"degraded:{result.degraded_reason}")
        for obs in result.tamper_observations:
            notes.append(f"{obs.code}:{obs.detail}")

        # Build field confidences from evidence
        field_confidences = {}
        for fe in result.fields:
            if fe.confidence_band == "high":
                field_confidences[fe.field] = 1.0
            elif fe.confidence_band == "low":
                field_confidences[fe.field] = 0.5
            # "none" → not reported (absent key = fully confident default)

        return PaymentClaim(
            claim_id=claim_id,
            provider=raw.provider_hint.value if raw.provider_hint.ok else None,
            amount=amount,
            sender_name=raw.sender_name.value if raw.sender_name.ok else None,
            receiver_name=raw.receiver_name.value if raw.receiver_name.ok else None,
            receiver_account=receiver_account,
            reference_id=raw.reference_id.value if raw.reference_id.ok else None,
            occurred_at=occurred_at,
            field_confidences=field_confidences,
            notes=tuple(notes),
            parser_version=result.extractor_id,
        )


def _str_to_maybe(value: str | None):
    """Helper to convert a plain string to a Maybe."""
    from proofpay.extraction.schema import Maybe

    if value and value.strip():
        return Maybe(value=value.strip(), raw_text=value.strip())
    return Maybe(absent_reason="not_present")
