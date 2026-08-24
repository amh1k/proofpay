"""Qwen-VL OCR adapter via Alibaba DashScope — Key Information Extraction mode.

This is the ONLY file in the codebase that `import dashscope`. The KIE mode
uses `ocr_options` with a server-side `result_schema`, which means the field
list lives OUTSIDE the prompt — reducing prompt-injection surface from
attacker-controlled text in the receipt image.

Model: qwen-vl-ocr (pinned snapshot) at $0.07/$0.16 per 1M tokens.
Free quota: 1M tokens / 90 days on the Singapore region.

CRITICAL: use the international endpoint. Beijing has no free quota.
"""

from __future__ import annotations

import base64
import logging
import os
import time

import dashscope

from proofpay.extraction.errors import (
    ExtractionMalformed,
    ExtractionRefused,
    ExtractionTimeout,
    ExtractionUnavailable,
)
from proofpay.extraction.preprocess import PreparedImage
from proofpay.extraction.schema import (
    ExtractionResult,
    FieldEvidence,
    Maybe,
    RawClaim,
    compute_confidence_band,
)

__all__ = ["DashScopeOcrExtractor"]

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────

# Pin a snapshot — never use -latest, it silently changes under you
DEFAULT_MODEL = "qwen-vl-ocr-2025-11-20"

# International endpoint only — Beijing has no free quota
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"

# Server-side field schema — lives outside the prompt (injection-resistant)
RESULT_SCHEMA = {
    "Transaction ID": "The transaction/TID/reference number shown on the receipt",
    "Amount": "The transferred amount exactly as printed, e.g. 4,500.00 or Rs. 5000",
    "Currency": "Currency code or symbol as printed, e.g. Rs, PKR, ₨",
    "Sender Name": "Name of the person sending money, exactly as printed",
    "Receiver Name": "Name of the person or business receiving money",
    "Receiver Account": "Receiver mobile number or IBAN as printed on the receipt",
    "Date Time": "Date and time of the transaction exactly as printed on receipt",
    "Status": "Transaction status text, e.g. Successful / Pending / Failed",
    "Provider": "Payment app or bank name shown, e.g. Easypaisa, JazzCash, Raast, HBL",
}

# Token budget: 32*32*4096 = 4,194,304 max pixels. A 1080x2400 screenshot
# sits under this cap and passes through untouched at ~2,530 tokens.
MIN_PIXELS = 32 * 32 * 4
MAX_PIXELS = 32 * 32 * 4096

# Hard timeout: 12 seconds connect+read. The API's own limit is 300s — never inherit that.
CALL_TIMEOUT_S = 12

# Status codes that must never be retried
_NO_RETRY_CODES = {400, 401, 403, 404}


