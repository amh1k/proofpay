"""Explanation tests: the merchant-facing rendering, and what it must never say.

The load-bearing test in this file is `test_no_explanation_ever_shows_a
_percentage`. "Fraud probability: 87%" is the output this product exists to
not produce, and a percentage is exactly the kind of thing that gets added back
by someone being helpful.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from proofpay.core.compare.levels import Agreement
from proofpay.core.decide.engine import decide
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.explain import (
    MARK_AGREE,
    MARK_CAUTION,
    MARK_CONFLICT,
    MARK_UNKNOWN,
    Explanation,
    explain,
    format_money,
    render_text,
)
from proofpay.core.models import (
    Allocation,
    FieldOutcome,
    LedgerTxn,
    Order,
    PaymentClaim,
)
from proofpay.core.money import Money
from proofpay.core.reasons import ObservationCode, ReasonCode, Risk, Source, Status
from proofpay.core.timex import GRANULARITY_DAY, PKT, ClaimedInstant

MERCHANT = "M-1"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 3, 4, 10, 42, tzinfo=UTC)   # 15:42 PKT
RS_2000 = Money(200_000)
SENDER = "Zulqarnain Haider"
POLICY = DecisionPolicy()


def txn(
    txn_id: str = "TX1001",
    *,
    amount: Money = RS_2000,
    at: datetime = PAID_AT,
    sender: str | None = SENDER,
    source: Source = Source.MERCHANT_LEDGER,
) -> LedgerTxn:
    return LedgerTxn(
        txn_id=txn_id,
        amount=amount,
        occurred_at=at,
        merchant_id=MERCHANT,
        external_id=txn_id,
        sender_name=sender,
        source=source,
    )


CLAIMED_AT = ClaimedInstant.from_local(datetime(2026, 3, 4, 15, 42), tz=PKT, granularity_s=60)


def claim(
    *,
    amount: Money | None = RS_2000,
    ref: str | None = "TX1001",
    sender: str | None = SENDER,
    when: ClaimedInstant | None = CLAIMED_AT,
    field_confidences: Mapping[str, float] | None = None,
) -> PaymentClaim:
    return PaymentClaim(
        claim_id="C-1",
        merchant_id=MERCHANT,
        amount=amount,
        reference_id=ref,
        sender_name=sender,
        occurred_at=when,
        field_confidences=dict(field_confidences or {}),
    )


def order(expected: Money | None = RS_2000, order_id: str = "O-1") -> Order:
    return Order(order_id=order_id, expected=expected, merchant_id=MERCHANT)


def explained(
    the_claim: PaymentClaim,
    the_order: Order | None,
    feed: list[LedgerTxn],
    allocations: tuple[Allocation, ...] = (),
    *,
    observations: tuple[str, ...] = (),
    matched: LedgerTxn | None = None,
    include_txn: bool = True,
) -> Explanation:
    """Explain a decision the engine really took.

    `include_txn=False` is the replay path: a caller holding a stored decision
    that never re-fetched the ledger row. It is a supported way to call
    `explain`, so every rendering invariant has to survive it.
    """
    decision = decide(
        the_claim,
        the_order,
        feed,
        allocations,
        now=NOW,
        policy=POLICY,
        observations=observations,
    )
    if matched is None:
        matched = next(
            (t for t in feed if t.txn_id == decision.matched_txn_id), None
        )
    return explain(
        decision,
        claim=the_claim,
        txn=matched if include_txn else None,
        order=the_order,
    )


# --------------------------------------------------------------------------
# The five results
# --------------------------------------------------------------------------

def verified(*, include_txn: bool = True) -> Explanation:
    return explained(claim(), order(), [txn()], include_txn=include_txn)


def unmatched(*, include_txn: bool = True) -> Explanation:
    return explained(claim(), order(), [], include_txn=include_txn)


def suspicious(*, include_txn: bool = True) -> Explanation:
    return explained(
        claim(amount=Money(500_000)),
        order(Money(500_000)),
        [txn(amount=Money(50_000))],
        matched=txn(amount=Money(50_000)),
        include_txn=include_txn,
    )


def duplicate(*, include_txn: bool = True) -> Explanation:
    return explained(
        claim(),
        order(),
        [txn()],
        [Allocation(txn_id="TX1001", order_id="O-OTHER")],
        include_txn=include_txn,
    )


def underpaid(*, include_txn: bool = True) -> Explanation:
    return explained(
        claim(amount=Money(195_000)),
        order(RS_2000),
        [txn(amount=Money(195_000))],
        matched=txn(amount=Money(195_000)),
        include_txn=include_txn,
    )


def partially_trusted(*, include_txn: bool = True) -> Explanation:
    """`R065`: a match good enough to verify, against a row the merchant
    imported or keyed in by hand. It is in `ALL` so every rendering invariant
    in this file - no percentage, no hole where money should be - covers it."""
    return explained(
        claim(),
        order(),
        [txn(source=Source.MERCHANT_CSV)],
        include_txn=include_txn,
    )


def poorly_read(*, include_txn: bool = True) -> Explanation:
    """`R067`: every field agrees, and the reader says it was unsure of one.

    Like `partially_trusted` it only ever fires on a match strong enough to have
    verified, so it lands the same trap: a screen of four ticks under a sentence
    saying there is not enough evidence. In `ALL` for exactly that reason.
    """
    return explained(
        claim(field_confidences={"amount": 0.5}),
        order(),
        [txn()],
    )


ALL = (
    verified,
    unmatched,
    suspicious,
    duplicate,
    underpaid,
    partially_trusted,
    poorly_read,
)


@pytest.mark.parametrize(
    ("build", "status"),
    [
        (verified, Status.VERIFIED),
        (unmatched, Status.UNMATCHED),
        (suspicious, Status.SUSPICIOUS),
        (duplicate, Status.DUPLICATE),
        (underpaid, Status.NEEDS_REVIEW),
        (partially_trusted, Status.NEEDS_REVIEW),
        (poorly_read, Status.NEEDS_REVIEW),
    ],
    ids=[f.__name__ for f in ALL],
)
def test_each_result_gets_its_own_headline_and_action(build, status):
    e = build()
    assert e.status is status
    assert e.headline and e.headline != ""
    assert e.recommended_action.endswith(".")
    assert e.summary


def test_every_status_has_a_headline_and_an_action():
    """A status added without display text must fail here, not at a counter."""
    for status in Status:
        from proofpay.core.explain import _ACTIONS, _HEADLINES

        assert status in _HEADLINES
        assert status in _ACTIONS


# --------------------------------------------------------------------------
# The thing this product refuses to say
# --------------------------------------------------------------------------

def test_no_explanation_ever_shows_a_percentage():
    for build in ALL:
        text = build().render()
        assert "%" not in text
        assert "probability" not in text.lower()
        assert "fraud" not in text.lower()


def test_risk_is_rendered_as_an_ordinal_band():
    text = verified().render()
    assert f"Risk: {Risk.LOW}" in text


def test_confidence_is_not_rendered_at_all():
    """It is on the `Decision` for the API; it is not a number to show a
    shopkeeper, who would read it as a probability."""
    assert "confidence" not in verified().render().lower()


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def test_rows_read_in_narrative_order_not_alphabetical():
    assert [r.field for r in verified().rows] == [
        "reference",
        "amount",
        "timestamp",
        "sender_name",
    ]


def test_a_row_carries_claimed_actual_and_a_verdict():
    row = next(r for r in verified().rows if r.field == "amount")
    assert row.label == "Amount"
    assert row.claimed == "Rs 2,000"
    assert row.actual == "Rs 2,000"
    assert row.level_code == "AMT_EXACT"
    assert row.verdict == "Amount matches the transaction exactly"
    assert row.mark == MARK_AGREE
    assert row.agrees


def test_an_agreeing_field_is_ticked():
    assert all(r.mark == MARK_AGREE for r in verified().rows)


def test_a_conflicting_field_is_crossed():
    e = explained(
        claim(ref="ZZZ-9999"), order(), [txn()], matched=txn()
    )
    row = next(r for r in e.rows if r.field == "reference")
    assert row.mark == MARK_CONFLICT
    assert row.level_code == "REF_ELSE"


def test_an_unreadable_field_is_a_question_mark_not_a_cross():
    """Absence of evidence is not evidence of mismatch, and the row must not
    look like an accusation."""
    e = explained(claim(ref=None), order(), [txn()], matched=txn())
    row = next(r for r in e.rows if r.field == "reference")
    assert row.mark == MARK_UNKNOWN
    assert row.claimed == "—"


def test_a_partial_field_is_flagged_for_attention():
    """A field that agrees, but only loosely, is a caution and not a cross.

    (Previously asserted on `AMT_SCALED`, which is not a partial agreement at
    all — see `test_a_scaled_amount_is_not_softer_than_a_plain_mismatch`.)
    """
    date_only = ClaimedInstant.from_local(
        datetime(2026, 3, 4), tz=PKT, granularity_s=GRANULARITY_DAY
    )
    e = explained(claim(when=date_only), order(), [txn()], matched=txn())
    row = next(r for r in e.rows if r.field == "timestamp")
    assert row.level_code == "TS_DATE_ONLY"
    assert row.mark == MARK_CAUTION


def test_rows_show_an_em_dash_when_no_transaction_was_matched():
    e = unmatched()
    assert e.rows == ()          # nothing was compared, so there is nothing to show
    assert e.matched_txn_id is None


# --------------------------------------------------------------------------
# Money and time formatting
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("money", "text"),
    [
        (Money(200_000), "Rs 2,000"),
        (Money(50_000), "Rs 500"),
        (Money(123_450), "Rs 1,234.50"),
        (Money(1_234_567_800), "Rs 12,345,678"),
        (Money(0), "Rs 0"),
        (Money(5), "Rs 0.05"),
        (None, "—"),
    ],
)
def test_money_is_formatted_for_a_receipt_not_for_a_ledger(money, text):
    assert format_money(money) == text


def test_times_are_shown_on_the_merchants_clock():
    """Stored instants are UTC; a Karachi merchant reading 10:42 would think a
    correct match was five hours wrong."""
    row = next(r for r in verified().rows if r.field == "timestamp")
    assert row.claimed == "2026-03-04 15:42"
    assert row.actual == "2026-03-04 15:42"


def test_a_date_only_receipt_is_not_shown_as_midnight():
    date_only = ClaimedInstant.from_local(
        datetime(2026, 3, 4), tz=PKT, granularity_s=GRANULARITY_DAY
    )
    e = explained(claim(when=date_only), order(), [txn()], matched=txn())
    row = next(r for r in e.rows if r.field == "timestamp")
    assert row.claimed == "2026-03-04"


# --------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------

def test_the_verified_summary_names_the_transaction_and_the_money():
    e = verified()
    assert "Rs 2,000 received." in e.summary
    assert "TX1001" in e.summary


def test_the_suspicious_summary_contrasts_the_two_amounts():
    assert suspicious().summary == (
        "The screenshot claims Rs 5,000, but Rs 500 was received."
    )


def test_the_underpaid_summary_names_the_order_total():
    summary = underpaid().summary
    assert "Rs 1,950" in summary
    assert "Rs 2,000" in summary


def test_the_duplicate_summary_says_what_happened():
    assert "already used" in duplicate().summary


def test_the_unmatched_summary_does_not_accuse_anyone():
    summary = unmatched().summary.lower()
    assert "not found" in summary or "no matching" in summary
    assert "fake" not in summary and "fraud" not in summary


def test_an_unmatched_result_tells_the_merchant_to_wait_not_to_reject():
    assert "processing" in unmatched().recommended_action


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------

def test_observations_are_rendered_in_plain_language():
    e = explained(
        claim(),
        order(),
        [txn()],
        observations=(ObservationCode.IMAGE_ELA_ANOMALY,),
        matched=txn(),
    )
    assert "Possible editing detected in part of the image" in e.observations


def test_an_unmapped_observation_is_shown_rather_than_dropped():
    from proofpay.core.explain import _observation_lines

    assert _observation_lines(("SOMETHING_NEW",)) == ("SOMETHING_NEW",)


def test_observations_are_never_presented_as_the_verdict():
    e = explained(
        claim(),
        order(),
        [txn()],
        observations=(ObservationCode.IMAGE_ELA_ANOMALY,),
        matched=txn(),
    )
    assert e.status is Status.VERIFIED
    assert e.observations       # noticed, and said out loud
    assert ReasonCode.TAMPER_OBSERVATIONS not in e.reasons


# --------------------------------------------------------------------------
# The rendered text
# --------------------------------------------------------------------------

def test_the_rendered_text_follows_the_product_overview_layout():
    text = suspicious().render()
    lines = text.splitlines()

    assert lines[0] == "⚠ PAYMENT DETAILS DO NOT MATCH"
    assert lines[1] == ""
    assert "Screenshot:" in text and "Received:" in text
    assert f"{MARK_AGREE} Transaction ID:" in text
    assert "Risk: HIGH" in text
    assert text.endswith("Do not approve the order yet.")
    assert "Recommended action:" in lines


def test_the_two_amounts_are_column_aligned():
    """`Rs 5,000` above `Rs   500` is the whole point of the block."""
    lines = suspicious().render().splitlines()
    screenshot = next(line for line in lines if line.startswith("Screenshot:"))
    received = next(line for line in lines if line.startswith("Received:"))
    assert len(screenshot) == len(received)


def test_the_amount_block_is_omitted_when_nothing_was_matched():
    text = unmatched().render()
    assert "Received:" not in text


def test_render_text_and_the_render_method_agree():
    e = verified()
    assert render_text(e) == e.render()


def test_every_row_appears_in_the_rendered_text():
    e = verified()
    text = e.render()
    for row in e.rows:
        assert f"{row.mark} {row.label}: {row.verdict}" in text


def test_the_explanation_carries_the_machine_contract_too():
    """The frontend formats this contract; it must not have to re-derive it."""
    e = verified()
    assert e.fired_rule_id == "R090"
    assert e.ruleset_version.startswith("rules-v")
    assert ReasonCode.STRONG_FIELD_AGREEMENT in e.reasons
    assert e.matched_txn_id == "TX1001"


def test_explaining_without_the_transaction_still_renders():
    """A caller replaying a stored decision may not have fetched the row.

    It used to be asserted here that an em dash appeared in that rendering.
    It did — in the middle of the VERIFIED summary, where the money goes (see
    `test_the_verified_summary_names_the_money_even_without_the_ledger_row`).
    What this test actually protects is that the replay path renders at all.
    """
    decision = decide(claim(), order(), [txn()], [], now=NOW, policy=POLICY)
    text = explain(decision, claim=claim(), order=order()).render()
    assert text.startswith("✅ PAYMENT VERIFIED")
    assert "TX1001" in text
    assert "%" not in text


# --------------------------------------------------------------------------
# R1 — the VERIFIED summary dropped the amount
#
# `_summary` took the received amount from `txn.amount` and from nothing else.
# `txn` is optional (a caller replaying a stored decision holds the decision,
# not the ledger row), and only the mismatch branches were written to cope with
# its absence — so a genuine Rs 2,000 payment rendered
#
#     ✅ PAYMENT VERIFIED
#
#     — received. Transaction TX1001 matches the submitted proof.
#
# with an em dash standing where the money goes.
# --------------------------------------------------------------------------

def test_the_verified_summary_names_the_money_even_without_the_ledger_row():
    """The decision itself recorded that the amounts were equal, so the
    received amount is known whether or not the caller re-fetched the row."""
    e = verified(include_txn=False)
    assert e.status is Status.VERIFIED
    assert "Rs 2,000 received." in e.summary
    assert "—" not in e.summary


def test_the_verified_summary_is_the_two_lines_from_the_product_overview():
    """overview.md section 5, exactly: the money first, then what it matched."""
    assert verified().summary == (
        "Rs 2,000 received.\nTransaction TX1001 matches the submitted proof."
    )


@pytest.mark.parametrize("include_txn", [True, False], ids=["with_txn", "replayed"])
@pytest.mark.parametrize("build", ALL, ids=[f.__name__ for f in ALL])
def test_no_summary_ever_leaves_a_hole_where_money_should_be(build, include_txn):
    """Every status, both ways of calling `explain`. A sentence about money
    with the money missing is worse than no sentence at all, so a branch that
    cannot name an amount must drop the clause, not print the placeholder."""
    from proofpay.core.explain import ABSENT

    summary = build(include_txn=include_txn).summary
    assert ABSENT not in summary
    assert summary and summary.strip() == summary


def test_the_underpaid_summary_names_the_money_without_the_ledger_row():
    """The NEEDS_REVIEW branch read `txn.amount` the same way VERIFIED did."""
    summary = underpaid(include_txn=False).summary
    assert "Rs 1,950" in summary
    assert "Rs 2,000" in summary


def test_a_verified_summary_says_less_when_the_amount_was_never_readable():
    """No amount on the receipt, no ledger row in hand: there is no honest way
    to name a figure, so the sentence that names one is dropped entirely."""
    e = explained(claim(amount=None), order(), [txn()], include_txn=False)
    assert e.status is Status.VERIFIED
    assert e.summary == "Transaction TX1001 matches the submitted proof."


def test_an_overpaid_verified_summary_still_names_both_figures():
    e = explained(
        claim(amount=Money(250_000)),
        order(RS_2000),
        [txn(amount=Money(250_000))],
        matched=txn(amount=Money(250_000)),
    )
    assert e.status is Status.VERIFIED
    assert ReasonCode.AMOUNT_OVERPAID in e.reasons
    assert "Rs 2,500 received." in e.summary
    assert "more than the order total of Rs 2,000" in e.summary


# --------------------------------------------------------------------------
# R2 / R3 — the mark is the level's meaning, never its score
#
# R2: `NAME_COMMON_ONLY` (0.20) says the names *agree* on a name too common to
#     identify anyone. A score band rendered that agreement as a red cross —
#     on a VERIFIED payment, in demo case 1, where both sides read
#     "Muhammad Ali" byte for byte.
# R3: `AMT_SCALED` (0.35) is a deliberate factor-of-ten digit edit and rendered
#     a caution: softer than the cross on a plain `AMT_ELSE` mismatch (0.00).
#
# The meaning itself has since moved out of this module. `explain.py` used to
# hold its own `_MARK_BY_LEVEL` table, which made presentation the only place
# that knew which levels contradict — and the decision engine, which needs the
# same fact to refuse to verify a contradicted match, could not read it without
# importing the renderer. It is now `Level.agreement`, declared beside the rung
# in `compare/levels.py`, and both layers consume it. These tests therefore pin
# two separate things: that the shipped classification still says what it said
# (below), and that the renderer translates it faithfully.
# --------------------------------------------------------------------------

DEMO_NAME = "Muhammad Ali"   # overview.md section 8 case 1, identical both sides

#: Every level code the comparisons can produce today, with the score it
#: actually carries, the meaning it declares and the mark that meaning must
#: render as. The scores are here on purpose: they are what a score band would
#: have keyed on, so a table that disagrees with them is the point.
#:
#: This is a *pin*, not a source. The source is `Level.agreement` in
#: `compare/levels.py`; `test_the_shipped_ladders_still_declare_these_meanings`
#: below asserts the two agree, so re-classifying a level is a visible diff in
#: this file rather than a silent change to what a merchant is shown.
LEVEL_MARKS: tuple[tuple[str, float, Agreement, str], ...] = (
    ("REF_EXACT", 1.00, Agreement.AGREE, MARK_AGREE),
    ("REF_CONFUSABLE", 0.90, Agreement.AGREE, MARK_AGREE),
    ("REF_SUFFIX", 0.75, Agreement.AGREE, MARK_AGREE),
    ("REF_PARTIAL", 0.55, Agreement.WEAK, MARK_CAUTION),
    ("REF_MISSING", 0.00, Agreement.MISSING, MARK_UNKNOWN),
    ("REF_ELSE", 0.00, Agreement.CONTRADICT, MARK_CONFLICT),
    ("AMT_EXACT", 1.00, Agreement.AGREE, MARK_AGREE),
    ("AMT_TOLERANCE", 0.90, Agreement.AGREE, MARK_AGREE),
    ("AMT_SCALED", 0.35, Agreement.CONTRADICT, MARK_CONFLICT),
    ("AMT_MISSING", 0.00, Agreement.MISSING, MARK_UNKNOWN),
    ("AMT_ELSE", 0.00, Agreement.CONTRADICT, MARK_CONFLICT),
    ("TS_TIGHT", 1.00, Agreement.AGREE, MARK_AGREE),
    ("TS_CLOSE", 0.85, Agreement.AGREE, MARK_AGREE),
    ("TS_DATE_ONLY", 0.60, Agreement.WEAK, MARK_CAUTION),
    ("TS_LOOSE", 0.50, Agreement.WEAK, MARK_CAUTION),
    ("TS_HOUR_ART", 0.25, Agreement.WEAK, MARK_CAUTION),
    ("TS_MISSING", 0.00, Agreement.MISSING, MARK_UNKNOWN),
    ("TS_ELSE", 0.00, Agreement.CONTRADICT, MARK_CONFLICT),
    ("NAME_EXACT", 1.00, Agreement.AGREE, MARK_AGREE),
    ("NAME_STRONG", 0.90, Agreement.AGREE, MARK_AGREE),
    ("NAME_MASK_OK", 0.85, Agreement.AGREE, MARK_AGREE),
    ("NAME_INITIALS", 0.80, Agreement.AGREE, MARK_AGREE),
    ("NAME_PARTIAL", 0.55, Agreement.WEAK, MARK_CAUTION),
    ("NAME_COMMON_ONLY", 0.20, Agreement.WEAK, MARK_CAUTION),
    ("NAME_MISSING", 0.00, Agreement.MISSING, MARK_UNKNOWN),
    ("NAME_ELSE", 0.00, Agreement.CONTRADICT, MARK_CONFLICT),
)

#: How loud each mark is. Only the ordering matters.
SEVERITY = {MARK_AGREE: 0, MARK_UNKNOWN: 1, MARK_CAUTION: 2, MARK_CONFLICT: 3}


def outcome(
    code: str,
    score: float,
    field: str = "sender_name",
    agreement: Agreement = Agreement.AGREE,
) -> FieldOutcome:
    return FieldOutcome(
        field=field, level_code=code, label=code, score=score, agreement=agreement
    )


@pytest.mark.parametrize(
    ("code", "score", "agreement", "expected"),
    LEVEL_MARKS,
    ids=[code for code, _, _, _ in LEVEL_MARKS],
)
def test_the_mark_is_the_levels_meaning_not_its_score(code, score, agreement, expected):
    """Every shipped level, rendered from what it declares.

    The score is passed in and deliberately ignored by the renderer: rows like
    `NAME_COMMON_ONLY` (0.20, agrees) and `AMT_SCALED` (0.35, contradicts) are
    in this table precisely because a score band gets both of them backwards.
    """
    from proofpay.core.explain import _mark

    assert _mark(outcome(code, score, agreement=agreement)) == expected


def test_the_shipped_ladders_still_declare_these_meanings():
    """The pin. `LEVEL_MARKS` above is this test file's copy of what each rung
    means; `Level.agreement` is the real one. Re-classifying a level is a
    legitimate act, and it has to show up as a diff here rather than silently
    changing what a merchant is shown - or what the rule table refuses to
    verify, which reads the same field."""
    from proofpay.core.compare.amount_match import AMOUNT_MATCH
    from proofpay.core.compare.name import SENDER_NAME
    from proofpay.core.compare.reference import REFERENCE
    from proofpay.core.compare.timestamp import TIMESTAMP

    pinned = {code: agreement for code, _, agreement, _ in LEVEL_MARKS}
    for comparison in (REFERENCE, AMOUNT_MATCH, TIMESTAMP, SENDER_NAME):
        for level in comparison.levels:
            assert pinned[level.code] == level.agreement, (
                f"{level.code} now declares {level.agreement}; this test pins "
                f"{pinned[level.code]}"
            )


def test_there_is_no_unclassified_level_left_to_guess_at():
    """The score-band fallback is gone, and this is why it could go.

    `explain.py` used to fall back to `_AGREE_PCT`/`_CONFLICT_PCT` for a level
    code nobody had classified - the very band that rendered
    `NAME_COMMON_ONLY`'s agreement as a red cross. It existed because the
    classification lived in a lookup table that a new level could miss.
    `Agreement` is a required field on `Level` and a closed enum, so every
    outcome carries a meaning and every meaning has a mark: the mapping is
    total, and there is nothing left for a fallback to catch.
    """
    from proofpay.core import explain as explain_mod
    from proofpay.core.explain import _MARK_BY_AGREEMENT, _mark

    assert set(_MARK_BY_AGREEMENT) == set(Agreement)
    assert not hasattr(explain_mod, "_MARK_BY_LEVEL")
    assert not hasattr(explain_mod, "_AGREE_PCT")
    assert not hasattr(explain_mod, "_CONFLICT_PCT")
    for agreement in Agreement:
        assert _mark(outcome("X_ANYTHING", 0.5, agreement=agreement)) in SEVERITY


def test_every_level_in_every_comparison_renders_one_of_the_four_marks():
    """Walk the live ladders: no level, present or future, renders nothing."""
    from proofpay.core.compare.amount_match import AMOUNT_MATCH
    from proofpay.core.compare.name import name_comparison
    from proofpay.core.compare.reference import REFERENCE
    from proofpay.core.compare.timestamp import TIMESTAMP
    from proofpay.core.explain import _mark

    declared = {code: mark for code, _, _, mark in LEVEL_MARKS}
    ladders = (REFERENCE, AMOUNT_MATCH, TIMESTAMP, name_comparison("sender_name"))
    for comparison in ladders:
        for level in comparison.levels:
            mark = _mark(
                outcome(
                    level.code, level.score, comparison.field, agreement=level.agreement
                )
            )
            assert mark in SEVERITY
            assert mark == declared[level.code], (
                f"{level.code} declares {level.agreement} but LEVEL_MARKS in "
                "this test expects a different mark"
            )


def test_a_byte_identical_common_name_is_not_rendered_as_a_contradiction():
    """overview.md section 8, demo case 1: 'Muhammad Ali' on both sides, VERIFIED.

    The name agrees. It is simply not distinctive enough to identify anyone,
    which is a caution about the *weight* of the evidence, not a claim that the
    field contradicts the match.
    """
    e = explained(
        claim(sender=DEMO_NAME),
        order(),
        [txn(sender=DEMO_NAME)],
        matched=txn(sender=DEMO_NAME),
    )
    row = next(r for r in e.rows if r.field == "sender_name")
    assert e.status is Status.VERIFIED
    assert row.level_code == "NAME_COMMON_ONLY"
    assert row.mark == MARK_CAUTION
    assert MARK_CONFLICT not in e.render()


def test_a_common_name_row_says_the_name_agrees():
    """The wording has to agree with the mark, or the row still accuses."""
    e = explained(
        claim(sender=DEMO_NAME),
        order(),
        [txn(sender=DEMO_NAME)],
        matched=txn(sender=DEMO_NAME),
    )
    row = next(r for r in e.rows if r.field == "sender_name")
    assert "agrees" in row.verdict.lower()
    assert "common" in row.verdict.lower()
    assert row.level_code == "NAME_COMMON_ONLY"     # the machine id is untouched


HOUR_OFF = ClaimedInstant.from_local(
    datetime(2026, 3, 4, 14, 42), tz=PKT, granularity_s=60
)
DATE_ONLY = ClaimedInstant.from_local(
    datetime(2026, 3, 4), tz=PKT, granularity_s=GRANULARITY_DAY
)

#: VERIFIED decisions the engine really reaches, spread across every level that
#: means agreement: exact/suffix/confusable/absent reference, exact/absent
#: amount, tight/date-only/whole-hour timestamps, and every name level above
#: NAME_ELSE. Built lazily so collection does not run the engine.
VERIFIED_CASES = {
    "exact": lambda: explained(claim(), order(), [txn()]),
    "common_name": lambda: explained(
        claim(sender=DEMO_NAME), order(), [txn(sender=DEMO_NAME)]
    ),
    "masked_name": lambda: explained(claim(sender="Z***** Haider"), order(), [txn()]),
    "initials": lambda: explained(claim(sender="Z. Haider"), order(), [txn()]),
    "partial_name": lambda: explained(
        claim(sender="Zulqarnain Sheikh"), order(), [txn()]
    ),
    "ref_suffix": lambda: explained(claim(ref="1001"), order(), [txn("EPX-TX1001")]),
    "ref_confusable": lambda: explained(claim(ref="TXI00l"), order(), [txn()]),
    "no_ref": lambda: explained(claim(ref=None), order(), [txn()]),
    "date_only": lambda: explained(claim(when=DATE_ONLY), order(), [txn()]),
    "hour_offset": lambda: explained(claim(when=HOUR_OFF), order(), [txn()]),
    "no_amount": lambda: explained(claim(amount=None), order(), [txn()]),
    "overpaid": lambda: explained(
        claim(amount=Money(250_000)), order(RS_2000), [txn(amount=Money(250_000))]
    ),
}


@pytest.mark.parametrize("case", sorted(VERIFIED_CASES))
def test_no_verified_result_renders_a_cross_on_an_agreeing_field(case):
    """The invariant behind R2: on a payment the engine verified, no field that
    agrees — however weakly, however common the name, however coarse the clock
    — may be shown to the merchant as contradicting the match."""
    e = VERIFIED_CASES[case]()
    assert e.status is Status.VERIFIED
    crossed = [(r.field, r.level_code, r.verdict) for r in e.rows if r.mark == MARK_CONFLICT]
    assert crossed == []
    assert MARK_CONFLICT not in e.render()


def test_a_scaled_amount_is_not_softer_than_a_plain_mismatch():
    """R3: Rs 5,000 claimed against Rs 500 received is a deliberate digit edit.
    It cannot render more gently than an amount that merely fails to match."""
    scaled = next(r for r in suspicious().rows if r.field == "amount")
    plain = explained(claim(amount=Money(170_000)), order(), [txn()], matched=txn())
    mismatch = next(r for r in plain.rows if r.field == "amount")

    assert scaled.level_code == "AMT_SCALED"
    assert mismatch.level_code == "AMT_ELSE"
    assert SEVERITY[scaled.mark] >= SEVERITY[mismatch.mark]
    assert scaled.mark == MARK_CONFLICT


def test_the_flagship_demo_crosses_out_the_amount():
    """overview.md section 5, SUSPICIOUS: 'Amount does not match', crossed."""
    text = suspicious().render()
    assert f"{MARK_CONFLICT} Amount:" in text
    assert "Screenshot: Rs 5,000" in text
    assert "Received:     Rs 500" in text


# --------------------------------------------------------------------------
# What the rendering must never contain, in every status and both call styles
# --------------------------------------------------------------------------

#: `Rs 1,234.50` is money, not a probability. Strip it before hunting for the
#: bare decimals that would mean a score leaked into the merchant's view.
_MONEY_TEXT = re.compile(r"Rs [\d,]+(?:\.\d+)?")

_FORBIDDEN_WORDS = (
    "%",
    "percent",
    "probability",
    "fraud",
    "confidence",
    "score",
    "likelihood",
    "odds",
)


@pytest.mark.parametrize("include_txn", [True, False], ids=["with_txn", "replayed"])
@pytest.mark.parametrize("build", ALL, ids=[f.__name__ for f in ALL])
def test_no_status_ever_renders_a_percentage_or_a_bare_probability(build, include_txn):
    text = build(include_txn=include_txn).render()
    lowered = text.lower()
    for word in _FORBIDDEN_WORDS:
        assert word not in lowered, f"{word!r} leaked into the {build.__name__} render"
    assert re.search(r"\d\.\d", _MONEY_TEXT.sub("", text)) is None


# --------------------------------------------------------------------------
# Provenance: the review screen has to say why a human is being asked
# --------------------------------------------------------------------------

def test_a_partially_trusted_match_says_provenance_not_missing_evidence():
    """`R065` fires only on a match strong enough to have verified, so the
    generic NEEDS_REVIEW sentence was a false statement sitting directly above
    four agreeing rows: "there is not enough evidence" next to
    `✓ ✓ ✓ ✓` reads as a broken system, and the merchant cannot act on it.
    What is missing is provenance, not evidence, and the screen must say so.
    """
    e = partially_trusted()

    assert e.status is Status.NEEDS_REVIEW
    assert "not enough evidence" not in e.summary.lower()
    assert "imported or hand-entered" in e.summary
    assert "confirm" in e.summary.lower()

    # The premise of the test: every field really does agree.
    assert [row.mark for row in e.rows] == [MARK_AGREE] * len(e.rows)


def test_the_provenance_sentence_survives_the_replay_path():
    """`explain` takes `txn` optionally, so the sentence must come from the
    reason code on the decision and never from `txn.source` - a caller
    replaying a stored decision does not hold the ledger row."""
    stored = partially_trusted(include_txn=False)

    assert "imported or hand-entered" in stored.summary
    assert "not enough evidence" not in stored.summary.lower()


def test_a_partially_trusted_underpayment_states_the_shortfall_and_the_reason():
    """`R065` outranks `R070` and `AMOUNT_UNDERPAID` is derived from the
    arithmetic rather than attached to a rule, so both codes ride on the same
    decision. Reporting only one of them hides a fact the merchant needs:
    the shortfall is what they are deciding about, the provenance is why the
    decision reached them at all."""
    e = explained(
        claim(amount=Money(195_000)),
        order(RS_2000),
        [txn(amount=Money(195_000), source=Source.MANUAL_ENTRY)],
    )

    assert e.status is Status.NEEDS_REVIEW
    assert ReasonCode.AMOUNT_UNDERPAID in e.reasons
    assert ReasonCode.SOURCE_PARTIALLY_TRUSTED in e.reasons
    assert "Rs 1,950 was received against an order for Rs 2,000." in e.summary
    assert "imported or hand-entered" in e.summary


def test_an_unclear_screenshot_blames_the_reading_and_not_the_customer():
    """`R067`'s sentence, and where the blame in it points.

    The payment may be perfectly good — every field agrees. What went wrong is
    that we could not make out part of the picture, so the wording has to say
    that about US. "The receipt is unclear" accuses the customer of sending a
    bad one, and a merchant who repeats it to them is repeating an accusation
    the engine never made.
    """
    e = poorly_read()

    assert e.status is Status.NEEDS_REVIEW
    assert ReasonCode.LOW_EXTRACTION_CONFIDENCE in e.reasons
    assert "could not be read clearly" in e.summary
    assert "not enough evidence" not in e.summary.lower()
    # The premise, as in the provenance test above: every field really agrees.
    assert [row.mark for row in e.rows] == [MARK_AGREE] * len(e.rows)


def test_only_a_reasonless_decision_says_there_is_not_enough_evidence():
    """The generic sentence is `R999`'s, and pointing any reasoned rule at it
    is how a specific finding gets rendered as a shrug."""
    generic = "There is not enough evidence to decide this automatically."

    assert partially_trusted().summary != generic
    assert underpaid().summary != generic
    assert poorly_read().summary != generic


def test_every_level_code_in_every_comparison_has_a_declared_agreement():
    """The seam between a comparison, the rule table and this renderer.

    The classification used to be a lookup table in `explain.py` keyed by level
    code, and a level added or renamed in `compare/` fell through it onto a
    score band silently - which is what rendered `NAME_COMMON_ONLY`'s 0.20
    agreement as a red contradiction. It is now a required field on `Level`, so
    "every level is classified" is true by construction rather than by
    vigilance; this walks the live ladders and says so out loud, including the
    `*_MISSING` rungs, which the old table deliberately could not cover.

    It also checks this test file's own pin has not gone stale in the other
    direction: a code listed here that no comparison produces means a level was
    renamed or removed, and a renamed level code is a broken contract.
    """
    from proofpay.core.compare.amount_match import AMOUNT_MATCH
    from proofpay.core.compare.name import SENDER_NAME
    from proofpay.core.compare.reference import REFERENCE
    from proofpay.core.compare.timestamp import TIMESTAMP

    ladders = (REFERENCE, AMOUNT_MATCH, TIMESTAMP, SENDER_NAME)
    real = {
        level.code: level
        for comparison in ladders
        for level in comparison.levels
    }
    for code, level in real.items():
        assert isinstance(level.agreement, Agreement), (
            f"{code} declares no Agreement"
        )
        # The suffix convention and the declared meaning are one statement made
        # twice, and `Level.__post_init__` ties them together.
        assert (level.agreement is Agreement.MISSING) == code.endswith("_MISSING")

    pinned = {code for code, _, _, _ in LEVEL_MARKS}
    assert not pinned - set(real), (
        f"this test pins levels no comparison produces (renamed or removed?): "
        f"{sorted(pinned - set(real))}"
    )
    assert not set(real) - pinned, (
        f"levels nobody has pinned a mark for in this file: "
        f"{sorted(set(real) - pinned)}"
    )
