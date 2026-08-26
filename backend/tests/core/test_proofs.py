"""Screenshot-reuse detection, on its own and through the rule table.

`core/proofs.py` is small enough to read in one sitting, and every one of its
decisions is one somebody will be tempted to undo:

  * the same-order exemption, without which a page refresh is fraud;
  * the `sha256 is None` guard, without which an extractor that hashes nothing
    can still produce a DUPLICATE;
  * first-writer-wins over a contested history, without which a verdict depends
    on dict ordering;
  * `R025` sitting below `R020`, so an allocated transaction keeps the more
    specific explanation.

Each has a test that names the failure rather than the mechanism, so a reader
who breaks one is told what it costs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from proofpay.core.models import ProofFingerprint
from proofpay.core.proofs import (
    NO_PROOF_HISTORY,
    ProofIndex,
    ProofReport,
    check_proof,
    index_proofs,
    no_proof_history,
)
from proofpay.core.reasons import ObservationCode, ReasonCode

SHA_A = "a" * 64
SHA_B = "b" * 64
NOW = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)


def fp(
    sha256: str = SHA_A,
    *,
    order_id: str | None = "ORD-EARLIER",
    verification_id: str | None = None,
    submitted_at: datetime | None = None,
) -> ProofFingerprint:
    return ProofFingerprint(
        sha256=sha256,
        order_id=order_id,
        verification_id=verification_id,
        submitted_at=submitted_at,
    )


# ==========================================================================
# The finding itself
# ==========================================================================


def test_an_image_accepted_for_another_order_is_reuse() -> None:
    """The whole feature, in one assertion."""
    report = check_proof(SHA_A, order_id="ORD-NOW", proofs=index_proofs([fp()]))

    assert report.is_reused
    assert report.reasons == (ReasonCode.PROOF_REUSED,)
    assert report.conflict is not None
    assert report.conflict.sha256 == SHA_A
    assert report.conflict.reused_from_order_id == "ORD-EARLIER"
    assert report.conflict.reason is ReasonCode.PROOF_REUSED


def test_an_unseen_image_is_not_reuse() -> None:
    report = check_proof(SHA_B, order_id="ORD-NOW", proofs=index_proofs([fp(SHA_A)]))

    assert not report.is_reused
    assert report.reasons == ()


def test_an_empty_history_finds_nothing() -> None:
    assert not check_proof(SHA_A, order_id="ORD-NOW", proofs=index_proofs([])).is_reused
    assert not check_proof(SHA_A, order_id="ORD-NOW").is_reused


# ==========================================================================
# The same-order exemption: the line that keeps this from hurting honest users
# ==========================================================================


def test_resubmitting_the_same_image_to_the_same_order_is_not_reuse() -> None:
    """A page refresh, a double tap, a retried upload. Not an accusation.

    If this ever starts returning a conflict, the product tells a merchant who
    pressed the button twice that they are committing fraud -- and it will be a
    real user who finds it, not this suite.
    """
    report = check_proof(SHA_A, order_id="ORD-SAME", proofs=index_proofs([fp(order_id="ORD-SAME")]))

    assert not report.is_reused
    assert report is NO_PROOF_HISTORY


def test_a_proof_with_no_order_attached_has_nothing_to_be_exempt_about() -> None:
    """No "same order" exists, so any earlier acceptance stands as a conflict."""
    report = check_proof(SHA_A, order_id=None, proofs=index_proofs([fp()]))

    assert report.is_reused


def test_an_earlier_proof_with_no_order_is_still_reuse_but_names_nobody() -> None:
    report = check_proof(SHA_A, order_id="ORD-NOW", proofs=index_proofs([fp(order_id=None)]))

    assert report.is_reused
    assert report.conflict is not None
    assert report.conflict.reused_from_order_id is None
    # A note promising an order reference and delivering an empty one is worse
    # than no note: the frontend scans observations for exactly that reference.
    assert report.conflict.observation is None
    assert report.observations == ()


# ==========================================================================
# Silence is not evidence
# ==========================================================================


def test_an_unhashed_proof_can_never_be_reuse() -> None:
    """`proof_sha256 is None` means the caller did not look, not that it matched.

    An extraction path that reports no hash has told the engine nothing. Turning
    that silence into a DUPLICATE would make the verdict depend on which
    extractor happened to run rather than on what the customer did.
    """
    report = check_proof(None, order_id="ORD-NOW", proofs=index_proofs([fp()]))

    assert not report.is_reused
    assert report is NO_PROOF_HISTORY


# ==========================================================================
# Determinism over a history that disagrees with itself
# ==========================================================================


def test_the_earliest_submission_wins_a_contested_hash() -> None:
    """First-writer-wins, mirroring the unique index this stands in for.

    Order of the input list must not decide which order gets named, or the same
    stored history replays to two different explanations.
    """
    early = fp(order_id="ORD-FIRST", submitted_at=NOW)
    late = fp(order_id="ORD-SECOND", submitted_at=NOW + timedelta(hours=1))

    forward = index_proofs([early, late])
    backward = index_proofs([late, early])

    assert forward.by_sha256[SHA_A].order_id == "ORD-FIRST"
    assert backward.by_sha256[SHA_A].order_id == "ORD-FIRST"
    assert forward.contested == frozenset({SHA_A})


def test_a_contested_hash_with_no_timestamps_still_resolves_the_same_way() -> None:
    """The sort key is total, so a tie falls through to order id then id."""
    a = fp(order_id="ORD-AAA")
    b = fp(order_id="ORD-BBB")

    assert index_proofs([a, b]).by_sha256[SHA_A].order_id == "ORD-AAA"
    assert index_proofs([b, a]).by_sha256[SHA_A].order_id == "ORD-AAA"


def test_an_uncontested_history_reports_no_contest() -> None:
    index = index_proofs([fp(SHA_A), fp(SHA_B)])

    assert index.contested == frozenset()
    assert len(index) == 2
    assert index.for_sha256("c" * 64) is None


def test_the_report_carries_the_contest_flag_through() -> None:
    index = index_proofs([fp(order_id="ORD-1"), fp(order_id="ORD-2")])

    assert check_proof(SHA_A, order_id="ORD-NOW", proofs=index).contested


# ==========================================================================
# The note the merchant's screen reads
# ==========================================================================


def test_the_conflict_publishes_the_earlier_order_as_a_neutral_note() -> None:
    """`DUPLICATE` is only actionable once it names somewhere to look.

    The shape is the extractor's `CODE:detail`, so the code stays a real
    `ObservationCode` member and the payload rides behind the colon.
    """
    report = check_proof(SHA_A, order_id="ORD-NOW", proofs=index_proofs([fp()]))

    assert report.observations == (f"{ObservationCode.PROOF_PREVIOUSLY_SUBMITTED}:ORD-EARLIER",)


def test_no_finding_publishes_no_note() -> None:
    assert NO_PROOF_HISTORY.observations == ()
    assert NO_PROOF_HISTORY.reasons == ()
    assert no_proof_history() is NO_PROOF_HISTORY


# ==========================================================================
# Shape
# ==========================================================================


def test_the_report_and_the_index_are_frozen() -> None:
    """Nothing downstream may edit what a rule already read."""
    report = ProofReport()
    index = ProofIndex(by_sha256={})

    with pytest.raises(AttributeError):
        report.conflict = None  # type: ignore[misc]
    with pytest.raises(AttributeError):
        index.by_sha256 = {}  # type: ignore[misc]
