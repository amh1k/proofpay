"""Decision-engine tests: one scenario per rule, plus the invariants.

The workhorse is `SCENARIOS`, a parametrised decision table (guide 9.1). Each
row is a hand-built situation with the rule it must fire and the status that
rule must produce. Asserting the *rule id* rather than only the status is the
point: two rules can agree on `NEEDS_REVIEW` for completely different reasons,
and a table that silently starts firing a different rule is a regression even
when the status is unchanged.

`test_every_rule_is_covered` closes the loop — a rule added to the table
without a scenario fails the suite.
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from proofpay.core.compare.amount import AmountRelation, ClaimIntegrity
from proofpay.core.compare.levels import FieldOutcome
from proofpay.core.decide.engine import (
    COMPARISONS,
    ENGINE_VERSION,
    NO_AMOUNT_EVIDENCE,
    SENDER_NAME,
    TAMPER_OBSERVATION_CODES,
    _enforce_invariants,
    aggregate_score,
    build_context,
    confidence,
    decide,
    first_match,
    score_candidate,
    scoring_idf,
)
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.decide.rules_v1 import RULES, RULESET_VERSION, Rule, total_else
from proofpay.core.models import (
    Allocation,
    Decision,
    LedgerTxn,
    Order,
    PaymentClaim,
    ScoredCandidate,
)
from proofpay.core.money import Money
from proofpay.core.reasons import (
    PARTIALLY_TRUSTED_SOURCES,
    TRUSTED_LEDGER_SOURCES,
    ObservationCode,
    ReasonCode,
    Risk,
    Source,
    Status,
)
from proofpay.core.retrieval import CandidateRanking, TxnIndex
from proofpay.core.timex import PKT, ClaimedInstant

# --------------------------------------------------------------------------
# Fixtures: one merchant, one afternoon
# --------------------------------------------------------------------------

MERCHANT = "M-1"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 3, 4, 10, 42, tzinfo=UTC)   # 15:42 PKT
RS_2000 = Money(200_000)

#: Distinctive on purpose. `Muhammad Ali` is pinned to the IDF floor by design,
#: so a scenario built on it would exercise the common-name path, not the rule.
SENDER = "Zulqarnain Haider"
OTHER_SENDER = "Farhat Kanwal"

POLICY = DecisionPolicy()


def txn(
    txn_id: str = "TX1001",
    *,
    amount: Money = RS_2000,
    at: datetime = PAID_AT,
    sender: str | None = SENDER,
    ref: str | None = None,
    source: Source = Source.MERCHANT_LEDGER,
) -> LedgerTxn:
    return LedgerTxn(
        txn_id=txn_id,
        amount=amount,
        occurred_at=at,
        merchant_id=MERCHANT,
        external_id=ref if ref is not None else txn_id,
        sender_name=sender,
        source=source,
    )


def at_pkt(local: datetime, granularity_s: int = 60) -> ClaimedInstant:
    return ClaimedInstant.from_local(local, tz=PKT, granularity_s=granularity_s)


CLAIMED_AT = at_pkt(datetime(2026, 3, 4, 15, 42))


def claim(
    claim_id: str = "C-1",
    *,
    amount: Money | None = RS_2000,
    ref: str | None = "TX1001",
    sender: str | None = SENDER,
    when: ClaimedInstant | None = CLAIMED_AT,
    notes: tuple[str, ...] = (),
) -> PaymentClaim:
    return PaymentClaim(
        claim_id=claim_id,
        merchant_id=MERCHANT,
        amount=amount,
        reference_id=ref,
        sender_name=sender,
        occurred_at=when,
        notes=notes,
    )


def order(expected: Money | None = RS_2000, order_id: str = "O-1") -> Order:
    return Order(order_id=order_id, expected=expected, merchant_id=MERCHANT)


def run(
    the_claim: PaymentClaim,
    the_order: Order | None,
    feed: list[LedgerTxn],
    allocations: tuple[Allocation, ...] = (),
    *,
    observations: tuple[str, ...] = (),
    policy: DecisionPolicy = POLICY,
) -> Decision:
    return decide(
        the_claim,
        the_order,
        feed,
        allocations,
        now=NOW,
        policy=policy,
        observations=observations,
    )


def busy_feed() -> list[LedgerTxn]:
    """A merchant's afternoon: two identical Rs. 2,000 payments from the same
    customer, among the rest of the day's traffic.

    The other traffic is not decoration. Name IDF is measured on the
    merchant's own feed, so a two-row feed where both rows share one sender
    correctly concludes that the sender name carries no information at all —
    true, and useless for exercising ambiguity. Four other customers make the
    name informative again, which is what a real feed looks like.
    """
    return [
        txn("TX-A"),
        txn("TX-B"),
        txn("TX-C", amount=Money(125_000), at=PAID_AT - timedelta(hours=1), sender="Nadia Perveen"),
        txn("TX-D", amount=Money(340_000), at=PAID_AT - timedelta(hours=2), sender="Imran Baig"),
        txn("TX-E", amount=Money(90_000), at=PAID_AT - timedelta(hours=3), sender="Rukhsana Tabassum"),
        txn("TX-F", amount=Money(410_000), at=PAID_AT - timedelta(hours=4), sender="Waqar Younis"),
    ]


# --------------------------------------------------------------------------
# One scenario per rule
# --------------------------------------------------------------------------

def s_r010() -> Decision:
    """No transactions at all: nothing for any other rule to look at."""
    return run(claim(), order(), [])


def s_r020() -> Decision:
    """A perfect match that another order already consumed."""
    return run(
        claim(),
        order(),
        [txn()],
        [Allocation(txn_id="TX1001", order_id="O-OTHER")],
    )


def s_r030() -> Decision:
    """Rs. 500 arrived; the screenshot says Rs. 5,000."""
    return run(
        claim(amount=Money(500_000)),
        order(Money(500_000)),
        [txn(amount=Money(50_000))],
    )


def s_r040() -> Decision:
    """Two image signals on a claim whose fields only half agree."""
    return run(
        claim(ref=None, sender=OTHER_SENDER),
        order(),
        [txn()],
        observations=(
            ObservationCode.IMAGE_ELA_ANOMALY,
            ObservationCode.IMAGE_EDITOR_SIGNATURE,
        ),
    )


def s_r050() -> Decision:
    """Two identical Rs. 2,000 payments and a receipt with no transaction id."""
    return run(claim(ref=None), order(), busy_feed())


def s_r060() -> Decision:
    """A transaction in the window, but nothing about it matches."""
    return run(
        claim(amount=Money(777_000), ref="ZZZ999", sender=None, when=None),
        order(),
        [txn()],
    )


def s_r065() -> Decision:
    """A perfect match against a row the merchant typed in by hand."""
    return run(claim(), order(), [txn(source=Source.MANUAL_ENTRY)])


def s_r070() -> Decision:
    """Rs. 1,950 against a Rs. 2,000 order, and the receipt agrees."""
    return run(
        claim(amount=Money(195_000)),
        order(RS_2000),
        [txn(amount=Money(195_000))],
    )


def s_r080() -> Decision:
    """Rs. 2,050 against a Rs. 2,000 order."""
    return run(
        claim(amount=Money(205_000)),
        order(RS_2000),
        [txn(amount=Money(205_000))],
    )


def s_r090() -> Decision:
    """Everything agrees."""
    return run(claim(), order(), [txn()])


def s_r999() -> Decision:
    """Half the fields agree and nothing else is wrong: a human decides."""
    return run(claim(ref=None, sender=OTHER_SENDER), order(), [txn()])


SCENARIOS: tuple[tuple[str, object, Status, Risk, ReasonCode | None], ...] = (
    ("R010", s_r010, Status.UNMATCHED, Risk.MEDIUM, ReasonCode.NO_CANDIDATES),
    ("R020", s_r020, Status.DUPLICATE, Risk.HIGH, ReasonCode.TXN_ALREADY_ALLOCATED),
    ("R030", s_r030, Status.SUSPICIOUS, Risk.HIGH, ReasonCode.CLAIM_INFLATED),
    ("R040", s_r040, Status.SUSPICIOUS, Risk.HIGH, ReasonCode.TAMPER_OBSERVATIONS),
    ("R050", s_r050, Status.NEEDS_REVIEW, Risk.MEDIUM, ReasonCode.AMBIGUOUS_CANDIDATES),
    ("R060", s_r060, Status.UNMATCHED, Risk.MEDIUM, ReasonCode.NAME_MISMATCH),
    (
        "R065",
        s_r065,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        ReasonCode.SOURCE_PARTIALLY_TRUSTED,
    ),
    ("R070", s_r070, Status.NEEDS_REVIEW, Risk.MEDIUM, ReasonCode.AMOUNT_UNDERPAID),
    ("R080", s_r080, Status.VERIFIED, Risk.LOW, ReasonCode.AMOUNT_OVERPAID),
    ("R090", s_r090, Status.VERIFIED, Risk.LOW, ReasonCode.STRONG_FIELD_AGREEMENT),
    ("R999", s_r999, Status.NEEDS_REVIEW, Risk.MEDIUM, None),
)


@pytest.mark.parametrize(
    ("rule_id", "scenario", "status", "risk", "reason"),
    SCENARIOS,
    ids=[row[0] for row in SCENARIOS],
)
def test_scenario_fires_its_rule(rule_id, scenario, status, risk, reason):
    decision = scenario()
    assert decision.fired_rule_id == rule_id
    assert decision.status is status
    assert decision.risk is risk
    if reason is not None:
        assert reason in decision.reasons


def test_every_rule_is_covered():
    covered = {row[0] for row in SCENARIOS}
    assert covered == {rule.id for rule in RULES}


def test_fired_rule_id_is_recorded_on_every_decision():
    ids = {rule.id for rule in RULES}
    for _, scenario, *_ in SCENARIOS:
        assert scenario().fired_rule_id in ids


# --------------------------------------------------------------------------
# Rule-table structure
# --------------------------------------------------------------------------

def test_rule_ids_are_ascending_unique_and_always_leave_room_to_insert():
    """Ids are ordered and never crowded.

    This used to assert that consecutive ids differ by *exactly* ten, which
    contradicted the reason the gaps exist: `R065` had to be inserted between
    `R060` and `R070` to route a partially trusted source to review, and
    renumbering `R070` onwards is forbidden - an id must mean the same thing in
    this table and in every decision ever stored. What matters is the invariant
    the gap buys, so that is what is asserted: strictly ascending, unique, and
    never numerically adjacent, so there is always room for the next insertion.
    """
    ids = [rule.id for rule in RULES]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    numeric = [int(rule_id[1:]) for rule_id in ids[:-1]]
    assert all(b - a >= 2 for a, b in pairwise(numeric)), (
        f"no room left to insert a rule between two of {ids}"
    )
    assert ids[-1] == "R999"


def test_the_table_ends_in_a_total_else():
    assert RULES[-1].when is total_else
    assert all(rule.when is not total_else for rule in RULES[:-1])


def test_structural_impossibility_precedes_everything():
    order_of = {rule.id: i for i, rule in enumerate(RULES)}
    assert order_of["R010"] == 0


def test_safety_negative_outranks_safety_positive():
    order_of = {rule.id: i for i, rule in enumerate(RULES)}
    verified = [rule.id for rule in RULES if rule.status is Status.VERIFIED]
    unsafe = [
        rule.id
        for rule in RULES
        if rule.status in (Status.DUPLICATE, Status.SUSPICIOUS)
    ]
    assert unsafe, "the table must be able to say no"
    assert max(order_of[i] for i in unsafe) < min(order_of[i] for i in verified)


def test_specific_amount_rules_precede_the_general_verification():
    order_of = {rule.id: i for i, rule in enumerate(RULES)}
    assert order_of["R070"] < order_of["R090"]
    assert order_of["R080"] < order_of["R090"]


def test_a_hand_built_table_without_an_else_raises():
    partial = (Rule("R010", lambda c: False, Status.VERIFIED, Risk.LOW, (), "never"),)
    ctx = build_context(claim(), order(), [txn()], [], now=NOW, policy=POLICY)
    with pytest.raises(AssertionError, match="not total"):
        first_match(ctx, partial)


# --------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------

def test_an_empty_ledger_can_never_be_verified():
    for a_claim in (
        claim(),
        claim(amount=None, ref=None, sender=None, when=None),
        claim(ref="TX1001"),
    ):
        assert run(a_claim, order(), []).status is not Status.VERIFIED


def test_screenshot_sourced_evidence_cannot_verify():
    """The one architectural commitment, as a post-condition rather than prose.

    The transaction here matches on every field; only its provenance is wrong.
    """
    feed = [txn(source=Source.CUSTOMER_SCREENSHOT)]
    with pytest.raises(AssertionError, match="non-ledger evidence"):
        run(claim(), order(), feed)


def test_simulator_sourced_evidence_may_verify():
    """Demo fixtures are ledger-grade by policy; see TRUSTED_LEDGER_SOURCES."""
    decision = run(claim(), order(), [txn(source=Source.SIMULATOR)])
    assert decision.status is Status.VERIFIED


def test_enforce_invariants_rejects_verified_without_a_transaction():
    ctx = build_context(claim(), order(), [], [], now=NOW, policy=POLICY)
    forged = Decision(
        status=Status.VERIFIED,
        risk=Risk.LOW,
        confidence=1.0,
        reasons=(ReasonCode.STRONG_FIELD_AGREEMENT,),
        matched_txn_id="TX1001",          # a transaction that is not in the ranking
        fired_rule_id="R090",
        evidence=(),
        observations=(),
        ruleset_version=RULESET_VERSION,
        policy_fingerprint=POLICY.fingerprint(),
        engine_version=ENGINE_VERSION,
        evaluated_at=NOW,
    )
    with pytest.raises(AssertionError, match="without a ledger transaction"):
        _enforce_invariants(forged, ctx)


def test_enforce_invariants_lets_non_verified_decisions_through():
    ctx = build_context(claim(), order(), [], [], now=NOW, policy=POLICY)
    decision = run(claim(), order(), [])
    assert _enforce_invariants(decision, ctx) is decision


# --------------------------------------------------------------------------
# The matched transaction id
# --------------------------------------------------------------------------

def test_a_verified_decision_names_its_transaction():
    assert s_r090().matched_txn_id == "TX1001"


def test_an_unmatched_decision_names_nothing():
    assert s_r010().matched_txn_id is None
    assert s_r060().matched_txn_id is None


def test_an_ambiguous_decision_refuses_to_name_a_transaction():
    """Naming one of several interchangeable payments is the bug R050 exists
    to prevent; putting one in the payload lets the caller allocate it anyway."""
    assert s_r050().matched_txn_id is None


def test_a_duplicate_decision_names_the_contested_transaction():
    assert s_r020().matched_txn_id == "TX1001"


# --------------------------------------------------------------------------
# Aggregate scoring
# --------------------------------------------------------------------------

def outcome(field: str, code: str, score: float) -> FieldOutcome:
    return FieldOutcome(field=field, level_code=code, label=code, score=score)


def test_a_perfect_match_scores_one():
    outcomes = {c.field: outcome(c.field, f"{c.field.upper()}_OK", 1.0) for c in COMPARISONS}
    assert aggregate_score(outcomes, POLICY) == 1.0


def test_an_unreadable_field_does_not_count_as_a_mismatch():
    """A receipt that never printed a transaction id must still be verifiable."""
    outcomes = {c.field: outcome(c.field, f"{c.field.upper()}_OK", 1.0) for c in COMPARISONS}
    outcomes["reference"] = outcome("reference", "REF_MISSING", 0.0)
    missing = aggregate_score(outcomes, POLICY)

    outcomes["reference"] = outcome("reference", "REF_ELSE", 0.0)
    mismatched = aggregate_score(outcomes, POLICY)

    assert missing > mismatched
    assert missing >= POLICY.tau_accept


def test_a_name_alone_cannot_reach_acceptance():
    """Everything unreadable but one perfectly matching name."""
    outcomes = {
        c.field: outcome(c.field, f"{c.field.upper()}_MISSING", 0.0) for c in COMPARISONS
    }
    outcomes[SENDER_NAME.field] = outcome(SENDER_NAME.field, "NAME_EXACT", 1.0)
    assert aggregate_score(outcomes, POLICY) < POLICY.tau_accept


def test_everything_unreadable_scores_zero():
    outcomes = {
        c.field: outcome(c.field, f"{c.field.upper()}_MISSING", 0.0) for c in COMPARISONS
    }
    assert aggregate_score(outcomes, POLICY) == 0.0


def test_a_zero_missing_penalty_makes_unreadable_fields_free():
    lenient = DecisionPolicy(missing_evidence_penalty=0.0)
    outcomes = {
        c.field: outcome(c.field, f"{c.field.upper()}_MISSING", 0.0) for c in COMPARISONS
    }
    outcomes[SENDER_NAME.field] = outcome(SENDER_NAME.field, "NAME_EXACT", 1.0)
    assert aggregate_score(outcomes, lenient) == 1.0


def test_score_candidate_produces_one_outcome_per_comparison():
    index = TxnIndex.build([txn()], idf_floor=POLICY.blocking_idf_floor)
    scored = score_candidate(
        claim(), txn(), idf=scoring_idf(index, POLICY), policy=POLICY
    )
    assert {o.field for o in scored.evidence} == {c.field for c in COMPARISONS}
    assert scored.score == 1.0
    assert scored.outcomes["reference"].level_code == "REF_EXACT"
    assert scored.outcomes["amount"].level_code == "AMT_EXACT"
    assert scored.outcomes["timestamp"].level_code == "TS_TIGHT"
    assert scored.outcomes["sender_name"].level_code == "NAME_EXACT"


# --------------------------------------------------------------------------
# Confidence
# --------------------------------------------------------------------------

def test_confidence_of_a_lone_perfect_match_is_one():
    ctx = build_context(claim(), order(), [txn()], [], now=NOW, policy=POLICY)
    assert confidence(ctx.ranking, ctx.evidence, POLICY) == 1.0


def test_confidence_falls_when_the_margin_collapses():
    feed = busy_feed()
    lone = build_context(
        claim(ref=None),
        order(),
        [t for t in feed if t.txn_id != "TX-B"],
        [],
        now=NOW,
        policy=POLICY,
    )
    twins = build_context(claim(ref=None), order(), feed, [], now=NOW, policy=POLICY)
    assert confidence(twins.ranking, twins.evidence, POLICY) < confidence(
        lone.ranking, lone.evidence, POLICY
    )


def test_confidence_falls_when_fields_are_unreadable():
    full = build_context(claim(), order(), [txn()], [], now=NOW, policy=POLICY)
    partial = build_context(
        claim(ref=None, sender=None), order(), [txn()], [], now=NOW, policy=POLICY
    )
    assert confidence(partial.ranking, partial.evidence, POLICY) < confidence(
        full.ranking, full.evidence, POLICY
    )


def test_confidence_with_no_evidence_at_all_is_the_formula_floor():
    ctx = build_context(claim(), order(), [], [], now=NOW, policy=POLICY)
    # 0.5*0 (no candidate) + 0.3*1 (a lone candidate has nothing to be confused
    # with) + 0.2*0 (nothing was compared).
    assert confidence(ctx.ranking, ctx.evidence, POLICY) == 0.3


def test_confidence_is_never_a_fraud_probability():
    """It is bounded, and every decision carries one — including UNMATCHED,
    where a fraud probability would be meaningless."""
    for _, scenario, *_ in SCENARIOS:
        try:
            decision = scenario()
        except AssertionError:  # pragma: no cover - no scenario does this
            continue
        assert 0.0 <= decision.confidence <= 1.0


# --------------------------------------------------------------------------
# Amount evidence in context
# --------------------------------------------------------------------------

def test_amounts_are_not_compared_against_an_incredible_candidate():
    """Otherwise any smaller transaction in the window makes a claim look
    inflated, and R030 accuses a customer whose real answer is UNMATCHED."""
    ctx = build_context(
        claim(amount=Money(777_000), ref="ZZZ999", sender=None, when=None),
        order(),
        [txn()],
        [],
        now=NOW,
        policy=POLICY,
    )
    assert ctx.best is not None
    assert ctx.best.score < POLICY.tau_reject
    assert ctx.amount_compared is False
    assert ctx.amount is NO_AMOUNT_EVIDENCE
    assert ctx.material_inflation is False


def test_no_candidate_means_no_amount_comparison():
    ctx = build_context(claim(), order(), [], [], now=NOW, policy=POLICY)
    assert ctx.amount.relation is AmountRelation.UNKNOWN
    assert ctx.amount.integrity is ClaimIntegrity.UNKNOWN
    assert ctx.amount.shortfall is None
    assert ctx.amount.within_tolerance is True   # nothing to breach


def test_an_order_without_a_total_reports_the_missing_expectation():
    decision = run(claim(), None, [txn()])
    assert decision.status is Status.VERIFIED
    assert ReasonCode.MISSING_ORDER_AMOUNT in decision.reasons
    assert ReasonCode.CLAIM_CONSISTENT in decision.reasons


def test_amount_reason_codes_are_appended_after_the_rule_reasons():
    decision = s_r090()
    assert decision.reasons[0] is ReasonCode.STRONG_FIELD_AGREEMENT
    assert ReasonCode.AMOUNT_EXACT in decision.reasons


def test_an_unmatched_decision_carries_no_amount_reasons():
    reasons = set(s_r060().reasons)
    assert not reasons & {
        ReasonCode.AMOUNT_EXACT,
        ReasonCode.AMOUNT_UNDERPAID,
        ReasonCode.MISSING_ORDER_AMOUNT,
    }


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------

def test_re_verifying_the_same_order_is_idempotent_not_duplicate():
    decision = run(
        claim(),
        order(order_id="O-1"),
        [txn()],
        [Allocation(txn_id="TX1001", order_id="O-1")],
    )
    assert decision.status is Status.VERIFIED
    assert decision.fired_rule_id == "R090"


def test_an_allocated_runner_up_does_not_make_a_duplicate():
    decision = run(
        claim(),
        order(),
        [txn("TX1001"), txn("TX-OTHER", ref="TX-OTHER")],
        [Allocation(txn_id="TX-OTHER", order_id="O-OTHER")],
    )
    assert decision.status is Status.VERIFIED


def test_duplicate_outranks_verification():
    """A high score must never pre-empt the duplicate check."""
    decision = s_r020()
    assert decision.status is Status.DUPLICATE
    assert decision.fired_rule_id == "R020"


# --------------------------------------------------------------------------
# Tamper observations
# --------------------------------------------------------------------------

def test_only_image_signals_count_as_tamper():
    ctx = build_context(
        claim(notes=(ObservationCode.AMOUNT_SEPARATOR_AMBIGUOUS,)),
        order(),
        [txn()],
        [],
        now=NOW,
        policy=POLICY,
        observations=(ObservationCode.IMAGE_ELA_ANOMALY,),
    )
    assert ctx.tamper_count == 1
    assert set(TAMPER_OBSERVATION_CODES) <= set(ObservationCode)


def test_one_tamper_signal_alone_does_not_accuse():
    """Every WhatsApp forward is re-compressed; the default limit tolerates one."""
    decision = run(
        claim(ref=None, sender=OTHER_SENDER),
        order(),
        [txn()],
        observations=(ObservationCode.IMAGE_RECOMPRESSED,),
    )
    assert decision.status is Status.NEEDS_REVIEW
    assert decision.fired_rule_id == "R999"


def test_tamper_signals_cannot_overturn_a_strong_match():
    """R040 requires a weak match too — image forensics never decide alone."""
    decision = run(
        claim(),
        order(),
        [txn()],
        observations=(
            ObservationCode.IMAGE_ELA_ANOMALY,
            ObservationCode.IMAGE_EDITOR_SIGNATURE,
            ObservationCode.IMAGE_RECOMPRESSED,
        ),
    )
    assert decision.status is Status.VERIFIED


def test_observations_reach_the_decision_deduplicated():
    decision = run(
        claim(notes=(ObservationCode.AMOUNT_NON_ASCII_DIGITS,)),
        order(),
        [txn()],
        observations=(
            ObservationCode.IMAGE_EXIF_MISSING,
            ObservationCode.IMAGE_EXIF_MISSING,
        ),
    )
    assert decision.observations.count(ObservationCode.IMAGE_EXIF_MISSING) == 1
    assert ObservationCode.AMOUNT_NON_ASCII_DIGITS in decision.observations
    assert ObservationCode.TIME_TZ_ASSUMED in decision.observations


def test_observations_are_never_reason_codes():
    decision = run(
        claim(),
        order(),
        [txn()],
        observations=(ObservationCode.IMAGE_ELA_ANOMALY,),
    )
    assert ObservationCode.IMAGE_ELA_ANOMALY not in set(decision.reasons)


# --------------------------------------------------------------------------
# Determinism and provenance
# --------------------------------------------------------------------------

def test_the_decision_does_not_depend_on_feed_order():
    feed = [txn(f"TX-{i}", at=PAID_AT + timedelta(minutes=i)) for i in range(8)]
    baseline = run(claim(ref=None), order(), list(feed))
    shuffled = list(feed)
    random.Random(1234).shuffle(shuffled)
    assert run(claim(ref=None), order(), shuffled) == baseline


def test_the_decision_records_how_it_was_taken():
    decision = s_r090()
    assert decision.ruleset_version == RULESET_VERSION
    assert decision.engine_version == ENGINE_VERSION
    assert decision.policy_fingerprint == POLICY.fingerprint()
    assert decision.evaluated_at == NOW


def test_evaluated_at_is_the_now_that_was_handed_in():
    other = NOW + timedelta(days=400)
    decision = decide(claim(), order(), [txn()], [], now=other, policy=POLICY)
    assert decision.evaluated_at == other


def test_a_different_policy_leaves_a_different_fingerprint():
    strict = DecisionPolicy(tau_accept=0.95)
    assert run(claim(), order(), [txn()], policy=strict).policy_fingerprint != s_r090(
    ).policy_fingerprint


def test_evidence_is_one_row_per_comparison_in_a_stable_order():
    decision = s_r090()
    assert [e.field for e in decision.evidence] == sorted(c.field for c in COMPARISONS)


def test_a_prebuilt_index_gives_the_same_answer():
    feed = [txn()]
    assert decide(
        claim(), order(), TxnIndex.build(feed, idf_floor=POLICY.blocking_idf_floor), [], now=NOW, policy=POLICY
    ) == run(claim(), order(), feed)


# --------------------------------------------------------------------------
# The dominance escape hatch
# --------------------------------------------------------------------------

def _ref_only_candidate(txn_id: str, score: float, ref_code: str) -> ScoredCandidate:
    """A candidate carrying nothing but a reference verdict, for margin tests."""
    return ScoredCandidate(
        txn=txn(txn_id),
        score=score,
        outcomes={
            "reference": outcome(
                "reference", ref_code, 1.0 if ref_code == "REF_EXACT" else 0.0
            )
        },
    )


def test_a_printed_transaction_id_picks_the_right_one_of_two_twins():
    decision = run(claim(ref="TX-A"), order(), busy_feed())
    assert decision.status is Status.VERIFIED
    assert decision.matched_txn_id == "TX-A"


def test_without_a_transaction_id_the_same_pair_goes_to_review():
    decision = run(claim(ref=None), order(), busy_feed())
    assert decision.fired_rule_id == "R050"
    assert decision.status is Status.NEEDS_REVIEW


def test_dominance_overrides_the_margin_rule():
    """A unique exact transaction id wins even on a dead-even margin.

    The margin rule exists to protect against *interchangeable* candidates,
    and a printed TID means they are not interchangeable.
    """
    base = build_context(claim(), order(), [txn()], [], now=NOW, policy=POLICY)
    tied = CandidateRanking.of(
        [
            _ref_only_candidate("TX-A", 0.95, "REF_EXACT"),
            _ref_only_candidate("TX-B", 0.95, "REF_ELSE"),
        ]
    )
    ctx = replace(base, ranking=tied)
    assert ctx.ranking.margin == 0.0
    assert ctx.dominant is True
    assert first_match(ctx).id == "R090"


def test_a_tie_without_dominance_goes_to_review():
    base = build_context(claim(), order(), [txn()], [], now=NOW, policy=POLICY)
    tied = CandidateRanking.of(
        [
            _ref_only_candidate("TX-A", 0.95, "REF_MISSING"),
            _ref_only_candidate("TX-B", 0.95, "REF_MISSING"),
        ]
    )
    ctx = replace(base, ranking=tied)
    assert ctx.dominant is False
    assert first_match(ctx).id == "R050"


# --------------------------------------------------------------------------
# Ambiguity: demo case 4, and what the engine must refuse to name
# --------------------------------------------------------------------------

#: overview.md section 8, case 4, in its hardest form: a bare feed of two
#: interchangeable payments from a customer with one of the commonest names in
#: Pakistan. Nothing here is decoration - the shared common name is what pins
#: the sender token to the IDF floor, which is what kept the pair below
#: `tau_accept` and out of `R050`'s reach.
TWIN_AT = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)          # 14:00 PKT
RS_250 = Money(25_000)
COMMON_SENDER = "Muhammad Ali"


def twin_feed() -> list[LedgerTxn]:
    return [
        txn("TX2001", amount=RS_250, at=TWIN_AT, sender=COMMON_SENDER),
        txn("TX2002", amount=RS_250, at=TWIN_AT, sender=COMMON_SENDER),
    ]


def twin_claim(**kwargs) -> PaymentClaim:
    return claim(
        amount=RS_250,
        ref=None,
        sender=COMMON_SENDER,
        when=at_pkt(datetime(2026, 3, 4, 14, 0)),
        **kwargs,
    )


def test_two_interchangeable_payments_are_ambiguous_even_below_tau_accept():
    """Demo case 4: "Two possible transactions match this screenshot".

    Ambiguity is about indistinguishability, not strength. These two rows are
    identical in amount, instant and sender, so no evidence on earth separates
    them - and yet both score ~0.72, because a receipt with no transaction id
    is capped well below 1.0 and two rows sharing one common name drive that
    name to the IDF floor. `R050` used to demand `>= tau_accept`, so it never
    fired here: the claim fell through to `R999`, which carries no reasons, and
    the engine handed back one of the two arbitrarily for the caller to
    allocate.
    """
    ctx = build_context(twin_claim(), order(RS_250), twin_feed(), [], now=NOW, policy=POLICY)
    assert ctx.ranking.margin == 0.0
    assert ctx.best_score < POLICY.tau_accept
    assert ctx.best_score >= POLICY.tau_ambiguous
    assert ctx.indistinguishable is True
    assert ctx.ambiguous is True

    decision = run(twin_claim(), order(RS_250), twin_feed())
    assert decision.fired_rule_id == "R050"
    assert decision.status is Status.NEEDS_REVIEW
    assert ReasonCode.AMBIGUOUS_CANDIDATES in decision.reasons
    assert decision.matched_txn_id is None


def test_an_indistinguishable_ranking_names_nothing_whichever_rule_fires():
    """The suppression is a property of the ranking, not of the fired rule.

    Two identical Rs 500 payments and a receipt claiming Rs 5,000: `R030` wins
    on precedence, well above `R050`, and it carries no ambiguity reason code.
    Keying the suppression off the fired rule's reasons therefore leaked one of
    two interchangeable transactions into `matched_txn_id` - which the caller
    then allocates, whatever the status said.
    """
    feed = [
        txn("TX-500-A", amount=Money(50_000), sender=SENDER),
        txn("TX-500-B", amount=Money(50_000), sender=SENDER),
    ]
    inflated = claim(amount=Money(500_000), ref=None)
    ctx = build_context(inflated, order(Money(500_000)), feed, [], now=NOW, policy=POLICY)
    assert ctx.indistinguishable is True

    decision = run(inflated, order(Money(500_000)), feed)
    assert decision.fired_rule_id == "R030"
    assert decision.status is Status.SUSPICIOUS
    assert ReasonCode.AMBIGUOUS_CANDIDATES not in decision.reasons
    assert decision.matched_txn_id is None


def test_a_lone_plausible_candidate_is_never_ambiguous():
    """`R050` needs two candidates. One transaction has nothing to be confused
    with, and a rule that fired on it would refuse to name the only match
    there is."""
    ctx = build_context(twin_claim(), order(RS_250), twin_feed()[:1], [], now=NOW, policy=POLICY)
    assert len(ctx.ranking.scored) == 1
    assert ctx.indistinguishable is False
    assert ctx.ambiguous is False
    assert run(twin_claim(), order(RS_250), twin_feed()[:1]).matched_txn_id == "TX2001"


def test_an_incredible_tie_is_unmatched_rather_than_ambiguous():
    """Below `tau_ambiguous` there is no credible candidate to be confused
    about, so `R060`'s "nothing matched" is the honest answer and `R050` must
    stay out of the way."""
    feed = [
        txn("TX-X", amount=Money(777_000), at=PAID_AT, sender="Nadia Perveen"),
        txn("TX-Y", amount=Money(777_000), at=PAID_AT, sender="Nadia Perveen"),
    ]
    weak = claim(amount=Money(123_000), ref="ZZZ999", sender=None, when=None)
    ctx = build_context(weak, order(), feed, [], now=NOW, policy=POLICY)
    assert ctx.indistinguishable is True
    assert ctx.best_score < POLICY.tau_ambiguous
    assert ctx.ambiguous is False

    decision = run(weak, order(), feed)
    assert decision.fired_rule_id == "R060"
    assert decision.matched_txn_id is None


def test_an_unrelated_row_carrying_the_claims_reference_cannot_break_the_tie():
    """Dominance means *the winner* is the unique exact reference match.

    Two interchangeable payments, and a third transaction that matches nothing
    - wrong amount, six hours away, a different customer - whose provider id
    happens to be the one printed on the receipt. It ranks last and could never
    be the match. Dominance that only counted `REF_EXACT` candidates anywhere
    in the ranking let that row switch off the ambiguity rule for the two at
    the top, turning a correct NEEDS_REVIEW into a VERIFIED naming one of two
    interchangeable payments.
    """
    ref = "EP99887766"
    twins = [
        txn("TX-A", at=PAID_AT, sender=SENDER, ref="A1" + ref[2:]),
        txn("TX-B", at=PAID_AT, sender=SENDER, ref="B2" + ref[2:]),
    ]
    stranger = txn(
        "TX-Z",
        amount=Money(99_900),
        at=PAID_AT - timedelta(hours=6, minutes=13),
        sender="Waqar Younis",
        ref=ref,
    )
    tail_claim = claim(ref=ref)

    without = build_context(tail_claim, order(), twins, [], now=NOW, policy=POLICY)
    assert without.dominant is False
    assert without.ambiguous is True

    ctx = build_context(tail_claim, order(), [*twins, stranger], [], now=NOW, policy=POLICY)
    assert ctx.ranking.txn_ids()[-1] == "TX-Z", "the stranger must rank last"
    assert ctx.ranking.scored[-1].outcomes["reference"].level_code == "REF_EXACT"
    assert ctx.dominant is False, "dominance requires the winner to hold the id"

    decision = run(tail_claim, order(), [*twins, stranger])
    assert decision.fired_rule_id == "R050"
    assert decision.status is Status.NEEDS_REVIEW
    assert decision.matched_txn_id is None


# --------------------------------------------------------------------------
# Provenance: trust is a rule, not a crash
# --------------------------------------------------------------------------

@pytest.mark.parametrize("source", sorted(TRUSTED_LEDGER_SOURCES))
def test_a_ledger_grade_source_verifies(source):
    decision = run(claim(), order(), [txn(source=source)])
    assert decision.status is Status.VERIFIED
    assert decision.fired_rule_id == "R090"
    assert decision.matched_txn_id == "TX1001"


@pytest.mark.parametrize("source", sorted(PARTIALLY_TRUSTED_SOURCES))
def test_a_partially_trusted_source_goes_to_a_human_rather_than_crashing(source):
    """`Source` documents CSV imports and hand-keyed rows as real, partially
    trusted feeds, but no rule inspected `txn.source`: the table returned
    VERIFIED and the post-condition assertion then killed the verification, so
    a merchant who imports by CSV could get no answer at all. Trust is a rule
    now, and the assertion is the backstop it was meant to be."""
    decision = run(claim(), order(), [txn(source=source)])
    assert decision.status is Status.NEEDS_REVIEW
    assert decision.fired_rule_id == "R065"
    assert ReasonCode.SOURCE_PARTIALLY_TRUSTED in decision.reasons
    assert decision.matched_txn_id == "TX1001"


def test_every_source_is_either_trusted_partially_trusted_or_refused():
    """No `Source` may fall through the trust model unclassified.

    A source in neither set is not evidence at all, and reaching VERIFIED on
    one has to raise rather than return - which is what the last assertion
    checks, for the only member that is deliberately in neither set.
    """
    assert not (TRUSTED_LEDGER_SOURCES & PARTIALLY_TRUSTED_SOURCES)
    unclassified = set(Source) - TRUSTED_LEDGER_SOURCES - PARTIALLY_TRUSTED_SOURCES
    assert unclassified == {Source.CUSTOMER_SCREENSHOT}
    with pytest.raises(AssertionError, match="non-ledger evidence"):
        run(claim(), order(), [txn(source=Source.CUSTOMER_SCREENSHOT)])


def test_a_partially_trusted_source_that_matches_weakly_is_still_just_weak():
    """`R065` says "this would have verified, but for its provenance". A claim
    that was never going to verify is not a trust problem, and must keep the
    answer it had."""
    decision = run(
        claim(ref=None, sender=OTHER_SENDER),
        order(),
        [txn(source=Source.MERCHANT_CSV)],
    )
    assert decision.fired_rule_id == "R999"
    assert ReasonCode.SOURCE_PARTIALLY_TRUSTED not in decision.reasons


def test_provenance_is_settled_before_any_rule_offers_to_release_goods():
    order_of = {rule.id: i for i, rule in enumerate(RULES)}
    verified = [rule.id for rule in RULES if rule.status is Status.VERIFIED]
    assert order_of["R065"] < min(order_of[i] for i in verified)


# --------------------------------------------------------------------------
# Context plumbing
# --------------------------------------------------------------------------

def test_best_score_is_zero_when_there_is_no_candidate():
    ctx = build_context(claim(), order(), [], [], now=NOW, policy=POLICY)
    assert ctx.best is None
    assert ctx.best_score == 0.0
    assert ctx.evidence == ()
    assert ctx.dominant is False


def test_an_empty_ranking_is_falsy_and_measures_a_full_margin():
    empty = CandidateRanking.of([])
    assert not empty
    assert empty.margin == 1.0


def test_a_batch_may_reuse_one_name_idf():
    index = TxnIndex.build([txn()], idf_floor=POLICY.blocking_idf_floor)
    idf = scoring_idf(index, POLICY)
    reused = build_context(
        claim(), order(), index, [], now=NOW, policy=POLICY, name_idf=idf
    )
    fresh = build_context(claim(), order(), index, [], now=NOW, policy=POLICY)
    assert reused.best.score == fresh.best.score


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------

def test_the_fingerprint_is_sixteen_stable_hex_characters():
    fp = POLICY.fingerprint()
    assert len(fp) == 16
    assert all(ch in "0123456789abcdef" for ch in fp)
    assert fp == DecisionPolicy().fingerprint()


def test_changing_any_threshold_changes_the_fingerprint():
    baseline = POLICY.fingerprint()
    for changed in (
        DecisionPolicy(tau_accept=0.83),
        DecisionPolicy(tau_margin=0.11),
        DecisionPolicy(tau_ambiguous=0.5),
        DecisionPolicy(amount_tolerance_minor=100),
        DecisionPolicy(policy_id="proofpay-policy-1.0.1"),
        DecisionPolicy(name_idf_floor=0.16),
    ):
        assert changed.fingerprint() != baseline


def _nudge(value):
    """A different, still-legal value for one policy field."""
    if isinstance(value, str):
        return value + "-changed"
    if isinstance(value, bool):  # pragma: no cover - no bool fields today
        return not value
    if isinstance(value, int):
        return value + 1
    return value + 0.01 if value <= 0.99 else value - 0.01


def test_changing_any_policy_field_at_all_changes_the_fingerprint():
    """Every field, not a hand-picked five.

    `policy.py` promises that "change any threshold and every subsequent
    decision carries a visibly different fingerprint", and the promise is only
    worth what the weakest field makes it worth. This walks the dataclass, so a
    tunable added later is covered the day it is added - and a tunable that
    steers decisions from *outside* the policy is exactly the hole this test
    cannot see, which is why the constants that used to live outside it were
    moved in.
    """
    baseline = DecisionPolicy()
    for spec in fields(DecisionPolicy):
        changed = replace(baseline, **{spec.name: _nudge(getattr(baseline, spec.name))})
        assert changed.fingerprint() != baseline.fingerprint(), (
            f"{spec.name} does not reach the fingerprint"
        )


def test_no_decision_steering_constant_survives_outside_the_policy():
    """The specific numbers that used to steer decisions from module scope.

    Each of these changed a verdict while `policy_fingerprint`,
    `ruleset_version` and `engine_version` all stayed identical, which makes a
    stored decision unreconstructable from its own stamps. They are policy
    fields now; this asserts the old copies did not survive alongside them,
    because two homes for one number is how they drift apart again.
    """
    from proofpay.core import retrieval as retrieval_mod
    from proofpay.core.compare import reference as reference_mod
    from proofpay.core.compare import timestamp as timestamp_mod
    from proofpay.core.decide import engine as engine_mod

    gone = (
        (timestamp_mod, "SIM_TIGHT"),
        (timestamp_mod, "SIM_CLOSE"),
        (timestamp_mod, "SIM_LOOSE"),
        (reference_mod, "MIN_PARTIAL_LEN"),
        (retrieval_mod, "COMMON_NAME_IDF"),
        (engine_mod, "SENDER_NAME_WEIGHT"),
    )
    for module, name in gone:
        assert not hasattr(module, name), (
            f"{module.__name__}.{name} still steers decisions from outside the policy"
        )

    policy = DecisionPolicy()
    assert policy.ts_sim_tight_t == 0.98
    assert policy.ts_sim_close_t == 0.80
    assert policy.ts_sim_loose_t == 0.40
    assert policy.ref_min_partial_len == 4
    assert policy.blocking_idf_floor == 0.15
    assert policy.field_weights() == {
        "reference": 1.0,
        "amount": 1.0,
        "timestamp": 0.8,
        "sender_name": 0.6,
    }


def test_a_retuned_level_cut_point_moves_the_verdict_and_the_fingerprint_together():
    """The audit claim, stated as one test.

    Raising the `TS_CLOSE` cut-point turns this receipt's ten-minute skew from
    "within a few minutes" into "roughly the same time" and drops the aggregate
    below `tau_accept`. That flip used to be invisible: the constant lived in
    `compare/timestamp.py`, so the two decisions carried identical policy
    fingerprints, ruleset versions and engine versions, and nothing in the
    stored record said why they differed.
    """
    strict = DecisionPolicy(ts_sim_close_t=0.95)
    inputs = (
        claim(ref=None, when=at_pkt(datetime(2026, 3, 4, 15, 52))),
        order(),
        [txn()],
    )
    lenient_decision = run(*inputs)
    strict_decision = run(*inputs, policy=strict)

    assert lenient_decision.evidence_by_field()["timestamp"].level_code == "TS_CLOSE"
    assert strict_decision.evidence_by_field()["timestamp"].level_code == "TS_LOOSE"
    assert lenient_decision.status is Status.VERIFIED
    assert strict_decision.status is Status.NEEDS_REVIEW
    assert lenient_decision.policy_fingerprint != strict_decision.policy_fingerprint


def test_a_retuned_field_weight_moves_the_verdict_and_the_fingerprint_together():
    """The same claim for the weights, which steer just as hard as a cut-point.

    A printed transaction id, the right amount and the right minute, against a
    sender name that does not agree at all. Under the shipped weights the name
    is the weakest of the four signals and the claim verifies at 0.824; weigh
    the name like a transaction id and the same evidence lands in review.
    """
    heavier = DecisionPolicy(w_sender_name=1.0)
    inputs = (claim(sender=OTHER_SENDER), order(), [txn()])
    assert run(*inputs).status is Status.VERIFIED
    assert run(*inputs, policy=heavier).status is not Status.VERIFIED
    assert heavier.fingerprint() != POLICY.fingerprint()


def test_the_fingerprint_does_not_depend_on_argument_order():
    assert DecisionPolicy(tau_accept=0.9, tau_reject=0.5).fingerprint() == DecisionPolicy(
        tau_reject=0.5, tau_accept=0.9
    ).fingerprint()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tau_accept": 1.5},
        {"tau_reject": -0.1},
        {"tau_accept": 0.4, "tau_reject": 0.5},   # no accept band at all
        {"time_window_s": -1},
        {"max_candidates": 0},
        {"amount_tolerance_minor": -1},
        {"inflation_material_minor": -1},
        {"inflation_material_pct": 2.0},
        {"tamper_signal_limit": -1},
        {"missing_evidence_penalty": 1.5},
        {"tau_ambiguous": 1.5},
        # Ambiguity above acceptance would let a ranking too close to call slip
        # past R050 and verify one of two interchangeable payments.
        {"tau_ambiguous": 0.9},
        {"ref_min_partial_len": 0},
        {"blocking_idf_floor": 1.5},
        {"w_sender_name": -0.1},
        {"ts_sim_close_t": 0.99},   # cut-points crossing
    ],
)
def test_an_incoherent_policy_is_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        DecisionPolicy(**kwargs)


def test_the_policy_is_frozen():
    with pytest.raises(FrozenInstanceError):
        POLICY.tau_accept = 0.5      # type: ignore[misc]


def test_the_policy_supplies_the_comparison_thresholds():
    thresholds = POLICY.name_thresholds()
    assert thresholds.strong == POLICY.name_strong_t
    assert thresholds.common_idf == POLICY.name_common_idf_t

    params = POLICY.timestamp_params()
    assert params.scale_s == POLICY.ts_scale_s
    assert params.hour_artifact_tol_s == POLICY.hour_artifact_tol_s


def test_a_stricter_policy_refuses_what_a_default_policy_accepts():
    """The whole point of a versioned policy: the same inputs, a different
    verdict, and a fingerprint that says which thresholds were in force."""
    strict = DecisionPolicy(tau_accept=0.99)
    inputs = (claim(ref=None, sender=OTHER_SENDER), order(), [txn(sender=OTHER_SENDER)])
    assert run(*inputs).status is Status.VERIFIED
    assert run(*inputs, policy=strict).status is Status.NEEDS_REVIEW


def test_decide_requires_now_as_a_keyword():
    with pytest.raises(TypeError):
        decide(claim(), order(), [txn()], [], POLICY)   # type: ignore[misc]
