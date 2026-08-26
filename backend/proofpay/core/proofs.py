"""Screenshot-reuse detection: pure observation, never enforcement.

`core/duplicates.py` names this module in its own closing line — "screenshot
reuse (`PROOF_REUSED`) is a separate signal, computed from proof hashes rather
than allocations, and is not implemented here" — and this is that signal. The
two are deliberately built the same way, because they answer the same shape of
question about two different objects:

    duplicates.py   this TRANSACTION was already consumed by another order
    proofs.py       this IMAGE was already accepted for another order

The distinction matters to a merchant because the two are different
accusations. A reused transaction means the money arrived once and is being
spent twice — the ledger row is real, and it is already gone. A reused
screenshot means the *picture* is a re-run: the same JPEG forwarded to a second
merchant, or sent back to the same one under a new order. The second is the
cheapest payment fraud there is, and the one a human is worst at catching,
because nobody remembers a receipt they glanced at last Tuesday.

**Detection here is advisory; the database is authoritative.** `payment_proofs`
carries `sha256_hash` under a unique index on `(merchant_id, sha256_hash)`,
written in the same transaction as the accepting decision. That constraint is
the guarantee. This module does the narrower, complementary thing: given the
proofs a caller has already read, it detects and *explains* reuse early enough
that the engine can answer `DUPLICATE` with something actionable instead of
surfacing a raw integrity error.

The exemption that carries all the weight, exactly as in `duplicates.py`:

* accepted **for another order** — the same picture is being spent twice.
  `PROOF_REUSED`, `DUPLICATE`.
* accepted **for this same order** — a page refresh, a retried upload, a
  merchant who tapped twice. Not fraud and not a duplicate. Reporting it as one
  turns idempotency into an accusation, and it is the single most likely way
  for this feature to hurt an honest merchant.

**Why there is no perceptual hash here, deliberately.**

The obvious extension is near-duplicate detection: catch a re-cropped or
re-compressed screenshot, not only a byte-identical one. `extraction/tamper.py`
already computes a 256-bit pHash and dHash on every upload, so the input would
be free. It is not implemented, and the reason is a measurement rather than a
preference. Over the 30 committed fixtures, every pairwise pHash distance was
taken:

    D01 <-> G01     0     byte-identical, genuine reuse
    D02 <-> G02     0     byte-identical, genuine reuse
    S01 <-> S06     0     DIFFERENT payments, different senders, different
                          amounts, different reference ids — and an identical
                          256-bit perceptual hash
    G03 <-> D03    14     the pair a perceptual rule is supposed to catch

Forty-five unrelated pairs sit strictly closer than the one true positive, and
`S01 <-> S06` is a false positive at distance *zero* — so there is no cut-point,
not even "identical pHash", that separates reuse from coincidence here. That is
not a fixture artefact. Every receipt in the corpus is one template with the
numbers changed, which is precisely what real receipts from one payment app
are: pHash measures the template, and the template is the part that is supposed
to be the same. A near-duplicate rule tuned to catch a genuine crop would tell a
merchant that two unrelated customers paying through the same app had reused
one screenshot.

So exact sha256 only, which is also why nothing in this module needs a
threshold: an equality test on a content hash has no cut-point to tune, so no
number escapes `DecisionPolicy.fingerprint()`. Revisit when a signal exists
that actually separates — a crop-invariant hash over the receipt's text region,
or the extracted field set — and revisit it with a measurement, not an
intuition.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from proofpay.core.models import ProofFingerprint
from proofpay.core.reasons import ObservationCode, ReasonCode

__all__ = [
    "ProofConflict",
    "ProofIndex",
    "ProofReport",
    "check_proof",
    "index_proofs",
    "no_proof_history",
]

#: Sorts before every real timestamp, so a proof that never recorded one still
#: orders deterministically and still loses to one that did. Same sentinel and
#: same reasoning as `core/duplicates.py`.
_EPOCH = datetime(1, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProofConflict:
    """One image, already accepted for a different order.

    Carries the *other* order's id for the same reason `AllocationConflict`
    does: it is the only actionable thing a merchant can be told. "We have seen
    this picture before" invites an argument; "this picture already paid order
    ORD-1041" ends one.
    """

    #: The content hash both submissions share.
    sha256: str
    #: The order that already holds this image. Never the order under
    #: verification — that case is idempotency, not a conflict. `None` when the
    #: earlier proof was recorded with no order attached: still genuine reuse,
    #: simply with nothing to point the merchant at.
    reused_from_order_id: str | None = None
    #: The merchant's own name for that order, when the store recorded one.
    #: See `name` below for why both are carried.
    reused_from_order_ref: str | None = None
    submitted_at: datetime | None = None
    verification_id: str | None = None

    @property
    def reason(self) -> ReasonCode:
        return ReasonCode.PROOF_REUSED

    @property
    def name(self) -> str | None:
        """What to CALL the earlier order when telling a merchant about it.

        The reference when there is one, the internal id when there is not.
        Emphatically not the other way round: `order_demo_1001` is a database
        key, it appears on no screen the merchant can search, and a row reading
        "already used for order_demo_1001" is an instruction to go and find
        something that does not exist as far as they are concerned. The order
        picker they clicked a moment earlier called that same order `ORD-G01`.

        The id survives as the fallback because a conflict with a name nobody
        can read still beats a conflict with no name at all — `check_proof`
        needs the id regardless, and this is a display choice made at the point
        of display rather than a second field on the store.
        """
        return self.reused_from_order_ref or self.reused_from_order_id

    @property
    def observation(self) -> str | None:
        """The earlier order, as a neutral note the frontend can surface.

        `Decision` has no field for "which earlier order", and adding one would
        ripple through the API schema and every committed mock. The extractor
        has already established `CODE:detail` as the shape of a note carrying a
        payload (`IMAGE_PHASH:phash:...`), so this follows it. It is a fact that
        was noticed, not a verdict — the verdict is the reason code above.

        `None` rather than a note with an empty tail when the earlier order is
        unknown: `frontend/src/lib/verdict.ts` scans observations for an order
        reference, and a note that promises one and delivers nothing is worse
        than no note.
        """
        if not self.name:
            return None
        return f"{ObservationCode.PROOF_PREVIOUSLY_SUBMITTED}:{self.name}"


@dataclass(frozen=True, slots=True)
class ProofIndex:
    """Previously accepted proofs, keyed by the image bytes they were.

    The database permits at most one accepted proof per `(merchant_id,
    sha256)`, so this map is one-to-one when the input is well formed. When it
    is not — a caller that passed the same image twice, a stale read — the
    earliest submission wins, mirroring the first-writer-wins behaviour of the
    unique index. Picking an arbitrary one instead would make a `DUPLICATE`
    verdict depend on dict ordering.
    """

    by_sha256: Mapping[str, ProofFingerprint]
    #: Hashes that arrived with more than one accepted proof. Non-empty means
    #: the caller's view disagrees with the database's invariant.
    contested: frozenset[str] = frozenset()

    def for_sha256(self, sha256: str) -> ProofFingerprint | None:
        return self.by_sha256.get(sha256)

    def __len__(self) -> int:
        return len(self.by_sha256)


#: The answer when there is nothing to compare against: no hash on the claim, or
#: no history to compare it to. A shared empty instance rather than a fresh one
#: per call, exactly as `NO_AMOUNT_EVIDENCE` is in `compare/amount.py`.
_EMPTY_INDEX: ProofIndex = ProofIndex(by_sha256=MappingProxyType({}))


def _proof_order(proof: ProofFingerprint) -> tuple[datetime, str, str]:
    """Total order over proofs: earliest first, then order id, then id.

    Total rather than merely sorted-by-time, because two proofs recorded in the
    same millisecond must still resolve the same way on every replay.
    """
    return (
        proof.submitted_at or _EPOCH,
        proof.order_id or "",
        proof.verification_id or "",
    )


def index_proofs(proofs: Iterable[ProofFingerprint]) -> ProofIndex:
    """Group prior proofs by content hash, resolving collisions deterministically.

    Callers pass only proofs that were **accepted** — one that was itself
    refused consumed nothing, and re-submitting it is not reuse of anything.
    This layer has no way to tell the difference (a `ProofFingerprint` carries
    no status), so that filtering is the adapter's job and is documented here
    rather than guessed at, exactly as `index_allocations` documents the
    RELEASED case.
    """
    grouped: dict[str, list[ProofFingerprint]] = {}
    for proof in proofs:
        grouped.setdefault(proof.sha256, []).append(proof)

    winners = {sha256: min(group, key=_proof_order) for sha256, group in grouped.items()}
    contested = frozenset(sha for sha, group in grouped.items() if len(group) > 1)
    return ProofIndex(by_sha256=MappingProxyType(winners), contested=contested)


@dataclass(frozen=True, slots=True)
class ProofReport:
    """What proof history says about this submission.

    Deliberately thinner than `DuplicateReport`, and the asymmetry is real
    rather than an omission. A ranking has many candidates, so allocation state
    has to be reported per candidate; a submission has exactly one set of bytes,
    so there is exactly one question to answer about it.
    """

    conflict: ProofConflict | None = None
    #: True when the caller's history was self-contradictory for this hash.
    contested: bool = False

    @property
    def is_reused(self) -> bool:
        """The predicate the rule table's `R025` reads."""
        return self.conflict is not None

    @property
    def reasons(self) -> tuple[ReasonCode, ...]:
        if self.conflict is None:
            return ()
        return (ReasonCode.PROOF_REUSED,)

    @property
    def observations(self) -> tuple[str, ...]:
        """The earlier order as a note, or nothing. Never a verdict."""
        if self.conflict is None or self.conflict.observation is None:
            return ()
        return (self.conflict.observation,)


