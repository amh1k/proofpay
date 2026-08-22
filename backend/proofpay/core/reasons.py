"""Stable machine identifiers: statuses, risks, sources, reasons, observations.

Every member of every enum here is a **contract**. These strings land in the
database, the API payload, the frontend translation table and every past
decision ever stored. Human-facing labels live in the UI and in `Level.label`,
and may be reworded freely. A code may be added; it may never be renamed,
repurposed or removed, because doing so retroactively changes the meaning of
decisions already taken.

`StrEnum` (3.11+) serialises straight to JSON as a plain string with no `.value`
ceremony, and compares equal to the bare string, which keeps golden files
readable.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "PARTIALLY_TRUSTED_SOURCES",
    "TRUSTED_LEDGER_SOURCES",
    "ObservationCode",
    "ReasonCode",
    "Risk",
    "Source",
    "Status",
]


class Status(StrEnum):
    """The five verification outcomes (system design 12.1)."""

    VERIFIED = "VERIFIED"          # trusted transaction exists and critical fields agree
    UNMATCHED = "UNMATCHED"        # no trusted transaction currently matches
    SUSPICIOUS = "SUSPICIOUS"      # a candidate exists but critical evidence conflicts
    DUPLICATE = "DUPLICATE"        # the transaction or proof was already consumed
    NEEDS_REVIEW = "NEEDS_REVIEW"  # incomplete, ambiguous or unavailable evidence


class Risk(StrEnum):
    """Ordinal risk band. Deliberately not a percentage: a merchant acts on a
    band, and a fabricated probability invites false precision."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Source(StrEnum):
    """Provenance of a transaction record — this is the trust model in code.

    Only ledger-grade provenance may support `VERIFIED`; a screenshot is a claim
    about the world, never evidence that money moved.
    """

    MERCHANT_LEDGER = "MERCHANT_LEDGER"          # trusted merchant-side record
    PROVIDER_API = "PROVIDER_API"                # trusted provider record
    SIMULATOR = "SIMULATOR"                      # trusted for demo only
    MERCHANT_CSV = "MERCHANT_CSV"                # partially trusted import
    MANUAL_ENTRY = "MANUAL_ENTRY"                # partially trusted, human keyed
    CUSTOMER_SCREENSHOT = "CUSTOMER_SCREENSHOT"  # untrusted; claim only


#: Sources that may support a `VERIFIED` decision. The engine's post-condition
#: assertion checks membership here, so widening trust is a one-line, reviewable
#: change rather than an edit scattered through the rule table.
TRUSTED_LEDGER_SOURCES: frozenset[Source] = frozenset(
    {Source.MERCHANT_LEDGER, Source.PROVIDER_API, Source.SIMULATOR}
)

#: Sources that are real merchant-side records but not ledger-grade: a human
#: typed them, or a spreadsheet did. They are evidence worth showing and worth
#: matching against, and they are not evidence enough to release goods on their
#: own, so a match against one is routed to `NEEDS_REVIEW` by a rule (`R065`)
#: rather than by the post-condition assertion. A source in neither set — today
#: only `CUSTOMER_SCREENSHOT` — is not evidence at all, and reaching VERIFIED on
#: one is a bug in the rule table that the assertion exists to catch.
PARTIALLY_TRUSTED_SOURCES: frozenset[Source] = frozenset(
    {Source.MERCHANT_CSV, Source.MANUAL_ENTRY}
)


class ReasonCode(StrEnum):
    """Why the engine decided what it decided. Ordered by the rule that fired."""

    # Retrieval / matching structure
    NO_CANDIDATES = "NO_CANDIDATES"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
    TXN_ALREADY_ALLOCATED = "TXN_ALREADY_ALLOCATED"
    PROOF_REUSED = "PROOF_REUSED"

    # Amount axis A: ledger vs order expectation (a commercial outcome)
    AMOUNT_EXACT = "AMOUNT_EXACT"
    AMOUNT_UNDERPAID = "AMOUNT_UNDERPAID"
    AMOUNT_OVERPAID = "AMOUNT_OVERPAID"
    MISSING_ORDER_AMOUNT = "MISSING_ORDER_AMOUNT"

    # Amount axis B: claim vs ledger (an integrity signal; the sign is the signal)
    CLAIM_CONSISTENT = "CLAIM_CONSISTENT"
    CLAIM_INFLATED = "CLAIM_INFLATED"
    CLAIM_DEFLATED = "CLAIM_DEFLATED"

    # Field disagreement
    NAME_MISMATCH = "NAME_MISMATCH"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    TIMESTAMP_MISMATCH = "TIMESTAMP_MISMATCH"
    TIME_WHOLE_HOUR_OFFSET = "TIME_WHOLE_HOUR_OFFSET"

    # Evidence quality
    SOURCE_PARTIALLY_TRUSTED = "SOURCE_PARTIALLY_TRUSTED"
    TAMPER_OBSERVATIONS = "TAMPER_OBSERVATIONS"
    SCREENSHOT_ONLY_EVIDENCE = "SCREENSHOT_ONLY_EVIDENCE"
    LOW_EXTRACTION_CONFIDENCE = "LOW_EXTRACTION_CONFIDENCE"

    # Positive evidence
    STRONG_FIELD_AGREEMENT = "STRONG_FIELD_AGREEMENT"


class ObservationCode(StrEnum):
    """Neutral things noticed while parsing or comparing — never a verdict.

    Observations travel as plain strings in `Decision.observations` and in the
    notes returned by the normalisers. They exist so that a borderline case can
    be pushed to review with a specific, auditable justification instead of a
    vague hunch. `StrEnum` members *are* strings, so appending a member to a
    `list[str]` is well typed and compares equal to the bare literal.
    """

    # Amount parsing
    AMOUNT_OCR_GLYPH_FIXUP = "AMOUNT_OCR_GLYPH_FIXUP"
    AMOUNT_SEPARATOR_AMBIGUOUS = "AMOUNT_SEPARATOR_AMBIGUOUS"
    AMOUNT_NON_ASCII_DIGITS = "AMOUNT_NON_ASCII_DIGITS"

    # Time reading
    TIME_MERIDIEM_AMBIGUOUS = "TIME_MERIDIEM_AMBIGUOUS"
    TIME_WHOLE_HOUR_OFFSET = "TIME_WHOLE_HOUR_OFFSET"
    TIME_DATE_INFERRED = "TIME_DATE_INFERRED"
    TIME_TZ_ASSUMED = "TIME_TZ_ASSUMED"

    # Amount integrity shape
    CLAIM_INFLATED_ROUND = "CLAIM_INFLATED_ROUND"

    # Names
    NAME_MASKED = "NAME_MASKED"
    NAME_COMMON_TOKENS_ONLY = "NAME_COMMON_TOKENS_ONLY"

    # Image forensics (produced above core, consumed as opaque strings)
    IMAGE_EXIF_MISSING = "IMAGE_EXIF_MISSING"
    IMAGE_EDITOR_SIGNATURE = "IMAGE_EDITOR_SIGNATURE"
    IMAGE_ELA_ANOMALY = "IMAGE_ELA_ANOMALY"
    IMAGE_RECOMPRESSED = "IMAGE_RECOMPRESSED"
