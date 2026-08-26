"""The frozen contracts every layer of ProofPay shares.

All domain types are `@dataclass(frozen=True, slots=True, kw_only=True)`:

* `frozen` - hashable, safe to share across candidates, no accidental mutation
  half way down the pipeline.
* `slots` - a typo raises `AttributeError` instead of silently inventing a
  field, which on a fraud engine is the difference between a bug and a loss.
* `kw_only` - `PaymentClaim(amount=..., sender_name=...)` at every call site.
  Positional arguments on a nine-field claim is exactly how someone eventually
  swaps the claimed amount with the ledger amount and inverts the fraud logic.

Pydantic belongs at the HTTP/adapter boundary, where untrusted JSON arrives.
Inside `core` the data has already been validated, so these stay plain
dataclasses: no import weight, no validation-error surface, no friction with
property-based tests.

**Optionality is meaningful.** A `PaymentClaim` field is `None` when OCR could
not read it - that is a fact about the evidence, not a placeholder. Never
substitute a default for an unread field; the comparisons have `*_MISSING`
levels precisely so an unread field is scored as absent rather than as wrong.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from proofpay.core.compare.levels import FieldOutcome
from proofpay.core.money import Money
from proofpay.core.reasons import ReasonCode, Risk, Source, Status
from proofpay.core.timex import ClaimedInstant

__all__ = [
    "Allocation",
    "Decision",
    "FieldOutcome",
    "LedgerTxn",
    "Order",
    "PaymentClaim",
    "ProofFingerprint",
    "ScoredCandidate",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentClaim:
    """What the screenshot appears to assert. Untrusted, and mostly optional.

    This object never proves anything. It is one side of every comparison and
    the sole thing the customer controls.
    """

    claim_id: str
    merchant_id: str | None = None
    proof_id: str | None = None
    #: Content hash of the proof image, lowercase hex sha256. The contrast with
    #: `proof_id` above is the whole point of the field: `proof_id` names the
    #: *submission* (the API mints a fresh uuid per upload, so the same picture
    #: sent twice gets two of them), while this names the *bytes*, which is the
    #: only thing that can be recognised across two submissions. `None` when the
    #: caller did not hash the image; core never hashes anything itself, so an
    #: extractor path that reports nothing here simply cannot produce a reuse
    #: finding — see `core/proofs.py`.
    proof_sha256: str | None = None

    provider: str | None = None          # "easypaisa", "jazzcash", "raast", ...
    amount: Money | None = None          # claimed amount, minor units
    sender_name: str | None = None       # raw text as read; normalisation is a step, not a field
    receiver_name: str | None = None
    sender_account: str | None = None    # often masked: "03XX-XXXXX67"
    receiver_account: str | None = None
    reference_id: str | None = None      # provider TID / external transaction id
    occurred_at: ClaimedInstant | None = None

    #: Per-field extraction confidence in 0.0..1.0, keyed by field name. An
    #: absent key means "not reported", which is not the same as low confidence.
    field_confidences: Mapping[str, float] = field(default_factory=dict)
    #: Neutral notes from parsing (see `ObservationCode`), e.g. an ambiguous
    #: thousands separator. These reach the decision engine; they are not verdicts.
    notes: tuple[str, ...] = ()
    parser_version: str = "unknown"

    def confidence_for(self, field_name: str, default: float = 1.0) -> float:
        """Extraction confidence for one field, defaulting to fully confident.

        Extractors that do not report confidences must not be penalised, so the
        absent case reads as 1.0 rather than 0.0.
        """
        return self.field_confidences.get(field_name, default)


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerTxn:
    """A merchant-side transaction record: the source of truth about money.

    `source` carries provenance, because only ledger-grade provenance may
    support `VERIFIED` (see `TRUSTED_LEDGER_SOURCES`).
    """

    txn_id: str
    amount: Money
    occurred_at: datetime                       # timezone-aware, normalised to UTC
    merchant_id: str | None = None
    provider: str | None = None
    external_id: str | None = None              # provider-side TID, if distinct from txn_id
    sender_name: str | None = None
    receiver_name: str | None = None
    sender_account: str | None = None
    receiver_account: str | None = None
    source: Source = Source.MERCHANT_LEDGER
    ingested_at: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def reference_id(self) -> str | None:
        """The identifier a receipt would print: the provider's, else ours."""
        return self.external_id or self.txn_id


