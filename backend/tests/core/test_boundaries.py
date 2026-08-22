"""Exact threshold boundaries — the three points either side of every cut.

Guide 9.4. Every comparison in this layer is inclusive: **`>=` everywhere**, so
a value sitting exactly on a threshold belongs to the *better* side. That is a
convention, not a fact, and a convention nobody tests is a convention that
drifts — a `>` typed instead of a `>=` moves a boundary by one float and no
scenario test notices, because no hand-written scenario ever lands exactly on
0.82.

So each threshold here is probed at three points: the float immediately below
it, the value itself, and the float immediately above. `math.nextafter` gives
the true adjacent double rather than a hand-picked epsilon that might round
away entirely.

**The point of this file is to fail loudly when a threshold changes.** Every
assertion names the side of the boundary it expects and, where the value is
load-bearing, the rule id that must fire. Retuning `tau_accept` after a batch of
labelled scenarios is a legitimate and expected act; doing it without noticing
that a claim underpaid by exactly the tolerance flipped from VERIFIED to review
is not.

Two kinds of test live here and they are deliberately separated:

* **Rule-table boundaries** drive `first_match` with a hand-built `Context`, so
  the candidate's score is exactly the number under test rather than whatever
  the scorers happen to produce. Nothing is approximated.
* **End-to-end boundaries** run the real `decide` over a real feed, so the
  scorers, the aggregate and the rule table are all in the loop.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest

from proofpay.core.compare.amount import (
    AmountEvidence,
    AmountRelation,
    ClaimIntegrity,
    is_material_inflation,
    is_power_of_ten_multiple,
)
from proofpay.core.compare.amount_match import AMOUNT_MATCH, compare_amount_match
from proofpay.core.compare.levels import FieldOutcome
from proofpay.core.compare.name import name_metrics
from proofpay.core.compare.reference import compare_reference, reference_ctx
from proofpay.core.compare.timestamp import (
    MAX_HOUR_ARTIFACT,
    TIMESTAMP,
    compare_timestamp,
    timestamp_ctx,
)
from proofpay.core.decide.engine import (
    COMPARISONS,
    NO_AMOUNT_EVIDENCE,
    SENDER_NAME,
    Context,
    aggregate_score,
    build_context,
    confidence,
    decide,
    first_match,
)
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.duplicates import AllocationConflict, DuplicateReport
from proofpay.core.models import LedgerTxn, Order, PaymentClaim, ScoredCandidate
from proofpay.core.money import Money
from proofpay.core.reasons import ObservationCode, ReasonCode, Status
from proofpay.core.retrieval import (
    KEY_TIME_WINDOW,
    CandidateRanking,
    RetrievalResult,
    retrieve,
)
from proofpay.core.timex import PKT, ClaimedInstant, hour_offset_artifact

MERCHANT = "M-1"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 3, 4, 10, 42, tzinfo=UTC)  # 15:42 PKT
POLICY = DecisionPolicy()
NAME_T = POLICY.name_thresholds()
TS_PARAMS = POLICY.timestamp_params()

#: The cut-points these boundary tests approach from both sides now live in the
#: policy - and are fingerprinted - rather than as module constants beside the
#: ladder they carve. Read back from the params object the comparison is
#: actually evaluated with, so the two can never drift apart.
SIM_TIGHT = TS_PARAMS.sim_tight
SIM_CLOSE = TS_PARAMS.sim_close
SIM_LOOSE = TS_PARAMS.sim_loose
MIN_PARTIAL_LEN = POLICY.ref_min_partial_len

RS_5000 = Money(500_000)


# ==========================================================================
# Helpers: exact floats, and a Context whose score is exactly what we say
# ==========================================================================

def below(value: float) -> float:
    """The largest float strictly below `value`."""
    return math.nextafter(value, -math.inf)


def above(value: float) -> float:
    """The smallest float strictly above `value`."""
    return math.nextafter(value, math.inf)


#: A margin of exactly `tau_margin` is unreachable from the accept band, and
#: that is arithmetic rather than an oversight: two scores in `[0.5, 1.0)`
#: differ by a multiple of 2^-53, while the double nearest 0.10 is an odd
#: multiple of 2^-55. No pair of accept-band scores subtracts to it.
#:
#: So the margin boundary is approached from the other side — the scores are
#: fixed and the *policy* is set to exactly the margin they produce. The
#: default value is pinned separately, below, so retuning it still fails loudly.
def margin_policy(best: float, runner: float, *, tighten: bool = False):
    """A policy whose `tau_margin` is exactly (or one float above) this margin."""
    margin = best - runner
    threshold = above(margin) if tighten else margin
    return replace(POLICY, tau_margin=threshold), margin


def test_the_default_ambiguity_margin_is_what_the_scenarios_were_tuned_to():
    """Pinned so a retune is a visible diff, not a silent behaviour change."""
    assert POLICY.tau_margin == 0.10
    assert POLICY.tau_accept == 0.82
    assert POLICY.tau_reject == 0.45


def txn(
    txn_id: str = "TX1001",
    *,
    amount: Money = RS_5000,
    at: datetime = PAID_AT,
    sender: str | None = "Zulqarnain Haider",
) -> LedgerTxn:
    return LedgerTxn(
        txn_id=txn_id,
        amount=amount,
        occurred_at=at,
        merchant_id=MERCHANT,
        external_id=txn_id,
        sender_name=sender,
    )


def outcome(field: str, code: str, score: float) -> FieldOutcome:
    return FieldOutcome(field=field, level_code=code, label=code, score=score)


def candidate(
    txn_id: str, score: float, *, ref_exact: bool = False
) -> ScoredCandidate:
    """A scored candidate whose aggregate is exactly `score`.

    The field outcomes carry no weight in these tests — `first_match` reads
    `best_score`, never the rows — except for the reference rung, which is
    what the dominance escape hatch keys off.
    """
    return ScoredCandidate(
        txn=txn(txn_id),
        score=score,
        outcomes={
            "reference": outcome(
                "reference",
                "REF_EXACT" if ref_exact else "REF_ELSE",
                1.0 if ref_exact else 0.0,
            )
        },
    )


def context(
    *,
    scores: Sequence[float] = (),
    ref_exact_on: Sequence[str] = (),
    policy: DecisionPolicy = POLICY,
    amount: Any = NO_AMOUNT_EVIDENCE,
    amount_compared: bool = False,
    observations: tuple[str, ...] = (),
    duplicates: DuplicateReport | None = None,
) -> Context:
    """A `Context` with candidate scores set to exactly the numbers given."""
    cands = [
        candidate(f"TX{i:03d}", score, ref_exact=f"TX{i:03d}" in ref_exact_on)
        for i, score in enumerate(scores)
    ]
    ranking = CandidateRanking.of(cands)
    txns = tuple(c.txn for c in ranking.scored)
    return Context(
        claim=PaymentClaim(claim_id="C-1", merchant_id=MERCHANT),
        order=Order(order_id="O-1", expected=RS_5000, merchant_id=MERCHANT),
        policy=policy,
        now=NOW,
        ranking=ranking,
        retrieval=RetrievalResult(
            txns=txns,
            hits=MappingProxyType({t.txn_id: (KEY_TIME_WINDOW,) for t in txns}),
            examined=len(txns),
            truncated=False,
            anchor=NOW,
            anchored_on_now=False,
        ),
        amount=amount,
        amount_compared=amount_compared,
        duplicates=duplicates if duplicates is not None else DuplicateReport(),
        observations=observations,
    )


# ==========================================================================
# tau_accept — the accept band
# ==========================================================================

@pytest.mark.parametrize(
    "score,expect_rule,expect_status",
    [
        (below(POLICY.tau_accept), "R999", Status.NEEDS_REVIEW),
        (POLICY.tau_accept, "R090", Status.VERIFIED),
        (above(POLICY.tau_accept), "R090", Status.VERIFIED),
    ],
    ids=["just-below", "exactly-at", "just-above"],
)
def test_tau_accept_is_inclusive(score, expect_rule, expect_status):
    """A score of exactly `tau_accept` accepts. `>=`, as everywhere else.

    The float immediately below it must not, and must land in review rather
    than in UNMATCHED: it is above `tau_reject`, so the honest answer is "a
    human should look", not "no such payment".
    """
    rule = first_match(context(scores=[score]))
    assert (rule.id, rule.status) == (expect_rule, expect_status)


def test_the_review_band_sits_strictly_between_the_two_thresholds():
    """Everything in [tau_reject, tau_accept) is NEEDS_REVIEW, by construction.

    This is the three-band accept / clerical-review / reject design the policy
    docstring commits to; if the bands ever stop tiling the interval, some
    score has no verdict.
    """
    for score in (POLICY.tau_reject, 0.5, 0.7, below(POLICY.tau_accept)):
        rule = first_match(context(scores=[score]))
        assert rule.status is Status.NEEDS_REVIEW, score
        assert rule.id == "R999", score


def test_a_perfect_score_never_outranks_an_allocation_conflict():
    """Precedence is a boundary too, and this is the money-losing one.

    Safety-negative before safety-positive: a table where a high score can
    pre-empt the duplicate check lets a customer reuse one payment for two
    orders. A score of 1.0 — better than any real claim will ever produce — is
    still not enough.
    """
    conflict = AllocationConflict(txn_id="TX000", allocated_to_order_id="O-ELSEWHERE")
    ctx = context(
        scores=[1.0],
        duplicates=DuplicateReport(conflicts=(conflict,), best_conflict=conflict),
    )
    rule = first_match(ctx)
    assert (rule.id, rule.status) == ("R020", Status.DUPLICATE)


#: More arrived than the order asked for: a commercial outcome, not a fraud
#: signal, so it verifies with the overpayment reported alongside.
OVERPAID = AmountEvidence(
    relation=AmountRelation.OVER,
    integrity=ClaimIntegrity.CONSISTENT,
    shortfall=Money(-100),
    inflation=Money(0),
    within_tolerance=False,
)


@pytest.mark.parametrize(
    "score,expect_rule,expect_status",
    [
        (below(POLICY.tau_accept), "R999", Status.NEEDS_REVIEW),
        (POLICY.tau_accept, "R080", Status.VERIFIED),
    ],
    ids=["just-below", "exactly-at"],
)
def test_an_overpayment_verifies_from_exactly_tau_accept(
    score, expect_rule, expect_status
):
    """`R080` sits above the plain `R090`: specific before general.

    Both rules verify, so the status alone would not catch a reordering — the
    rule id is what says the merchant is told *why*, and it shares the same
    inclusive `tau_accept` boundary as every other acceptance.
    """
    ctx = context(scores=[score], amount=OVERPAID, amount_compared=True)
    rule = first_match(ctx)
    assert (rule.id, rule.status) == (expect_rule, expect_status)
    if expect_status is Status.VERIFIED:
        assert ReasonCode.AMOUNT_OVERPAID in rule.reasons


# ==========================================================================
# tau_reject — the reject band
# ==========================================================================

@pytest.mark.parametrize(
    "score,expect_rule,expect_status",
    [
        (below(POLICY.tau_reject), "R060", Status.UNMATCHED),
        (POLICY.tau_reject, "R999", Status.NEEDS_REVIEW),
        (above(POLICY.tau_reject), "R999", Status.NEEDS_REVIEW),
    ],
    ids=["just-below", "exactly-at", "just-above"],
)
def test_tau_reject_is_inclusive(score, expect_rule, expect_status):
    """A score of exactly `tau_reject` is *not* rejected.

    `R060` fires on `best_score < tau_reject`, so the boundary value survives
    into the review band. The asymmetry is deliberate and matches the `>=`
    convention: the threshold value always belongs to the better side.
    """
    rule = first_match(context(scores=[score]))
    assert (rule.id, rule.status) == (expect_rule, expect_status)


def test_amounts_are_compared_exactly_at_tau_reject_and_not_below():
    """`tau_reject` also gates whether the amounts are compared at all.

    Below it, the winner is not a credible candidate, and comparing amounts
    anyway manufactures an accusation out of a coincidence — any unrelated
    smaller transaction in the window would make the claim look "materially
    inflated". The policy is tuned to the score the engine actually produces
    for this scenario so the boundary is hit exactly, not approached.
    """
    feed = [txn()]
    # No printed transaction id, so the aggregate lands strictly below 1.0 and
    # `above(score)` is still a legal threshold.
    the_claim = PaymentClaim(
        claim_id="C-1",
        merchant_id=MERCHANT,
        amount=RS_5000,
        sender_name="Zulqarnain Haider",
        occurred_at=ClaimedInstant.from_local(
            datetime(2026, 3, 4, 15, 42), tz=PKT, granularity_s=60
        ),
    )
    the_order = Order(order_id="O-1", expected=RS_5000, merchant_id=MERCHANT)

    measured = build_context(
        the_claim, the_order, feed, (), now=NOW, policy=POLICY
    ).ranking.best
    assert measured is not None
    score = measured.score
    assert score < 1.0

    at = replace(POLICY, tau_reject=score, tau_accept=1.0)
    just_above = replace(POLICY, tau_reject=above(score), tau_accept=1.0)

    assert build_context(
        the_claim, the_order, feed, (), now=NOW, policy=at
    ).amount_compared is True
    assert build_context(
        the_claim, the_order, feed, (), now=NOW, policy=just_above
    ).amount_compared is False


# ==========================================================================
# tau_margin — the ambiguity band
# ==========================================================================

def test_a_margin_of_exactly_tau_margin_is_not_ambiguous():
    """`R050` fires on `margin < tau_margin`, so the boundary value verifies."""
    policy, margin = margin_policy(0.92, 0.82)
    ctx = context(scores=[0.92, 0.82], policy=policy)

    assert ctx.ranking.margin == policy.tau_margin == margin
    rule = first_match(ctx)
    assert (rule.id, rule.status) == ("R090", Status.VERIFIED)


def test_a_margin_one_float_under_tau_margin_is_ambiguous():
    """One float of separation short and the two candidates are interchangeable.

    Guessing which of two equally good payments to allocate is how the wrong
    transaction gets consumed and the *other* order surfaces an incoherent
    DUPLICATE days later, so this side of the boundary must refuse to guess.
    """
    policy, margin = margin_policy(0.92, 0.82, tighten=True)
    ctx = context(scores=[0.92, 0.82], policy=policy)

    assert ctx.ranking.margin == margin < policy.tau_margin
    assert policy.tau_margin == above(margin)
    rule = first_match(ctx)
    assert (rule.id, rule.status) == ("R050", Status.NEEDS_REVIEW)
    assert ReasonCode.AMBIGUOUS_CANDIDATES in rule.reasons


def test_a_unique_exact_reference_wins_regardless_of_margin():
    """The dominance escape hatch, at the same boundary.

    The margin rule protects against *interchangeable* candidates. A unique
    printed transaction id means they are not interchangeable, so a zero
    margin must not block the match.
    """
    ctx = context(scores=[POLICY.tau_accept, POLICY.tau_accept], ref_exact_on=["TX000"])
    assert ctx.ranking.margin == 0.0
    assert ctx.dominant is True
    rule = first_match(ctx)
    assert (rule.id, rule.status) == ("R090", Status.VERIFIED)


def test_a_lone_candidate_has_the_maximum_margin():
    """Nothing to be confused with is not the same as being confusable.

    A single candidate has no runner-up, so `margin` is 1.0 and `R050` can
    never veto an unambiguous match — the degenerate case a naive
    `best - second` would divide by zero on.
    """
    ctx = context(scores=[POLICY.tau_accept])
    assert ctx.ranking.margin == 1.0
    assert first_match(ctx).id == "R090"


# ==========================================================================
# Materiality of an inflated claim
# ==========================================================================

#: Both knobs are cleared at exactly this point: 5 000 paisa is the floor, and
#: 5 000 paisa is exactly 1% of the 500 000 paisa that arrived.
MATERIAL_LEDGER = RS_5000
MATERIAL_INFLATION = POLICY.inflation_material_minor  # 5_000 paisa = Rs. 50


@pytest.mark.parametrize(
    "inflation_minor,ledger_minor,expected",
    [
        (MATERIAL_INFLATION - 1, MATERIAL_LEDGER.minor, False),
        (MATERIAL_INFLATION, MATERIAL_LEDGER.minor, True),
        (MATERIAL_INFLATION + 1, MATERIAL_LEDGER.minor, True),
    ],
    ids=["one-paisa-under-the-floor", "exactly-the-floor", "one-paisa-over"],
)
def test_the_absolute_materiality_floor_is_inclusive(
    inflation_minor, ledger_minor, expected
):
    """An over-claim of exactly `inflation_material_minor` is material.

    Below it the difference is OCR noise; a system that accuses someone of
    fraud over one paisa less than the floor has the wrong floor.
    """
    assert (
        is_material_inflation(inflation_minor, ledger_minor, POLICY) is expected
    )


@pytest.mark.parametrize(
    "ledger_minor,expected",
    [
        (MATERIAL_LEDGER.minor, True),          # 1% == 5_000, cleared exactly
        (MATERIAL_LEDGER.minor + 100, False),   # 1% == 5_001, floor no longer enough
    ],
    ids=["pct-cleared-exactly", "pct-one-paisa-short"],
)
def test_the_proportional_materiality_test_is_inclusive(ledger_minor, expected):
    """Both knobs must be cleared, so the proportion has its own boundary.

    Raising the amount that actually arrived raises the 1% bar above a
    fixed-size over-claim, and the accusation stops — which is the whole point
    of scaling materiality with the size of the payment.
    """
    assert is_material_inflation(MATERIAL_INFLATION, ledger_minor, POLICY) is expected


def test_deflation_is_never_material_at_any_size():
    """OCR drops digits; attackers do not under-claim.

    The sign is the fraud signal, so the magnitude test must never be reached
    for a claim smaller than the money that arrived.
    """
    assert is_material_inflation(-10**9, MATERIAL_LEDGER.minor, POLICY) is False
    assert is_material_inflation(0, MATERIAL_LEDGER.minor, POLICY) is False


def _inflated_run(claim_amount: Money):
    the_claim = PaymentClaim(
        claim_id="C-1",
        merchant_id=MERCHANT,
        amount=claim_amount,
        reference_id="TX1001",
        sender_name="Zulqarnain Haider",
        occurred_at=ClaimedInstant.from_local(
            datetime(2026, 3, 4, 15, 42), tz=PKT, granularity_s=60
        ),
    )
    return decide(
        the_claim,
        Order(order_id="O-1", expected=MATERIAL_LEDGER, merchant_id=MERCHANT),
        [txn(amount=MATERIAL_LEDGER)],
        (),
        now=NOW,
        policy=POLICY,
    )


def test_an_over_claim_of_exactly_the_material_amount_is_suspicious():
    """End to end, through the real scorers: the accusation is made here."""
    decision = _inflated_run(Money(MATERIAL_LEDGER.minor + MATERIAL_INFLATION))
    assert (decision.status, decision.fired_rule_id) == (Status.SUSPICIOUS, "R030")
    assert ReasonCode.CLAIM_INFLATED in decision.reasons


def test_one_paisa_less_is_reported_but_not_accused():
    """The finding still appears; only the verdict changes.

    `CLAIM_INFLATED` follows from the arithmetic and is reported either way —
    the merchant can see the discrepancy — but below the materiality floor the
    engine declines to call it suspicious. Losing the reason code at the same
    time as the status would hide the evidence along with the accusation.
    """
    decision = _inflated_run(Money(MATERIAL_LEDGER.minor + MATERIAL_INFLATION - 1))
    assert decision.status is not Status.SUSPICIOUS
    assert decision.fired_rule_id != "R030"
    assert ReasonCode.CLAIM_INFLATED in decision.reasons


def test_a_claim_equal_to_the_ledger_is_not_a_power_of_ten_multiple():
    """The scaled-amount check has a boundary too: equality is not a factor.

    `claim_minor <= ledger_minor` is the guard; without it every exact match
    would divide to a quotient of 1 and be flagged as a hand-typed digit.
    """
    assert is_power_of_ten_multiple(500_000, 500_000) is False
    assert is_power_of_ten_multiple(500_001, 500_000) is False
    assert is_power_of_ten_multiple(5_000_000, 500_000) is True


# ==========================================================================
# Underpayment tolerance
# ==========================================================================

TOLERANT = replace(POLICY, amount_tolerance_minor=100)  # Rs. 1


def _underpaid_run(expected: Money, policy: DecisionPolicy = TOLERANT):
    the_claim = PaymentClaim(
        claim_id="C-1",
        merchant_id=MERCHANT,
        amount=RS_5000,
        reference_id="TX1001",
        sender_name="Zulqarnain Haider",
        occurred_at=ClaimedInstant.from_local(
            datetime(2026, 3, 4, 15, 42), tz=PKT, granularity_s=60
        ),
    )
    return decide(
        the_claim,
        Order(order_id="O-1", expected=expected, merchant_id=MERCHANT),
        [txn(amount=RS_5000)],
        (),
        now=NOW,
        policy=policy,
    )


def test_a_shortfall_of_exactly_the_tolerance_still_verifies():
    """`within_tolerance` is `-t <= shortfall <= t` — inclusive at both ends."""
    decision = _underpaid_run(Money(RS_5000.minor + TOLERANT.amount_tolerance_minor))
    assert (decision.status, decision.fired_rule_id) == (Status.VERIFIED, "R090")
    assert ReasonCode.AMOUNT_UNDERPAID in decision.reasons  # reported, not blocking


def test_one_paisa_more_of_shortfall_goes_to_review():
    decision = _underpaid_run(
        Money(RS_5000.minor + TOLERANT.amount_tolerance_minor + 1)
    )
    assert (decision.status, decision.fired_rule_id) == (Status.NEEDS_REVIEW, "R070")


def test_the_default_policy_permits_no_shortfall_at_all():
    """The MVP position: exact equality in integer paisa.

    Pinned explicitly so that introducing a tolerance is a visible, deliberate
    act rather than something that arrives with a merged branch.
    """
    assert POLICY.amount_tolerance_minor == 0
    decision = _underpaid_run(Money(RS_5000.minor + 1), policy=POLICY)
    assert (decision.status, decision.fired_rule_id) == (Status.NEEDS_REVIEW, "R070")


# ==========================================================================
# Tamper signal limit
# ==========================================================================

TAMPER = (
    str(ObservationCode.IMAGE_EXIF_MISSING),
    str(ObservationCode.IMAGE_EDITOR_SIGNATURE),
)


def test_exactly_the_tolerated_number_of_image_signals_is_not_suspicious():
    """`R040` fires on `tamper_count > limit` — strictly greater, on purpose.

    One signal alone is routinely an honestly re-saved screenshot, so the limit
    is the number *tolerated*, not the number that triggers.
    """
    assert POLICY.tamper_signal_limit == 1
    ctx = context(scores=[0.5], observations=TAMPER[:1])
    assert ctx.tamper_count == 1
    assert first_match(ctx).id == "R999"


def test_one_signal_past_the_limit_with_a_weak_match_is_suspicious():
    ctx = context(scores=[0.5], observations=TAMPER)
    assert ctx.tamper_count == 2
    rule = first_match(ctx)
    assert (rule.id, rule.status) == ("R040", Status.SUSPICIOUS)


def test_image_signals_never_override_a_strong_field_match():
    """`R040` also requires `best_score < tau_accept`, and that is inclusive.

    A candidate sitting exactly on `tau_accept` is accepted, so tamper signals
    on a receipt that matches the ledger on every field are recorded as
    observations and do not become a verdict.
    """
    ctx = context(scores=[POLICY.tau_accept], observations=TAMPER)
    assert ctx.tamper_count > POLICY.tamper_signal_limit
    assert first_match(ctx).id == "R090"


def test_parsing_notes_never_count_toward_an_accusation():
    """Only the four `IMAGE_*` codes are tamper signals.

    An ambiguous thousands separator says something about our reader, not
    about the image, and must never accumulate toward calling someone a
    fraudster.
    """
    ctx = context(
        scores=[0.5],
        observations=(
            str(ObservationCode.AMOUNT_SEPARATOR_AMBIGUOUS),
            str(ObservationCode.AMOUNT_NON_ASCII_DIGITS),
            str(ObservationCode.TIME_TZ_ASSUMED),
            str(ObservationCode.NAME_MASKED),
        ),
    )
    assert ctx.tamper_count == 0
    assert first_match(ctx).id == "R999"


# ==========================================================================
# Whole-hour timezone artefacts
# ==========================================================================

@pytest.mark.parametrize(
    "delta_s,expected",
    [
        (3600.0 - POLICY.hour_artifact_tol_s, 1),
        (3600.0, 1),
        (3600.0 + POLICY.hour_artifact_tol_s, 1),
        (3600.0 + POLICY.hour_artifact_tol_s + 0.001, None),
        (3600.0 - POLICY.hour_artifact_tol_s - 0.001, None),
    ],
    ids=["low-edge", "dead-on", "high-edge", "just-past-high", "just-past-low"],
)
def test_the_hour_artifact_tolerance_is_inclusive(delta_s, expected):
    """A difference exactly `tol_s` from a whole hour still reads as an artefact.

    Inside the band it is a timezone/offset story worth reporting; outside it,
    it is simply a different transaction and must not be dressed up as one.
    """
    assert hour_offset_artifact(delta_s, POLICY.hour_artifact_tol_s) == expected


def test_zero_is_never_an_hour_artifact():
    """Same time is not "a whole number of hours out"; `hours != 0` guards it."""
    assert hour_offset_artifact(0.0, POLICY.hour_artifact_tol_s) is None
    assert hour_offset_artifact(30.0, POLICY.hour_artifact_tol_s) is None


@pytest.mark.parametrize(
    "hours,expect_level",
    [(MAX_HOUR_ARTIFACT, "TS_HOUR_ART"), (MAX_HOUR_ARTIFACT + 1, "TS_ELSE")],
    ids=["max-real-utc-offset", "one-hour-beyond"],
)
def test_the_hour_artifact_stops_at_the_widest_real_utc_offset(hours, expect_level):
    """14 hours is a timezone; 15 is a different transaction.

    24h is a multiple of 3600 too, and without this ceiling a payment a day
    away would be explained away as a mis-set clock.
    """
    claimed = ClaimedInstant(resolved_utc=PAID_AT, granularity_s=60)
    result = compare_timestamp(claimed, PAID_AT - timedelta(hours=hours), TS_PARAMS)
    assert result.level_code == expect_level


# ==========================================================================
# Level-ladder boundaries: the `>=` convention, rung by rung
# ==========================================================================

def _name_ctx(claim_raw: str, truth_raw: str, **overrides: Any) -> dict[str, Any]:
    """A real metric bundle with one metric pinned to an exact value.

    Overriding a computed metric rather than searching for two names that
    happen to score exactly 0.92 is what makes the boundary exact; every other
    key stays as the real pipeline produced it, so the predicate is evaluated
    against a coherent bundle.
    """
    ctx = dict(name_metrics(claim_raw, truth_raw, idf={}, thresholds=NAME_T))
    ctx.update(overrides)
    return ctx


def _evaluate_name(ctx: Mapping[str, Any]) -> FieldOutcome:
    return SENDER_NAME.evaluate(ctx["claim_tokens"], ctx["truth_tokens"], ctx)


@pytest.mark.parametrize(
    "token_score,expect",
    [
        (below(NAME_T.strong), "NAME_PARTIAL"),
        (NAME_T.strong, "NAME_STRONG"),
        (above(NAME_T.strong), "NAME_STRONG"),
    ],
    ids=["just-below", "exactly-at", "just-above"],
)
def test_the_name_strong_threshold_is_inclusive(token_score, expect):
    """Exactly `name_strong_t` is a spelling difference, not a partial match."""
    ctx = _name_ctx(
        "Zulqarnain Haider",
        "Zulqarnian Haider",
        token_score=token_score,
        idf_weighted_score=0.9,
    )
    assert _evaluate_name(ctx).level_code == expect


@pytest.mark.parametrize(
    "idf_score,expect",
    [
        (below(NAME_T.common_idf), "NAME_COMMON_ONLY"),
        (NAME_T.common_idf, "NAME_EXACT"),
        (above(NAME_T.common_idf), "NAME_EXACT"),
    ],
    ids=["just-below", "exactly-at", "just-above"],
)
def test_the_common_name_threshold_is_inclusive(idf_score, expect):
    """Exactly `name_common_idf_t` of evidence is still evidence.

    Below it, an exact string match on two different customers both called
    `Muhammad Ali` drops from 1.00 to 0.20 — the single most likely way this
    engine would match the wrong transaction, and the reason the rung exists.
    """
    ctx = _name_ctx("Muhammad Ali", "Muhammad Ali", idf_weighted_score=idf_score)
    assert _evaluate_name(ctx).level_code == expect


@pytest.mark.parametrize(
    "token_score,expect",
    [
        (below(NAME_T.initials), "NAME_PARTIAL"),
        (NAME_T.initials, "NAME_INITIALS"),
    ],
    ids=["just-below", "exactly-at"],
)
def test_the_initials_threshold_is_inclusive(token_score, expect):
    ctx = _name_ctx(
        "M. Ali", "Muhammad Ali", token_score=token_score, idf_weighted_score=0.9
    )
    assert ctx["initials_compatible"] is True
    assert _evaluate_name(ctx).level_code == expect


@pytest.mark.parametrize(
    "sim,expect",
    [
        (above(SIM_TIGHT), "TS_TIGHT"),
        (SIM_TIGHT, "TS_TIGHT"),
        (below(SIM_TIGHT), "TS_CLOSE"),
        (SIM_CLOSE, "TS_CLOSE"),
        (below(SIM_CLOSE), "TS_LOOSE"),
        (SIM_LOOSE, "TS_LOOSE"),
        (below(SIM_LOOSE), "TS_ELSE"),
    ],
    ids=[
        "above-tight",
        "exactly-tight",
        "below-tight",
        "exactly-close",
        "below-close",
        "exactly-loose",
        "below-loose",
    ],
)
def test_every_timestamp_rung_boundary_is_inclusive(sim, expect):
    """All three decay cut-points at once, each probed on its own edge.

    The ladder is walked top-down, so getting one rung's comparison wrong
    silently reassigns a whole band of similarities to the rung below it.
    """
    ctx = dict(timestamp_ctx(ClaimedInstant(resolved_utc=PAID_AT), PAID_AT, TS_PARAMS))
    ctx.update(sim=sim, hour_offset=None)
    assert TIMESTAMP.evaluate(None, None, ctx).level_code == expect


def test_an_imprecise_reading_can_never_reach_a_precise_rung():
    """A date-only receipt tops out at `TS_DATE_ONLY`, however close it lands.

    `precise` gates the top two rungs, so this is a structural boundary rather
    than a numeric one: perfect similarity plus an imprecise reading is
    `TS_DATE_ONLY`, not `TS_TIGHT`.
    """
    ctx = dict(timestamp_ctx(ClaimedInstant(resolved_utc=PAID_AT), PAID_AT, TS_PARAMS))
    ctx.update(sim=1.0, precise=False, hour_offset=None)
    assert TIMESTAMP.evaluate(None, None, ctx).level_code == "TS_DATE_ONLY"


@pytest.mark.parametrize(
    "left,right,expect",
    [
        ("ABCDE123", "VWXYZ123", "REF_ELSE"),      # shared tail of 3
        ("ABCD1234", "WXYZ1234", "REF_PARTIAL"),   # shared tail of exactly 4
    ],
    ids=["one-short-of-the-minimum", "exactly-the-minimum"],
)
def test_the_reference_partial_length_is_inclusive(left, right, expect):
    """A shared tail of exactly `MIN_PARTIAL_LEN` is evidence; one less is noise.

    Four characters is roughly where a coincidental collision stops being
    likely across a merchant's day, and scoring noise as a partial match is
    how a matcher starts matching the wrong transaction.
    """
    assert MIN_PARTIAL_LEN == 4
    ctx = reference_ctx(left, right, min_partial_len=MIN_PARTIAL_LEN)
    assert ctx["common_suffix_len"] == (3 if expect == "REF_ELSE" else 4)
    assert compare_reference(left, right, min_partial_len=MIN_PARTIAL_LEN).level_code == expect


def test_two_absent_references_are_missing_not_equal():
    """The boundary that matters most on this ladder is the guard, not a number.

    Both sides normalise to `""`, and an unguarded equality test would report
    `REF_EXACT` — verifying a payment on a receipt that printed no id at all.
    """
    assert compare_reference(None, None, min_partial_len=MIN_PARTIAL_LEN).level_code == "REF_MISSING"
    assert compare_reference("", "   ", min_partial_len=MIN_PARTIAL_LEN).level_code == "REF_MISSING"
    assert compare_reference("TID:", "TID:", min_partial_len=MIN_PARTIAL_LEN).level_code == "REF_MISSING"


@pytest.mark.parametrize(
    "diff,expect",
    [
        (0, "AMT_EXACT"),
        (100, "AMT_TOLERANCE"),
        (-100, "AMT_TOLERANCE"),
        (101, "AMT_ELSE"),
        (-101, "AMT_ELSE"),
    ],
    ids=["equal", "at-plus-tolerance", "at-minus-tolerance", "over", "under"],
)
def test_the_amount_tolerance_rung_is_inclusive_in_both_directions(diff, expect):
    """`-t <= diff <= t`, symmetric, and reachable only when policy allows it.

    The rung is unreachable under the default zero tolerance, which is the MVP
    position; it is tested here so that turning a tolerance on lands on a rung
    that says so out loud rather than quietly widening `AMT_EXACT`.
    """
    outcome = compare_amount_match(
        Money(RS_5000.minor + diff), RS_5000, tolerance_minor=100
    )
    assert outcome.level_code == expect


def test_the_default_policy_makes_the_tolerance_rung_unreachable():
    assert POLICY.amount_tolerance_minor == 0
    assert (
        compare_amount_match(Money(RS_5000.minor + 1), RS_5000, tolerance_minor=0).level_code
        == "AMT_ELSE"
    )
    assert "AMT_TOLERANCE" in AMOUNT_MATCH.codes  # still a declared, testable rung


# ==========================================================================
# Retrieval bounds
# ==========================================================================

TIME_ONLY_CLAIM = PaymentClaim(
    claim_id="C-1",
    merchant_id=MERCHANT,
    occurred_at=ClaimedInstant(resolved_utc=PAID_AT, granularity_s=60),
)


@pytest.mark.parametrize(
    "offset_s,retrieved",
    [
        (POLICY.time_window_s, True),
        (POLICY.time_window_s + 1, False),
        (-POLICY.time_window_s, True),
        (-POLICY.time_window_s - 1, False),
    ],
    ids=["at-the-edge", "one-second-past", "at-the-edge-before", "one-second-before"],
)
def test_the_retrieval_window_is_inclusive_on_both_sides(offset_s, retrieved):
    """A transaction exactly `time_window_s` from the anchor is a candidate.

    The claim carries nothing but a timestamp, so the time key is the only one
    that can retrieve anything and the boundary is tested in isolation.
    """
    feed = [txn("TX-EDGE", at=PAID_AT + timedelta(seconds=offset_s))]
    result = retrieve(TIME_ONLY_CLAIM, feed, POLICY, now=NOW)
    assert ("TX-EDGE" in result.txn_ids()) is retrieved


def test_the_candidate_cap_is_exact():
    """`max_candidates` transactions are not a truncation; one more is.

    `truncated` is what tells a later stage that the candidate set was cut,
    so an off-by-one here silently hides the fact that a true match may have
    been dropped.
    """
    policy = replace(POLICY, max_candidates=3)
    feed = [txn(f"TX{i}", at=PAID_AT + timedelta(seconds=i)) for i in range(3)]

    exact = retrieve(TIME_ONLY_CLAIM, feed, policy, now=NOW)
    assert len(exact.txns) == 3
    assert exact.truncated is False

    feed.append(txn("TX3", at=PAID_AT + timedelta(seconds=3)))
    over = retrieve(TIME_ONLY_CLAIM, feed, policy, now=NOW)
    assert len(over.txns) == 3
    assert over.truncated is True


# ==========================================================================
# The aggregate, and what an unreadable field costs
# ==========================================================================

def _perfect_outcomes() -> dict[str, FieldOutcome]:
    return {
        c.field: outcome(c.field, f"{c.codes[0]}", 1.0) for c in COMPARISONS
    }


def test_a_perfect_match_aggregates_to_exactly_one():
    assert aggregate_score(_perfect_outcomes(), POLICY) == 1.0


def test_an_otherwise_perfect_claim_survives_one_unreadable_field():
    """A receipt that never printed a transaction id must still be verifiable.

    The exact arithmetic, spelled out rather than asserted as a magic constant:
    the missing field leaves the numerator but keeps
    `missing_evidence_penalty` of its weight in the denominator. If that value
    is ever retuned, this test says immediately whether the no-TID receipt
    still clears `tau_accept`.
    """
    outcomes = _perfect_outcomes()
    outcomes["reference"] = outcome("reference", "REF_MISSING", 0.0)

    # Weights come from the policy, not from the `Comparison` objects: a field
    # weight steers every aggregate it feeds, so it is fingerprinted with the
    # rest of the tunables rather than declared beside the ladder.
    weights = POLICY.field_weights()
    present = sum(w for f, w in weights.items() if f != "reference")
    expected = round(present / (present + POLICY.missing_evidence_penalty * weights["reference"]), 6)

    score = aggregate_score(outcomes, POLICY)
    assert score == expected
    assert score >= POLICY.tau_accept, "a receipt with no printed TID became unverifiable"


def test_a_claim_carrying_only_a_name_cannot_reach_acceptance():
    """The other half of the same knob, and the more important half.

    Excluding unread fields entirely would make a claim with nothing but a
    legible name score 1.0 — precisely the screenshot-only verification the
    invariant forbids.
    """
    outcomes = {
        c.field: outcome(c.field, f"{c.codes[0].split('_')[0]}_MISSING", 0.0)
        for c in COMPARISONS
    }
    outcomes["sender_name"] = outcome("sender_name", "NAME_EXACT", 1.0)

    score = aggregate_score(outcomes, POLICY)
    assert score < POLICY.tau_accept
    assert first_match(context(scores=[score])).status is not Status.VERIFIED


def test_an_entirely_unreadable_claim_scores_zero_rather_than_dividing_by_zero():
    """Every field missing is the degenerate case of the aggregate's denominator."""
    outcomes = {
        c.field: outcome(c.field, f"{c.codes[0].split('_')[0]}_MISSING", 0.0)
        for c in COMPARISONS
    }
    assert aggregate_score(outcomes, POLICY, comparisons=()) == 0.0
    assert aggregate_score({}, POLICY) == 0.0


