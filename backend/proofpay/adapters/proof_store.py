"""Which proof images this merchant has already accepted. An adapter, not core.

`core` owns no clock, no filesystem and no hash function: it is *told* what the
bytes of a proof were (`PaymentClaim.proof_sha256`) and *told* what was accepted
before (`decide(prior_proofs=...)`), and it does dictionary lookups over the
two. Computing the hash and remembering the answer is this layer's job, which is
why this module lives under `adapters/` rather than beside the rule table.

This is the same shape as the allocation store one layer down: rows a caller
reads, handed to the engine, which indexes and explains them. `core/proofs.py`
holds the reasoning about *what counts* as reuse — the same-order exemption
above all — and nothing here re-litigates it.

**This implementation is in memory, and that is a stated stage, not an
oversight.** The real store already exists: `db/models/proof.py` declares
`payment_proofs.sha256_hash` under a unique index on
`(merchant_id, sha256_hash)`, and in production the row is written in the same
transaction as the allocation. The demo path never opens a database session, so
this dict is what stands in until it does — exactly as `api/v1/idempotency.py`
stands in for `idempotency_records`. Swapping it for a query means changing
`prior_proofs()` and `record_accepted()` and nothing above them.

**The recording rule, which is load-bearing and must survive refactoring.**

    A proof is recorded when the decision it produced was VERIFIED **and the
    merchant then approved the order**. Both, not either.

Two independent reasons, and the second one has a stage in front of it:

1. *It is what the claim means.* In production the proof row is written beside
   the allocation, so "this image is in the store" means "this image already
   got paid credit somewhere". A submission that was itself refused consumed
   nothing, and re-sending it is not reuse of anything — telling a merchant
   that a screenshot they already rejected is now a duplicate would be
   accusing them of their own caution.

   The approval half of the rule is the same sentence read carefully, and it
   was missing: for a while a proof was written four lines after `decide()`,
   with no allocation and no approval anywhere, so merely LOOKING at a receipt
   was recorded as having accepted it. That is not a theoretical gap. A shop
   with two open orders of the same value — the ordinary case for a
   single-product seller — mis-picks in the order picker, sees VERIFIED, backs
   out without approving, and re-checks the same receipt against the right
   order. Under the old rule the second check answered DUPLICATE / PROOF_REUSED
   and told the merchant to ask an honest customer for a fresh payment, on the
   strength of the merchant's own mis-click. Nothing had been counted,
   allocated or approved. So the write moved to where the merchant actually
   commits: `record_pending` when the engine says VERIFIED, `approve` when the
   merchant presses the approve action, and only `approve` makes the proof
   visible to a later verification.

   VERIFIED is still required, and "approve anyway" on a refused verdict still
   records nothing. It is a deliberate belt-and-braces: an override is a
   decision the merchant is allowed to make, but letting one write proof
   history would put the byte-identical G01/D01 pair back in play (reason 2),
   and there is no case in the product that needs it.

2. *It is what keeps the demo order-independent.* `fixtures/demo/images/G01.jpg`
   and `D01.jpg` are byte-identical, and the demo submits G01 against
   order_demo_1001 and D01 against order_demo_1003. Trace every ordering under
   this rule: 1002, 1004 and 1005 never verify, so they record nothing at all;
   1001 verifies and records `sha(G01) -> order_demo_1001`; 1003 carries an
   allocation, so `R020` takes it first whatever the proof history says, and it
   answers DUPLICATE / TXN_ALREADY_ALLOCATED exactly as before. Run 1003 first
   and it still records nothing, so 1001 is still VERIFIED. Run 1001 twice and
   the same-order exemption in `check_proof` returns no conflict.

   Under the naive alternative — record every submission — running 1003 before
   1001 would flip **order_demo_1001 from VERIFIED to DUPLICATE on stage**.
   That is the failure this rule exists to prevent, and it is why "simplify
   this to record everything" is not a simplification.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from proofpay.core.models import ProofFingerprint

__all__ = [
    "approve",
    "content_sha256",
    "prior_proofs",
    "record_accepted",
    "record_pending",
    "reset",
]

#: Accepted proofs, per merchant. A merchant only ever sees their own history,
#: which is the tenant boundary the `(merchant_id, sha256_hash)` unique index
#: draws in the database; keying the dict by merchant makes it impossible to
#: leak one merchant's proof into another's decision by forgetting a filter.
_accepted: dict[str, dict[str, ProofFingerprint]] = {}

#: Proofs that verified but that nobody has approved yet, keyed by the
#: verification that produced them — the id the approve call arrives with.
#: Deliberately NOT keyed by hash: two orders can be checked against the same
#: image before either is approved, and the one that gets approved is the one
#: that must be recorded. Nothing here is visible to `prior_proofs`, which is
#: the entire point: a pending proof has consumed nothing.
_pending: dict[str, tuple[str, ProofFingerprint]] = {}


def content_sha256(content: bytes) -> str:
    """The content hash of an uploaded proof, lowercase hex.

    One function so that the hash the engine compares, the hash the store keys
    on, and the hash the fixture lookup uses are provably the same bytes run
    through the same algorithm. They were already the same by coincidence in
    three places; a reuse verdict is not a thing to leave resting on a
    coincidence.
    """
    return hashlib.sha256(content).hexdigest()


def prior_proofs(merchant_id: str) -> tuple[ProofFingerprint, ...]:
    """Everything this merchant has already had accepted, for `decide()`.

    Returns a tuple rather than the live mapping: the engine must not be handed
    a structure that can change under it, and a caller must not be able to
    record a proof by mutating what it read.
    """
    return tuple(_accepted.get(merchant_id, {}).values())


def record_accepted(
    merchant_id: str,
    *,
    sha256: str,
    order_id: str | None,
    order_ref: str | None = None,
    verification_id: str | None = None,
    submitted_at: datetime | None = None,
) -> None:
    """Remember that this image was accepted for this order.

    First writer wins, mirroring the unique index this will become: a second
    acceptance of the same bytes must not overwrite the record of the first,
    because the first is the one a later reuse finding has to name.

    `order_ref` is the merchant's own label for the order (`ORD-1041`) and is
    what a later conflict will actually say out loud; `order_id` is the key the
    same-order exemption compares. Both, because they answer different
    questions — see `ProofConflict.name`.
    """
    history = _accepted.setdefault(merchant_id, {})
    if sha256 in history:
        return
    history[sha256] = ProofFingerprint(
        sha256=sha256,
        order_id=order_id,
        order_ref=order_ref,
        verification_id=verification_id,
        submitted_at=submitted_at,
    )


def record_pending(
    merchant_id: str,
    *,
    verification_id: str,
    sha256: str,
    order_id: str | None,
    order_ref: str | None = None,
    submitted_at: datetime | None = None,
) -> None:
    """Hold a verified proof aside until the merchant commits to the order.

    Overwrites freely, unlike `record_accepted`: a verification id names one
    submission, so a second call under the same id is the same submission being
    re-derived (an idempotent replay), not a competing claim on the bytes. The
    first-writer-wins rule belongs on the accepted side, where it protects the
    record a later reuse finding has to name.
    """
    _pending[verification_id] = (
        merchant_id,
        ProofFingerprint(
            sha256=sha256,
            order_id=order_id,
            order_ref=order_ref,
            verification_id=verification_id,
            submitted_at=submitted_at,
        ),
    )


def approve(verification_id: str) -> bool:
    """The merchant released the goods: this image is now spent.

    Returns whether anything moved, so a caller can tell "approved" from
    "there was nothing here to approve" — a refused verdict, an unknown id, or
    a second approval of the same verification — without a second lookup.
    Idempotent by construction: the pending entry is consumed, and
    `record_accepted` refuses to overwrite an existing record anyway.
    """
    entry = _pending.pop(verification_id, None)
    if entry is None:
        return False
    merchant_id, proof = entry
    record_accepted(
        merchant_id,
        sha256=proof.sha256,
        order_id=proof.order_id,
        order_ref=proof.order_ref,
        verification_id=proof.verification_id,
        submitted_at=proof.submitted_at,
    )
    return True


def reset() -> None:
    """Forget everything. Wired into `POST /api/v1/demo/reset`.

    Without this the demo accumulates across runs: a presenter who checks the
    same receipt twice in one session would, on the second run, be told it was
    a duplicate — which is true, and is not what they meant to show.

    Both stages, or a reset would leave a half-approved proof able to become a
    duplicate finding after the demo had supposedly been cleared.
    """
    _accepted.clear()
    _pending.clear()