class DashScopeOcrExtractor:
    """Production Qwen-VL OCR extractor using DashScope KIE mode."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = DASHSCOPE_BASE_URL,
    ):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.model = model
        self.id = f"{model}+kie/v1"

        if not self.api_key:
            raise ExtractionUnavailable(
                "DASHSCOPE_API_KEY not set. Use OfflineStubExtractor or set the key."
            )

        # Set the international base URL
        dashscope.base_http_api_url = base_url

    def extract(self, image: PreparedImage) -> ExtractionResult:
        """Extract structured payment data from a preprocessed receipt image."""
        t0 = time.monotonic()

        # Encode image as base64 data URI
        b64 = base64.b64encode(image.png_bytes).decode("ascii")
        image_uri = f"data:image/png;base64,{b64}"

        # Build message with image — note: min_pixels/max_pixels go INSIDE
        # the image content part, NOT at the top level
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "image": image_uri,
                        "min_pixels": MIN_PIXELS,
                        "max_pixels": MAX_PIXELS,
                    },
                    {
                        "text": "Extract the key information from this payment receipt.",
                    },
                ],
            }
        ]

        # Call DashScope with KIE mode
        try:
            response = dashscope.MultiModalConversation.call(
                api_key=self.api_key,
                model=self.model,
                messages=messages,
                timeout=CALL_TIMEOUT_S,
                ocr_options={
                    "task": "key_information_extraction",
                    "task_config": {
                        "result_schema": RESULT_SCHEMA,
                    },
                },
            )
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str or "timed out" in error_str:
                raise ExtractionTimeout(f"DashScope call timed out: {e}") from e
            if "connection" in error_str or "network" in error_str:
                raise ExtractionUnavailable(f"DashScope unreachable: {e}") from e
            raise ExtractionUnavailable(f"DashScope call failed: {e}") from e

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Handle API-level errors
        if response.status_code != 200:
            self._handle_error(response)

        # Extract the kv_result from the nested response
        kv = self._extract_kv_result(response)

        # Map KIE output to our RawClaim schema
        raw_claim = self._map_to_raw_claim(kv)

        # Build field evidence
        fields = self._build_field_evidence(raw_claim, kv)

        # Also get full OCR text if available
        ocr_text = self._extract_ocr_text(response)

        return ExtractionResult(
            claim=raw_claim,
            ocr_text=ocr_text,
            fields=fields,
            extractor_id=self.id,
            preproc_version=image.preproc_version,
            latency_ms=latency_ms,
        )

    def _handle_error(self, response) -> None:
        """Map DashScope error codes to our error hierarchy."""
        code = response.status_code
        msg = getattr(response, "message", str(response))

        if code in (401, 403):
            if "DataInspectionFailed" in str(msg):
                raise ExtractionRefused(f"Content filtered: {msg}")
            raise ExtractionUnavailable(f"Auth/quota error ({code}): {msg}")

        if code == 429:
            raise ExtractionUnavailable(f"Rate limited: {msg}")

        if code == 404:
            raise ExtractionUnavailable(f"Model not found: {msg}")

        if code == 400:
            if "DataInspectionFailed" in str(msg):
                raise ExtractionRefused(f"Content filtered: {msg}")
            raise ExtractionMalformed(f"Bad request: {msg}")

        if code >= 500:
            raise ExtractionUnavailable(f"Server error ({code}): {msg}")

        raise ExtractionUnavailable(f"Unexpected status {code}: {msg}")

    def _extract_kv_result(self, response) -> dict[str, str]:
        """Navigate the nested DashScope response to get kv_result."""
        try:
            choices = response.output.choices
            content = choices[0].message.content
            for part in content:
                if isinstance(part, dict) and "ocr_result" in part:
                    return part["ocr_result"].get("kv_result", {})
            # Fallback: content might be a string (plain text response)
            if isinstance(content, str):
                raise ExtractionMalformed(
                    "Response was plain text, not KIE structured output"
                )
            return {}
        except (AttributeError, IndexError, KeyError, TypeError) as e:
            raise ExtractionMalformed(
                f"Could not parse DashScope response structure: {e}"
            ) from e

    def _extract_ocr_text(self, response) -> str | None:
        """Try to extract full OCR text from the response if available."""
        try:
            choices = response.output.choices
            content = choices[0].message.content
            for part in content:
                if isinstance(part, dict) and "ocr_result" in part:
                    words = part["ocr_result"].get("words_info", [])
                    if words:
                        return " ".join(w.get("word", "") for w in words)
            # If content is a list of dicts with 'text' key
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    return part["text"]
        except (AttributeError, IndexError, KeyError, TypeError):
            pass
        return None

    def _map_to_raw_claim(self, kv: dict[str, str]) -> RawClaim:
        """Map flat kv_result strings to our Maybe[T] schema."""
        return RawClaim(
            reference_id=self._to_maybe(kv.get("Transaction ID")),
            amount_text=self._to_maybe(kv.get("Amount")),
            currency_text=self._to_maybe(kv.get("Currency")),
            sender_name=self._to_maybe(kv.get("Sender Name")),
            receiver_name=self._to_maybe(kv.get("Receiver Name")),
            receiver_account=self._to_maybe(kv.get("Receiver Account")),
            timestamp_text=self._to_maybe(kv.get("Date Time")),
            status_text=self._to_maybe(kv.get("Status")),
            provider_hint=self._to_maybe(kv.get("Provider")),
        )

    @staticmethod
    def _to_maybe(value: str | None) -> Maybe[str]:
        """Convert a KIE string value to a Maybe[str].

        KIE returns empty string or omits the key for absent fields.
        """
        if value and value.strip():
            return Maybe(value=value.strip(), raw_text=value.strip())
        return Maybe(absent_reason="not_present")

    def _build_field_evidence(
        self, claim: RawClaim, kv: dict[str, str]
    ) -> list[FieldEvidence]:
        """Build per-field evidence records from the extraction."""
        evidence = []
        field_map = {
            "reference_id": claim.reference_id,
            "amount": claim.amount_text,
            "currency": claim.currency_text,
            "sender_name": claim.sender_name,
            "receiver_name": claim.receiver_name,
            "receiver_account": claim.receiver_account,
            "timestamp": claim.timestamp_text,
            "status": claim.status_text,
            "provider": claim.provider_hint,
        }

        for field_name, maybe_field in field_map.items():
            has_value = maybe_field.ok
            band = compute_confidence_band(
                grounded=None,  # Will be set later by grounding check
                format_valid=None,  # Will be set later by template validation
                agreement="single_source",
                has_value=has_value,
            )
            evidence.append(
                FieldEvidence(
                    field=field_name,
                    value=maybe_field.value if has_value else None,
                    raw_text=maybe_field.raw_text if has_value else None,
                    source="vlm_kie" if has_value else "none",
                    absent_reason=(
                        maybe_field.absent_reason if not has_value else None
                    ),
                    confidence_band=band,
                )
            )

        return evidence