# ==========================================================================
# Confidence
# ==========================================================================

def test_the_margin_term_of_confidence_saturates_exactly_at_tau_margin():
    """`min(1.0, margin / tau_margin)` — one `tau_margin` of separation is all
    the separability the formula ever pays for, and the clip is inclusive.

    The best score is deliberately mid-band rather than 1.0: with a perfect
    score and full coverage the formula already sums to 1.0 and the rounding
    to three decimals would hide the term entirely.
    """
    evidence = tuple(_perfect_outcomes().values())
    policy, margin = margin_policy(1.0, 0.9)

    def ranking_with(gap: float) -> CandidateRanking:
        return CandidateRanking.of([candidate("TX1", 0.5), candidate("TX2", 0.5 - gap)])

    at = ranking_with(margin)
    assert at.margin == policy.tau_margin

    wider = ranking_with(2 * margin)
    narrower = ranking_with(margin / 2)
    assert wider.margin > policy.tau_margin > narrower.margin

    # 0.5 * 0.5 + 0.3 * 1.0 + 0.2 * 1.0
    assert confidence(at, evidence, policy) == 0.75
    assert confidence(wider, evidence, policy) == 0.75      # clipped, not rewarded
    assert confidence(narrower, evidence, policy) == 0.6    # 0.3 * 0.5