#: No history and no finding. Shared, for the same reason `_EMPTY_INDEX` is.
NO_PROOF_HISTORY: ProofReport = ProofReport()


def no_proof_history() -> ProofReport:
    """The empty report, as a function for callers that prefer one."""
    return NO_PROOF_HISTORY


def check_proof(
    sha256: str | None,
    *,
    order_id: str | None,
    proofs: ProofIndex | None = None,
) -> ProofReport:
    """Has this exact image already been accepted for a *different* order?

    `sha256 is None` — an extraction path that never hashed the image — returns
    the empty report rather than guessing. A caller that cannot say what the
    bytes were must not be able to produce a reuse verdict out of that silence.

    `order_id is None` — a proof submitted with no order attached — means there
    is no "same order" to be idempotent about, so any earlier acceptance is a
    conflict.
    """
    if sha256 is None:
        return NO_PROOF_HISTORY
    index = proofs if proofs is not None else _EMPTY_INDEX
    prior = index.for_sha256(sha256)
    if prior is None:
        return NO_PROOF_HISTORY
    if order_id is not None and prior.order_id == order_id:
        # The same picture, sent again for the same order: a retried upload, a
        # double tap, a page refresh. `check_candidate` draws exactly this line
        # for allocations and for exactly this reason — without it, the most
        # ordinary thing a merchant does becomes an accusation of fraud, and it
        # is the failure mode most likely to be found by a real user rather
        # than by a test.
        return NO_PROOF_HISTORY
    return ProofReport(
        conflict=ProofConflict(
            sha256=sha256,
            reused_from_order_id=prior.order_id,
            reused_from_order_ref=prior.order_ref,
            submitted_at=prior.submitted_at,
            verification_id=prior.verification_id,
        ),
        contested=sha256 in index.contested,
    )