@dataclass(frozen=True, slots=True, kw_only=True)
class Order:
    """What the merchant asked for.

    `expected` may be None: a proof can be submitted with no order attached, in
    which case the engine can still compare claim against ledger but cannot
    assert that the order is fully paid.
    """

    order_id: str
    expected: Money | None = None
    merchant_id: str | None = None
    created_at: datetime | None = None
    reference: str | None = None                # merchant's own order reference


@dataclass(frozen=True, slots=True, kw_only=True)
class Allocation:
    """A transaction consumed by an order.

    The database enforces uniqueness; the engine only observes and explains the
    conflict.
    """

    txn_id: str
    order_id: str
    verification_id: str | None = None
    allocated_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProofFingerprint:
    """One proof image this merchant has already accepted, by content hash.

    The exact sibling of `Allocation`, one layer over: an `Allocation` records
    that a *transaction* was consumed by an order, and this records that an
    *image* was. Both are read from a store by a caller and handed to the
    engine; neither is computed inside `core`, which owns no image toolkit and
    no database.

    `order_id` is what makes the record worth keeping. "This picture has been
    seen before" is a curiosity; "this picture already paid order ORD-1041" is
    something a merchant can act on, and it is also what separates fraud from a
    page refresh — see `check_proof`.
    """

    #: Lowercase hex sha256 of the image bytes, exactly as `PaymentClaim.proof_sha256`.
    sha256: str
    #: The order this proof was accepted for. `None` for a proof recorded with
    #: no order attached, which can never be exempted as a re-submission. This
    #: is the INTERNAL id, and the same-order exemption in `check_proof` is an
    #: equality test on it, so it must stay the id and never the reference.
    order_id: str | None = None
    #: What the merchant calls that order — `Order.reference`, e.g. `ORD-1041`.
    #: Carried alongside the id rather than instead of it because the two do
    #: different jobs: the id decides whether this is reuse, and the reference
    #: is the only half a merchant can look up. `PROOF_PREVIOUSLY_SUBMITTED`
    #: publishing `order_demo_1001` — an identifier that appears nowhere in the
    #: merchant's own order list — is a row telling somebody to go and find a
    #: thing that, as far as they can see, does not exist.
    order_ref: str | None = None
    verification_id: str | None = None
    submitted_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoredCandidate:
    """One retrieved transaction, scored against the claim.

    `outcomes` is keyed by comparison field name ("sender_name", "amount",
    "timestamp", "reference", ...) so a rule can inspect one field's level
    directly, e.g. `cand.outcomes["reference"].level_code == "REF_EXACT"`.
    """

    txn: LedgerTxn
    score: float
    outcomes: Mapping[str, FieldOutcome] = field(default_factory=dict)

    @property
    def txn_id(self) -> str:
        return self.txn.txn_id

    @property
    def evidence(self) -> tuple[FieldOutcome, ...]:
        """Field outcomes in a deterministic order, ready to render."""
        return tuple(self.outcomes[k] for k in sorted(self.outcomes))

    def sort_key(self) -> tuple[float, str]:
        """Total, stable ranking key: best score first, ties broken by id.

        Float ties plus list-sort stability plus a dict-ordered candidate list
        is a reproducibility bug waiting for a demo; this makes the order a
        function of the data alone.
        """
        return (-self.score, self.txn.txn_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class Decision:
    """The engine's verdict, and everything needed to reconstruct it later.

    `confidence` is confidence in *this decision*, derived from candidate margin
    and evidence coverage. It is explicitly **not** a probability of fraud, and
    must never be presented as one.

    `ruleset_version` + `policy_fingerprint` + `engine_version` + `evaluated_at`
    are what make an old decision explainable: the same inputs, replayed against
    the same pinned rules and thresholds, must reproduce it exactly.
    """

    status: Status
    risk: Risk
    confidence: float
    reasons: tuple[ReasonCode, ...]
    matched_txn_id: str | None
    fired_rule_id: str
    evidence: tuple[FieldOutcome, ...]
    observations: tuple[str, ...]
    ruleset_version: str
    policy_fingerprint: str
    engine_version: str
    evaluated_at: datetime          # the `now` that was handed in, never read from a clock

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be within 0.0..1.0")
        if self.status is Status.VERIFIED and self.matched_txn_id is None:
            # The one architectural commitment that must hold at the type level:
            # no screenshot-derived signal alone establishes that payment occurred.
            raise ValueError("VERIFIED requires a matched ledger transaction")

    def evidence_by_field(self) -> Mapping[str, FieldOutcome]:
        return MappingProxyType({e.field: e for e in self.evidence})
