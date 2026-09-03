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

__all__ = ["ExtractionService", "build_extractor", "field_confidences_from"]

logger = logging.getLogger(__name__)

# Path to the demo manifest for the offline stub
_MANIFEST_PATH = Path(__file__).parents[2] / ".." / "fixtures" / "demo" / "manifest.json"


def field_confidences_from(fields) -> dict[str, float]:
    """Confidence bands -> the numbers `DecisionPolicy.min_field_confidence` reads.

    A module-level function rather than four lines inside `_normalise`, because
    this is the join between two layers that were written apart, and a test that
    wants to ask "what does the cloud reader's output do to the engine?" has to
    be able to run the real mapping rather than a second copy of it. A second
    copy is exactly how the seam went unnoticed for as long as it did: the only
    test that touched the extractor's bands called it with every field absent,
    so every band was `none` and the all-`low` behaviour never appeared.

    Three bands, and only two of them report anything:

        high -> 1.0
        low  -> 0.5
        none -> no key at all, which `PaymentClaim.confidence_for` reads as the
                fully-confident default. Absence of a value is handled by the
                MISSING rung on the comparison ladder, not by doubt.

    So the live scale is two points wide, which is why
    `DecisionPolicy.min_field_confidence` is documented as a band switch rather
    than a tuned number.
    """
    confidences: dict[str, float] = {}
    for evidence in fields:
        if evidence.confidence_band == "high":
            confidences[evidence.field] = 1.0
        elif evidence.confidence_band == "low":
            confidences[evidence.field] = 0.5
    return confidences


def build_extractor(
    api_key: str | None = None,
    mode: str = "auto",
    model: str | None = None,
):
    """Factory: build the right extractor based on configuration.

    Modes:
        "auto"    — DashScope if key present, else offline stub
        "offline" — Always offline stub (no network)
        "cloud"   — DashScope only (fails if no key)

    `model` overrides the vision model and is only meaningful to the cloud
    adapter. `None` leaves the adapter's own pinned default alone, which is the
    one place the real default should live.
    """
    if mode == "offline":
        from proofpay.extraction.stub import OfflineStubExtractor

        manifest = _MANIFEST_PATH.resolve()
        return OfflineStubExtractor(manifest)

    if mode == "cloud" or (mode == "auto" and api_key):
        from proofpay.extraction.dashscope_ocr import DashScopeOcrExtractor

        if model is None:
            return DashScopeOcrExtractor(api_key=api_key)
        return DashScopeOcrExtractor(api_key=api_key, model=model)

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
        model: str | None = None,
    ):
        self.mode = mode
        self._extractor = None
        self._api_key = api_key
        self._model = model

    @property
    def extractor(self):
        if self._extractor is None:
            self._extractor = build_extractor(
                api_key=self._api_key, mode=self.mode, model=self._model
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

        # Step 2b: Tamper analysis (CPU-only observations)
        from proofpay.extraction.tamper import analyze_tamper

        tamper_obs = analyze_tamper(image_bytes, prepared)
        result.tamper_observations.extend(tamper_obs)

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
                            f"{stub_claim.amount.minor / 100:.2f}" if stub_claim.amount else None
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

        # Build field confidences from evidence. The mapping lives at module
        # level so a test can run THIS one rather than a copy of it — see
        # `field_confidences_from`.
        field_confidences = field_confidences_from(result.fields)

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
