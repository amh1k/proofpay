"""Pydantic models for raw VLM output and field-level evidence.

Every field is a `Maybe[T]` — a value is NEVER returned without `raw_text`,
and a null is NEVER returned without `absent_reason`. This is the contract
that prevents hallucination from becoming a false VERIFIED.

Amounts, dates, and phone numbers cross the model boundary as STRINGS.
Parsing lives in normalize.py.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ExtractionResult",
    "FieldEvidence",
    "Maybe",
    "RawClaim",
    "TamperObservation",
]

T = TypeVar("T")


class Maybe(BaseModel, Generic[T]):  # noqa: UP046 — Pydantic requires explicit Generic
    """A field that may or may not have been readable on the receipt."""

    value: T | None = None
    raw_text: str | None = Field(
        None,
        description="The EXACT characters as printed on the receipt, verbatim.",
    )
    absent_reason: Literal["not_present", "illegible", "cropped_out", "ambiguous", "obscured"] | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None

    @model_validator(mode="after")
    def _consistency(self) -> Maybe[T]:
        if self.value is not None and self.raw_text is None:
            raise ValueError("value set but no raw_text — provenance required")
        if self.value is not None and self.absent_reason is not None:
            raise ValueError("value set AND absent_reason set — contradictory")
        if self.value is None and self.absent_reason is None:
            # Treat as "not_present" by default rather than failing
            object.__setattr__(self, "absent_reason", "not_present")
        return self


class RawClaim(BaseModel):
    """Raw structured output from a receipt extractor, before normalisation."""

    provider_hint: Maybe[str] = Maybe()
    status_text: Maybe[str] = Maybe()
    amount_text: Maybe[str] = Maybe()  # TEXT, not float — parsing is ours
    currency_text: Maybe[str] = Maybe()
    reference_id: Maybe[str] = Maybe()
    sender_name: Maybe[str] = Maybe()
    receiver_name: Maybe[str] = Maybe()
    receiver_account: Maybe[str] = Maybe()
    timestamp_text: Maybe[str] = Maybe()


class FieldEvidence(BaseModel):
    """Per-field evidence record for the UI evidence breakdown."""

    field: str
    value: str | None = None
    raw_text: str | None = None
    source: Literal["vlm_kie", "vlm_json", "template_regex", "none"] = "none"
    grounded: bool | None = None
    agreement: Literal["agree", "disagree", "single_source", "n/a"] = "n/a"
    format_valid: bool | None = None
    absent_reason: str | None = None
    confidence_band: Literal["high", "low", "none"] = "none"


def compute_confidence_band(
    grounded: bool | None,
    format_valid: bool | None,
    agreement: str,
    has_value: bool,
) -> Literal["high", "low", "none"]:
    """Did any hard check REFUTE this reading? Never the model's opinion of it.

    Every input is three-state, and the middle state is the whole point:

        True   the check ran and the reading passed it
        False  the check ran and the reading FAILED it
        None   the check never ran

    The earlier form collapsed ``None`` into ``False`` -- it returned ``"low"``
    for anything that was not affirmatively grounded -- and that is not a
    nuance. ``dashscope_ocr`` passed ``grounded=None`` with the comment "Will
    be set later by grounding check", and nothing ever set it, so **every field
    the cloud reader successfully read came back "low"**. `service._normalise`
    maps ``low -> 0.5``, `DecisionPolicy.min_field_confidence` is 0.75, and
    `R067` routes any otherwise-acceptable match with a doubted field to a
    human -- so the moment the engine started reading confidences, turning the
    Qwen-VL extractor on meant no verification could ever return VERIFIED
    again. A check that was never performed is not evidence of a problem, and
    reporting it as one made a permanently-firing rule look like a tuned one.

    So: a band of ``"low"`` is an ASSERTION that something is wrong, and only a
    check that actually failed may make it. This matches the convention `core`
    already runs on -- `PaymentClaim.confidence_for` answers 1.0 for a field no
    extractor mentioned, because an extractor that reports nothing must not
    thereby fail every verification. ``"high"`` correspondingly means "nothing
    we checked refuted this", which is exactly as strong a claim as the checks
    that ran, and no stronger.

    ``"none"`` stays what it always was: there is no value here to have an
    opinion about. `service._normalise` reports no confidence key at all for
    it, which `confidence_for` reads as the fully-confident default -- absence
    is handled by the MISSING rung on the comparison ladder, not by doubt.
    """
    if not has_value:
        return "none"
    # Any one refutation is enough, and they are deliberately flat rather than
    # nested: a value the OCR never saw, a value that will not parse, and a
    # value two readers disagree about are three independent ways of being
    # wrong, and none of them needs another check to have passed first.
    if grounded is False or format_valid is False or agreement == "disagree":
        return "low"
    return "high"


class TamperObservation(BaseModel):
    """An advisory observation about the image — never a verdict."""

    code: str  # "editor_software_tag" | "near_duplicate_phash" | ...
    detail: str  # human-readable, shown verbatim in the evidence panel
    severity: Literal["info", "notice"] = "info"  # NOTE: no "critical". By design.
    analyzer_version: str = "tamper/v1"


class ExtractionResult(BaseModel):
    """Complete output of the extraction pipeline."""

    claim: RawClaim
    ocr_text: str | None = None
    fields: list[FieldEvidence] = Field(default_factory=list)
    tamper_observations: list[TamperObservation] = Field(default_factory=list)
    extractor_id: str
    preproc_version: str
    latency_ms: int = 0
    degraded: bool = False
    degraded_reason: str | None = None
