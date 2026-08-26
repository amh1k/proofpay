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
import re
import time

import dashscope

from proofpay.extraction.errors import (
    ExtractionMalformed,
    ExtractionRefused,
    ExtractionTimeout,
    ExtractionUnavailable,
)
from proofpay.extraction.normalize import (
    normalize_msisdn,
    parse_amount,
    parse_timestamp,
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

# ── Field-level checks behind `confidence_band` ─────────────────────────────
#
# These decide whether this reader is willing to say it read a field WELL, and
# `core`'s `R067` is the only thing that consumes the answer. Two rules govern
# everything below:
#
#   1. Only a check that RAN and FAILED may return False. "Not checked" is
#      `None`, and `compute_confidence_band` treats it as no evidence either
#      way. The alternative — pessimism-by-default — is what banded every
#      cloud-read field `low` and would have sent every Qwen-VL verification to
#      manual review.
#   2. A field nothing scores is not worth refuting. `currency`, `status` and
#      `provider` are read off the receipt and deliberately have no validator:
#      `engine.CONFIDENCE_KEYS` never looks them up, so a doubt about them
#      could only ever be noise on the evidence panel.

#: A reference as a receipt prints one: no spaces, four or more characters, and
#: nothing but the characters a provider actually uses in a TID. Anything else
#: is the reader having captured a label, a line-wrap or half a sentence rather
#: than an identifier.
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_-]{3,63}$")

#: Pakistani IBANs are `PK` + 2 check digits + 4 bank letters + 16 digits, but
#: this stays generic: a receipt may print an account at a foreign bank, and the
#: question here is only "is this shaped like an account identifier".
_IBAN_RE = re.compile(r"^[A-Za-z]{2}[0-9]{2}[A-Za-z0-9]{11,30}$")

#: Reduced to the characters a comparison can survive: case folded, and every
#: separator a receipt or a model might add or drop (spaces, commas, dots,
#: dashes, currency marks) removed. `Rs. 1,500` and `Rs 1500` squash alike.
_NOISE_RE = re.compile(r"[^0-9a-z]+")


def _squash(text: str | None) -> str:
    """Case-folded alphanumerics only. Empty string when there is nothing."""
    if not text:
        return ""
    return _NOISE_RE.sub("", text.casefold())


def _grounded(raw_text: str | None, haystack: str) -> bool | None:
    """Did the detector's own text contain this value? True, or *unknown*.

    Never False — see `_build_field_evidence` for why that is deliberate and
    what would have to be measured before it changes. `None` covers both "no
    OCR text came back" and "came back without this value in it", because this
    layer genuinely cannot tell those apart from a value the KIE head
    reformatted on the way out.
    """
    needle = _squash(raw_text)
    if not needle or not haystack:
        return None
    return True if needle in haystack else None


def _format_valid(field_name: str, raw_text: str | None) -> bool | None:
    """Does the printed text parse as the thing this field claims to be?

    Handed to the SAME parsers `extraction/service._normalise` will run on it
    downstream, so a `False` here always means a real consequence there: an
    amount that fails this check is an amount `PaymentClaim` will carry as
    `None`. `None` is returned for every field with no meaningful format to
    check against — a name and a provider are whatever the receipt printed.
    """
    if not raw_text:
        return None
    text = raw_text.strip()
    match field_name:
        case "amount":
            return parse_amount(text) is not None
        case "timestamp":
            return parse_timestamp(text) is not None
        case "receiver_account":
            # A mobile number OR an IBAN: `normalize_msisdn` answers only the
            # first, and `service._normalise` explicitly keeps an unrecognised
            # value as raw rather than dropping it, so an IBAN must not be
            # reported as a badly-read phone number.
            if normalize_msisdn(text) is not None:
                return True
            return _IBAN_RE.match(text.replace(" ", "")) is not None
        case "reference_id":
            return _REFERENCE_RE.match(text) is not None
        case "sender_name" | "receiver_name":
            # The weakest check that still catches a real failure: a name that
            # contains no letter at all is a row label or a stray amount, not a
            # person. Anything stricter starts refusing Urdu script, single
            # names, and businesses called `24/7 Mart`.
            return any(character.isalpha() for character in text)
    return None


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

        # The full OCR text is read BEFORE the field evidence, not after, because
        # the evidence is grounded against it: `words_info` is what the detector
        # actually saw on the page, and `kv_result` is what the KIE head made of
        # it. Two outputs of one pass, but not the same output — a value present
        # in the second and absent from the first came from the model rather than
        # from the receipt.
        ocr_text = self._extract_ocr_text(response)

        # Build field evidence
        fields = self._build_field_evidence(raw_claim, kv, ocr_text)

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
        self, claim: RawClaim, kv: dict[str, str], ocr_text: str | None = None
    ) -> list[FieldEvidence]:
        """Build per-field evidence records, running the checks the band needs.

        Both checks used to be `None` with a "will be set later" comment, and
        nothing ever set them. Because `compute_confidence_band` treated an
        unchecked field as a doubted one, that TODO quietly banded EVERY field
        this reader could read as `low` — and once `R067` started reading
        confidences, that meant no receipt extracted by Qwen-VL could return
        VERIFIED. A check nobody performs must not masquerade as a check that
        failed; these are the checks, actually performed.

        **Format validation** is the one that can refute, and it is entirely
        deterministic: the field's printed text is handed to the same parser
        that `service._normalise` will use on it, and a value that parser
        cannot read is a value this reader did not read well enough to carry a
        verification. That is exactly what `LOW_EXTRACTION_CONFIDENCE` says —
        a statement about our reader, never about the customer.

        **Grounding** is positive-only, and that is a deliberate limitation
        rather than an oversight. `kv_result` is the KIE head's answer and
        `words_info` is the detector's; finding the value in the detector's
        text is real evidence the characters were on the page. NOT finding it
        is ambiguous: the KIE head is free to normalise what it returns
        (`Rs. 1,500.00` for a printed `1,500`), so an unmatched value is a
        reformatting artefact at least as often as it is a hallucination, and
        nobody here has measured which. Until somebody does — against captured
        responses, not against an intuition — an unmatched value is recorded as
        *unknown* and refutes nothing. Calling it a hallucination on a guess
        would put the demo's headline VERIFIED one string-normalisation quirk
        away from becoming NEEDS_REVIEW, which is the failure this whole method
        is being rewritten to remove.
        """
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
        haystack = _squash(ocr_text)

        for field_name, maybe_field in field_map.items():
            has_value = maybe_field.ok
            raw_text = maybe_field.raw_text if has_value else None
            grounded = _grounded(raw_text, haystack) if has_value else None
            format_valid = _format_valid(field_name, raw_text) if has_value else None
            band = compute_confidence_band(
                grounded=grounded,
                format_valid=format_valid,
                agreement="single_source",
                has_value=has_value,
            )
            evidence.append(
                FieldEvidence(
                    field=field_name,
                    value=maybe_field.value if has_value else None,
                    raw_text=raw_text,
                    source="vlm_kie" if has_value else "none",
                    grounded=grounded,
                    format_valid=format_valid,
                    absent_reason=(
                        maybe_field.absent_reason if not has_value else None
                    ),
                    confidence_band=band,
                )
            )

        return evidence