def test_an_empty_ranking_is_credited_with_a_full_separability_term():
    """A documented quirk, pinned so that changing it is a deliberate act.

    `CandidateRanking.margin` returns 1.0 when there are fewer than two
    candidates — written for the *lone* candidate, which genuinely has nothing
    to be confused with, but it also covers the empty ranking. So an
    `R010` UNMATCHED decision reports confidence 0.3: nothing from the score
    term, nothing from coverage, and the entire 0.3 from a separability term
    measuring a field of one runner against no runners.

    That number is shown to a merchant beside "no matching transaction". It is
    not wrong so much as unearned, and if it is ever reworked this test is
    where the intent should be restated.
    """
    value = confidence(CandidateRanking.of([]), (), POLICY)
    assert value == 0.3
    assert 0.0 <= value <= 1.0


# ==========================================================================
# Policy validation boundaries
# ==========================================================================

def test_the_two_acceptance_thresholds_may_touch_but_not_cross():
    """A degenerate but coherent policy (no review band) is allowed; an
    incoherent one is rejected at construction rather than at demo time."""
    touching = replace(POLICY, tau_reject=POLICY.tau_accept)
    assert touching.tau_accept == touching.tau_reject

    with pytest.raises(ValueError, match="tau_accept must be >= tau_reject"):
        replace(POLICY, tau_reject=above(POLICY.tau_accept))


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_the_unit_interval_is_closed_for_every_fractional_threshold(value):
    assert replace(POLICY, tau_margin=value).tau_margin == value
    assert replace(POLICY, missing_evidence_penalty=value).missing_evidence_penalty == value


@pytest.mark.parametrize("value", [below(0.0), above(1.0)])
def test_a_threshold_one_float_outside_the_unit_interval_is_rejected(value):
    with pytest.raises(ValueError, match="must be within 0.0..1.0"):
        replace(POLICY, tau_margin=value)


def test_the_candidate_cap_must_admit_at_least_one_candidate():
    """Zero candidates is not a policy, it is a switched-off engine."""
    with pytest.raises(ValueError, match="max_candidates must be >= 1"):
        replace(POLICY, max_candidates=0)
    assert replace(POLICY, max_candidates=1).max_candidates == 1


def test_a_zero_width_time_window_is_legal_and_still_retrieves_the_instant():
    """The inclusive comparison means a zero window is a point, not an empty set."""
    policy = replace(POLICY, time_window_s=0)
    feed = [txn("TX-NOW", at=PAID_AT), txn("TX-LATER", at=PAID_AT + timedelta(seconds=1))]
    assert retrieve(TIME_ONLY_CLAIM, feed, policy, now=NOW).txn_ids() == ("TX-NOW",)
