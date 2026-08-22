"""A field that contradicts the match must block VERIFIED.

The bug this file exists for, exactly as it was reported:

    Screenshot claims  Rs 2,000, TID EP19730264, 18:31, from "Zubair Qureshi"
    Ledger holds       Rs 2,000, TID EP19730264, 18:31, from "Farhan Bhatti"

    ✅ PAYMENT VERIFIED      Risk: LOW      Continue with the order.
    ✓ Transaction ID: matches exactly
    ✓ Amount: matches exactly
    ✓ Timestamp: matches exactly
    ✗ Sender name: No name match

Three perfect fields carried the aggregate to 0.823529 against a `tau_accept`
of 0.82, and the merchant was handed a screen that says two opposite things at
once. There is no threshold that fixes this: a cut-point answers "how much
evidence is there", and the problem is that some of the evidence points the
other way. Direction is categorical, so it is a rule - `R075` - and it sits
above both verifying rules and below the safety-negative ones.

What each test here pins:

* the reported input, and the same shape for a contradicting reference and a
  contradicting timestamp;
* that the block survives a policy retune, which is what makes it a rule rather
  than a luckier threshold;
* that the rendered screen stops contradicting itself;
* that `R020` and `R030` keep their precedence, because the demo depends on it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from proofpay.core.compare.levels import Agreement
from proofpay.core.decide.engine import build_context, decide
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.explain import MARK_AGREE, MARK_CONFLICT, explain
from proofpay.core.models import Allocation, Decision, LedgerTxn, Order, PaymentClaim
from proofpay.core.money import Money
from proofpay.core.reasons import ReasonCode, Risk, Source, Status
from proofpay.core.timex import PKT, ClaimedInstant

MERCHANT = "M-1"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 3, 4, 10, 42, tzinfo=UTC)      # 15:42 PKT
RS_2000 = Money(200_000)
POLICY = DecisionPolicy()

#: The two people in the report. Both distinctive: `Muhammad Ali` sits at the
#: IDF floor by design and would exercise the common-name path instead.
CLAIMED_SENDER = "Zubair Qureshi"
LEDGER_SENDER = "Farhan Bhatti"

REF = "EP19730264"
CLAIMED_AT = ClaimedInstant.from_local(
    datetime(2026, 3, 4, 15, 42), tz=PKT, granularity_s=60
)
#: Hours away from the transaction, and not a whole number of them: far enough
#: that `TS_HOUR_ART` (the AM/PM and time-zone artefact, which is *weak*, not a
#: contradiction) cannot catch it first.
CLAIMED_AT_WRONG = ClaimedInstant.from_local(
    datetime(2026, 3, 4, 11, 7), tz=PKT, granularity_s=60
)


def txn(
    txn_id: str = "TX1001",
    *,
    amount: Money = RS_2000,
    at: datetime = PAID_AT,
    sender: str | None = LEDGER_SENDER,
    ref: str | None = REF,
    source: Source = Source.MERCHANT_LEDGER,
) -> LedgerTxn:
    return LedgerTxn(
        txn_id=txn_id,
        amount=amount,
        occurred_at=at,
        merchant_id=MERCHANT,
        external_id=ref,
        sender_name=sender,
        source=source,
    )


def claim(
    *,
    amount: Money | None = RS_2000,
    ref: str | None = REF,
    sender: str | None = LEDGER_SENDER,
    when: ClaimedInstant | None = CLAIMED_AT,
) -> PaymentClaim:
    return PaymentClaim(
        claim_id="C-1",
        merchant_id=MERCHANT,
        amount=amount,
        reference_id=ref,
        sender_name=sender,
        occurred_at=when,
    )


def order(expected: Money | None = RS_2000) -> Order:
    return Order(order_id="O-1", expected=expected, merchant_id=MERCHANT)


def run(
    the_claim: PaymentClaim,
    the_order: Order | None = None,
    feed: list[LedgerTxn] | None = None,
    allocations: tuple[Allocation, ...] = (),
    *,
    policy: DecisionPolicy = POLICY,
) -> Decision:
    return decide(
        the_claim,
        the_order if the_order is not None else order(),
        feed if feed is not None else [txn()],
        allocations,
        now=NOW,
        policy=policy,
    )


def level_of(decision: Decision, field: str) -> str:
    return decision.evidence_by_field()[field].level_code


# ==========================================================================
# The reported bug, and the same shape on the other two fields
# ==========================================================================

def test_the_reported_bug_no_longer_verifies():
    """Exact reference, exact amount, exact minute, a different sender.

    The one that shipped. Every assertion here is a line of the screen the
    merchant was shown.
    """
    decision = run(claim(sender=CLAIMED_SENDER))

    assert level_of(decision, "reference") == "REF_EXACT"
    assert level_of(decision, "amount") == "AMT_EXACT"
    assert level_of(decision, "timestamp") == "TS_TIGHT"
    assert level_of(decision, "sender_name") == "NAME_ELSE"

    assert decision.status is Status.NEEDS_REVIEW
    assert decision.status is not Status.VERIFIED
    assert decision.fired_rule_id == "R075"
    assert ReasonCode.FIELD_CONTRADICTS_MATCH in decision.reasons
    assert decision.risk is Risk.MEDIUM


def test_the_bug_input_still_scores_above_tau_accept():
    """The premise, asserted so the regression cannot pass for the wrong reason.

    If a future retune drops this claim below `tau_accept`, the test above
    would keep passing while testing nothing at all - `R999` would be catching
    it, not `R075`. The aggregate is still 0.823529 against 0.82; it is the
    rule that refuses it, not the arithmetic.
    """
    ctx = build_context(
        claim(sender=CLAIMED_SENDER), order(), [txn()], (), now=NOW, policy=POLICY
    )
    assert ctx.best_score >= POLICY.tau_accept
    assert ctx.has_contradicting_field is True
    assert [e.field for e in ctx.contradicting_fields] == ["sender_name"]


def test_a_contradicting_reference_does_not_verify():
    """The transaction id printed on the receipt is a different id: not a
    suffix of the real one, not a confusable reading of it, a different id."""
    decision = run(claim(ref="MB77301468"))

    assert level_of(decision, "reference") == "REF_ELSE"
    assert decision.status is Status.NEEDS_REVIEW
    assert decision.fired_rule_id == "R075"
    assert ReasonCode.FIELD_CONTRADICTS_MATCH in decision.reasons


def test_a_contradicting_timestamp_does_not_verify():
    """Both clocks were readable and they do not correspond."""
    decision = run(claim(when=CLAIMED_AT_WRONG))

    assert level_of(decision, "timestamp") == "TS_ELSE"
    assert decision.status is Status.NEEDS_REVIEW
    assert decision.fired_rule_id == "R075"
    assert ReasonCode.FIELD_CONTRADICTS_MATCH in decision.reasons


#: A policy that accepts almost anything. The reference and the timestamp carry
#: enough weight that contradicting one caps the aggregate below the shipped
#: `tau_accept` on its own - so under the default policy those two rows would
#: land in review even without `R075`, and the tests above would not prove the
#: block. Lowering the bar makes every one of them a claim the engine *would*
#: have verified on score, which is the only way to show the rule is doing the
#: work rather than the arithmetic.
PERMISSIVE = replace(POLICY, tau_accept=0.60)


@pytest.mark.parametrize(
    "kwargs,field,level",
    [
        ({"sender": CLAIMED_SENDER}, "sender_name", "NAME_ELSE"),
        ({"ref": "MB77301468"}, "reference", "REF_ELSE"),
        ({"when": CLAIMED_AT_WRONG}, "timestamp", "TS_ELSE"),
        ({"amount": Money(170_000)}, "amount", "AMT_ELSE"),
        ({"amount": Money(2_000_000)}, "amount", "AMT_SCALED"),
    ],
    ids=["name", "reference", "timestamp", "amount", "amount-scaled"],
)
def test_no_contradicting_field_verifies_however_low_the_bar(kwargs, field, level):
    """The block is a rule, not a luckier threshold.

    Each of these clears `PERMISSIVE.tau_accept` comfortably - the assertion
    below says so - and none of them verifies. A retune cannot buy back the
    bug, which is the whole reason this is not a weight change.
    """
    the_claim = claim(**kwargs)
    ctx = build_context(the_claim, order(), [txn()], (), now=NOW, policy=PERMISSIVE)
    assert ctx.best_score >= PERMISSIVE.tau_accept, "fixture no longer clears the bar"

    decision = run(the_claim, policy=PERMISSIVE)
    assert level_of(decision, field) == level
    assert decision.status is not Status.VERIFIED
    assert any(e.contradicts for e in decision.evidence)


def test_a_weakly_agreeing_field_is_not_a_contradiction():
    """The boundary this rule must not cross.

    `NAME_COMMON_ONLY`, `NAME_PARTIAL`, `TS_DATE_ONLY`, `TS_HOUR_ART` and
    `REF_PARTIAL` all describe a field that is *consistent* with the match and
    simply does not pin it down. Treating "weak evidence" as "evidence against"
    would send every date-only receipt and every common name to a human, which
    is the failure mode opposite to the one being fixed - and the demo's own
    case 1 verifies on a `NAME_COMMON_ONLY` row.
    """
    common = "Muhammad Ali"
    decision = run(
        claim(sender=common), order(), [txn(sender=common)]
    )
    assert level_of(decision, "sender_name") == "NAME_COMMON_ONLY"
    assert decision.status is Status.VERIFIED
    assert not any(e.contradicts for e in decision.evidence)


def test_an_unreadable_field_is_not_a_contradiction():
    """Absence of evidence is not evidence of mismatch, and it never was.

    A receipt that never printed a sender name must still be verifiable; the
    aggregate already discounts it for being unreadable, and `R075` must not
    also treat it as a field that argues back.
    """
    decision = run(claim(sender=None))
    assert level_of(decision, "sender_name") == "NAME_MISSING"
    assert decision.evidence_by_field()["sender_name"].agreement is Agreement.MISSING
    assert decision.status is Status.VERIFIED


# ==========================================================================
# Precedence: what must keep outranking the new rule
# ==========================================================================

def test_demo_case_two_still_belongs_to_r030():
    """overview.md section 8, case 2: Rs 5,000 claimed against Rs 500 received.

    `AMT_SCALED` is a contradicting level, so a contradiction rule placed above
    `R030` would take the headline finding of the entire demo and downgrade it
    from "the details do not match" to "a human should look". `R030` sits
    above `R075` precisely so that it cannot.
    """
    decision = run(
        claim(amount=Money(500_000)),
        order(Money(500_000)),
        [txn(amount=Money(50_000))],
    )
    assert level_of(decision, "amount") == "AMT_SCALED"
    assert any(e.contradicts for e in decision.evidence)
    assert decision.fired_rule_id == "R030"
    assert decision.status is Status.SUSPICIOUS
    assert decision.risk is Risk.HIGH


def test_a_reused_transaction_still_belongs_to_r020():
    """overview.md section 8, case 3. The merchant needs to be told about the
    other order first; a disputed field is the lesser finding."""
    decision = run(
        claim(sender=CLAIMED_SENDER),
        order(),
        [txn()],
        (Allocation(txn_id="TX1001", order_id="O-OTHER"),),
    )
    assert any(e.contradicts for e in decision.evidence)
    assert decision.fired_rule_id == "R020"
    assert decision.status is Status.DUPLICATE


# ==========================================================================
# The screen the merchant reads
# ==========================================================================

def explained(the_claim: PaymentClaim, matched: LedgerTxn | None = None):
    decision = run(the_claim)
    return decision, explain(
        decision,
        claim=the_claim,
        txn=matched if matched is not None else txn(),
        order=order(),
    )


def test_the_screen_no_longer_contradicts_itself():
    """The rendered output, end to end.

    A cross on a row and a green verification in the same frame is the artefact
    this whole change exists to remove, so it is asserted on the text a
    merchant actually sees rather than only on the `Decision`.
    """
    _, e = explained(claim(sender=CLAIMED_SENDER))
    text = e.render()

    assert e.status is Status.NEEDS_REVIEW
    assert "PAYMENT VERIFIED" not in text
    assert e.headline == "⚠ MANUAL REVIEW REQUIRED"

    marks = {row.field: row.mark for row in e.rows}
    assert marks["reference"] == MARK_AGREE
    assert marks["amount"] == MARK_AGREE
    assert marks["timestamp"] == MARK_AGREE
    assert marks["sender_name"] == MARK_CONFLICT


def test_the_summary_names_the_field_that_disagrees():
    """"Needs review" on its own sends a shopkeeper back to the table to work
    out what was noticed. The sentence says which row it was."""
    _, e = explained(claim(sender=CLAIMED_SENDER))

    assert "sender name" in e.summary.lower()
    assert "not enough evidence" not in e.summary.lower()
    assert e.recommended_action == (
        "Check this payment yourself before approving the order."
    )


def test_the_summary_does_not_accuse_anybody_of_fraud():
    """A wrong customer, a joint account, a shared phone and an edited
    screenshot all produce this screen. Deciding which is the human's job, and
    the wording must not pre-empt them - nor may it leak a score."""
    _, e = explained(claim(sender=CLAIMED_SENDER))
    lowered = e.render().lower()
    for word in ("fraud", "fake", "forged", "stolen", "%", "probability", "score"):
        assert word not in lowered


def test_the_summary_survives_the_replay_path():
    """`explain` takes `txn` optionally: a caller replaying a stored decision
    holds the `Decision` and may never have re-fetched the ledger row. The
    contradicting field is on the evidence, so the sentence still names it."""
    the_claim = claim(sender=CLAIMED_SENDER)
    decision = run(the_claim)
    replayed = explain(decision, claim=the_claim)

    assert "sender name" in replayed.summary.lower()


def test_more_than_one_contradicting_field_is_listed():
    """Two rows disagree; naming one of them would send the merchant to check
    half the problem."""
    the_claim = claim(sender=CLAIMED_SENDER, ref="MB77301468")
    decision = run(the_claim, policy=PERMISSIVE)
    e = explain(decision, claim=the_claim, txn=txn(), order=order())

    assert {e_.field for e_ in decision.evidence if e_.contradicts} == {
        "reference",
        "sender_name",
    }
    assert "transaction id" in e.summary.lower()
    assert "sender name" in e.summary.lower()
