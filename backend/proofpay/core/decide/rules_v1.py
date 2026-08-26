"""The rule table: an ordered Python tuple, evaluated first-match.

**No rules DSL.** `business-rules`, `durable_rules`, `pyDMNrules`, GoRules/ZEN,
JSON Logic — all rejected for Phase 1. Their whole value proposition is letting
non-engineers change rules at runtime without a deploy, which is precisely the
opposite of what this layer needs: decisions must be reproducible and
version-pinned. A DSL costs type checking, IDE navigation, stack traces and
property-based coverage, and buys nothing this week. Revisit when a
merchant-ops person needs to edit thresholds in a UI.

**Precedence, in order of importance:**

1. **Structural impossibility first.** `R010`: with no candidates there is
   nothing for any other rule to inspect.
2. **Safety-negative before safety-positive.** `DUPLICATE` and `SUSPICIOUS`
   outrank `VERIFIED`. A table where a high score can pre-empt the duplicate
   check is a money-losing bug.
3. **Specific before general.** The amount-qualified verifications `R070`
   and `R080` sit above the plain `R090`, and the provenance check `R065` sits
   above all three: how much a record is trusted is a question about the
   evidence, and it has to be settled before any rule offers to release goods.
   `R075` joins them for the same reason: a field that *contradicts* the match
   is a question about the evidence too, and one no aggregate score can put:
   three perfect fields carry a fourth that flatly disagrees over `tau_accept`.
   It sits above **both** verifying rules because both must be blocked, and
   below the safety-negative ones because DUPLICATE and SUSPICIOUS are stronger
   answers than "a human should look" and must keep outranking it — demo case 2
   (Rs 5,000 claimed against Rs 500 received) is exactly that: `AMT_SCALED`
   contradicts, and `R030` must still take it.
4. **A total ELSE.** `R999` is non-negotiable, exactly as every `Comparison`
   ends in an ELSE level. It is enforced structurally below, not hoped for.
5. **Rule ids leave gaps** so a rule can be inserted without renumbering, and
   an id never changes meaning: `R030` is `R030` forever, in this table and in
   every decision ever stored. The original table stepped by ten and `R065` is
   the first use of the room that was left; the invariant is the gap, not the
   step.

Rule ids are stable machine identifiers on the same footing as `ReasonCode`.
`note` is human text and may be reworded freely.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from proofpay.core.compare.amount import AmountRelation
from proofpay.core.reasons import ReasonCode, Risk, Status

if TYPE_CHECKING:  # pragma: no cover - import only for the annotation
    from proofpay.core.decide.engine import Context

__all__ = [
    "CONTRADICTION_RULE_ID",
    "RULES",
    "RULESET_VERSION",
    "Rule",
    "total_else",
]

#: The rule that stops a contradicted match from verifying. Named because its
#: *position* is the guarantee, and `_validate` below asserts that position.
CONTRADICTION_RULE_ID = "R075"

#: Pinned alongside the policy fingerprint on every `Decision`. Bump on any
#: change to the table — including a reordering, which changes outcomes.
RULESET_VERSION = "rules-v1.9.0"


def total_else(ctx: Context) -> bool:
    """The unconditional final predicate.

    A named function rather than `lambda c: True` so that "this table is total"
    is checkable by identity at import time, exactly as `levels.always` makes
    every `Comparison` provably total.
    """
    return True


@dataclass(frozen=True, slots=True)
class Rule:
    """One row of the table. First match wins; position *is* precedence."""

    id: str
    when: Callable[[Context], bool]
    status: Status
    risk: Risk
    reasons: tuple[ReasonCode, ...]
    note: str
    #: Did this rule decide by looking at the ranked candidates? Almost every
    #: rule here did — `best_is_allocated_elsewhere`, `material_inflation`,
    #: `best_score >= tau_accept` are all facts about the best candidate — and
    #: `_matched_txn_id` then names that candidate on the decision, which is
    #: what the merchant is shown a record of.
    #:
    #: `R025` is the exception, and the flag exists because leaving it
    #: unmarked was a real defect rather than a tidiness question. Its
    #: predicate is `c.proof_reused`: a fact about the image bytes, decided
    #: without consulting the ranking at all. Naming `ctx.best` on that verdict
    #: hands the merchant a transaction the rule never looked at — measured,
    #: through the live API, as a DUPLICATE screen showing a stranger's Rs 500
    #: payment, a different transaction id and a different sender under the
    #: heading "This payment arrived once", with three CONTRADICT rows the
    #: frontend then rendered as "Only the amount, transaction ID and sender
    #: name were changed": a forgery accusation manufactured entirely by
    #: comparing an honest receipt against an unrelated row.
    #:
    #: A rule that did not look must not point. This is the same principle
    #: `_matched_txn_id` already applies to `ctx.indistinguishable` — do not
    #: name one of several payments the engine could not tell apart — and the
    #: same doctrine one step further back.
    reads_ranking: bool = True


RULES: tuple[Rule, ...] = (
    Rule(
        "R010",
        lambda c: not c.ranking.scored,
        Status.UNMATCHED,
        Risk.MEDIUM,
        (ReasonCode.NO_CANDIDATES,),
        "No merchant transaction plausibly corresponds to this claim.",
    ),
    Rule(
        "R020",
        lambda c: c.best_is_allocated_elsewhere,
        Status.DUPLICATE,
        Risk.HIGH,
        (ReasonCode.TXN_ALREADY_ALLOCATED,),
        "That transaction is already allocated to another order.",
    ),
    # The image sibling of `R020`, and the cheapest payment fraud there is: one
    # screenshot forwarded to two merchants, or sent back to the same one under
    # a new order. `R020` catches it only when the earlier claim left an
    # allocation behind; this catches it from the bytes, which is the half a
    # human is worst at — nobody remembers a receipt they glanced at last week.
    #
    # Placement, both halves deliberate:
    #
    # BELOW `R020`. Both answer DUPLICATE, so the merchant's headline word is
    # the same either way and only the explanation differs — and the more
    # specific explanation should win. `TXN_ALREADY_ALLOCATED` says the money
    # is already spent and names the order that spent it; `PROOF_REUSED` says
    # only that the picture has been seen. Principle 3, applied inside one
    # status. It is also what keeps demo order 1003 (and fixtures D01/D04) on
    # `R020`, where they are pinned.
    #
    # ABOVE `R030`. If a screenshot was reused AND the amount looks inflated,
    # the merchant should be told it was reused: reuse is a certain fact about
    # bytes, while material inflation is arithmetic over OCR output, which is
    # the layer that can be wrong. Principle 2 already puts the allocation
    # DUPLICATE above SUSPICIOUS and there is no argument for treating the image
    # case differently. No fixture forces this — D02 and D03 are both
    # CLAIM_CONSISTENT — so it is a consistency call, recorded as one.
    #
    # NOT above `R010`, which is the one real cost. A reused image whose
    # transaction has aged out of the retrieval window reports UNMATCHED rather
    # than DUPLICATE, because principle 1 says an empty ranking is answered
    # structurally before anything else is inspected. Accepted rather than
    # overlooked: no fixture reaches that state, and inverting principle 1 for
    # one rule is a larger change than the case is worth.
    Rule(
        "R025",
        lambda c: c.proof_reused,
        Status.DUPLICATE,
        Risk.HIGH,
        (ReasonCode.PROOF_REUSED,),
        "This exact screenshot was already accepted for another order.",
        reads_ranking=False,
    ),
    Rule(
        "R030",
        lambda c: c.material_inflation,
        Status.SUSPICIOUS,
        Risk.HIGH,
        (ReasonCode.CLAIM_INFLATED,),
        "The screenshot claims materially more than was received.",
    ),
    Rule(
        "R040",
        lambda c: c.tamper_count > c.policy.tamper_signal_limit
        and c.best_score < c.policy.tau_accept,
        Status.SUSPICIOUS,
        Risk.HIGH,
        (ReasonCode.TAMPER_OBSERVATIONS,),
        "Image observations plus a weak field match.",
    ),
    # Ambiguity is a statement about *indistinguishability*, not about strength.
    # Two plausible candidates nobody can tell apart are ambiguous whether or
    # not either one clears `tau_accept`, and the earlier `>= tau_accept` form
    # made this rule almost unreachable: a receipt with no printed TID is capped
    # near 0.9 before scoring starts, and two interchangeable rows drive their
    # own shared sender name to the IDF floor, so the demo's twin Rs 250
    # payments landed at 0.72 and fell through to `R999` — which named one of
    # them. The floor is therefore plausibility (`tau_ambiguous`), not
    # acceptance. See `Context.ambiguous`.
    Rule(
        "R050",
        lambda c: c.ambiguous,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (ReasonCode.AMBIGUOUS_CANDIDATES,),
        "Two or more transactions match about equally well.",
    ),
    Rule(
        "R060",
        lambda c: c.best_score < c.policy.tau_reject,
        Status.UNMATCHED,
        Risk.MEDIUM,
        (ReasonCode.NAME_MISMATCH,),
        "No transaction matched strongly enough.",
    ),
    # Trust is a rule, not a crash. `Source` documents merchant CSV imports and
    # hand-keyed rows as real but partially trusted feeds, and no rule used to
    # inspect `txn.source` at all — so a perfect match against one returned
    # VERIFIED and the post-condition assertion then killed the verification
    # outright. A merchant who imports by CSV could get no answer at all. This
    # routes that match to a human instead, and leaves the assertion as the
    # backstop it was meant to be: it still fires, and must, for
    # `CUSTOMER_SCREENSHOT`, which is not evidence of anything.
    Rule(
        "R065",
        lambda c: c.best_score >= c.policy.tau_accept and c.best_partially_trusted,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (ReasonCode.SOURCE_PARTIALLY_TRUSTED,),
        "The matching record was imported or keyed in by hand, not fed by a ledger.",
    ),
    # The claim-side twin of `R065`, and it exists for the reason `R065`'s
    # comment already gives: how far the evidence can be trusted is a question
    # that has to be settled before any rule offers to release goods. `R065`
    # asks it of the LEDGER row -- a CSV import is a real record and not a
    # ledger-grade one. This asks it of the RECEIPT: a reader that says it is
    # unsure of the amount it read has not produced a number anybody should
    # release stock against, however neatly that number happens to agree.
    #
    # Below `R065` because a record that cannot be trusted is the stronger
    # objection: it is a fact about the merchant's own feed, while this is a
    # fact about our reader. Above `R070`-`R080` because a doubted field is a
    # question about the evidence and those are questions about the money, and
    # `R075` for the same reason `R065` sits above it.
    #
    # The `>= tau_accept` guard mirrors `R065` exactly. Below acceptance the
    # claim already has a better answer -- `R050`, `R060` or `R999` -- and
    # re-routing it here would replace a specific finding with a vaguer one.
    #
    # HONEST LIMITATION, and it is not a small one: this rule cannot fire on
    # the offline path. `extraction/stub.py` is a SHA-256 manifest lookup that
    # never inspects pixels, so it reports no field evidence, so
    # `service._normalise` leaves `field_confidences` empty and
    # `confidence_for` returns the fully-confident default for every field.
    # The rule is correct for the Qwen-VL path and unreachable without it. That
    # is recorded here, in `DecisionPolicy.min_field_confidence`, in the
    # `LOW_EXTRACTION_CONFIDENCE` comment, and in the manifest harness pins for
    # N04/N05/N06 -- four places, because the tempting fix is to fake a
    # confidence into a fixture and watch a test go green.
    Rule(
        "R067",
        lambda c: c.best_score >= c.policy.tau_accept and c.has_low_confidence_field,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (ReasonCode.LOW_EXTRACTION_CONFIDENCE,),
        "Matched, but the reader was unsure of a field this match depends on.",
    ),
    Rule(
        "R070",
        lambda c: c.best_score >= c.policy.tau_accept
        and c.amount.relation is AmountRelation.UNDER
        and not c.amount.within_tolerance,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (ReasonCode.AMOUNT_UNDERPAID,),
        "Matched, but less than the order total was received.",
    ),
    # The commercial mirror of `R070`, and the answer to a question the fixture
    # corpus asked in two contradictory voices: G05 (+33% over a Rs 1,500
    # order) expects VERIFIED, N02 (+233% over the same order) expects review.
    # Both carry AMOUNT_OVERPAID, so the difference between them is magnitude
    # and nothing else, and a magnitude question is answered by a threshold in
    # `DecisionPolicy` rather than by picking one fixture over the other.
    #
    # Rs 200 more than the order asked for is a customer rounding up or adding
    # delivery money, and stopping the order to fetch a human costs more than
    # the Rs 200. Three times the order total is a mis-typed digit or another
    # order's money, and somebody will come back for it.
    #
    # Placement mirrors `R070` exactly: UNDER and OVER are exclusive, so the two
    # can never both fire, and both sit above `R075` so that money keeps leading
    # the explanation (see the comment in `core/explain.py:_summary`). It
    # shadows `R080` by first match, exactly as `R070` shadows `R090` — `R080`
    # needs no `and not ...` guard, and adding one would only duplicate the
    # ordering the table already states.
    Rule(
        "R072",
        lambda c: c.best_score >= c.policy.tau_accept and c.material_overpayment,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (ReasonCode.AMOUNT_OVERPAID_MATERIAL,),
        "Matched, but far more than the order total was received.",
    ),
    # A field that contradicts the match. Not a score problem: a claim carrying
    # the right transaction id, the right amount and the right time, under a
    # completely different sender name, scored 0.823529 against a `tau_accept`
    # of 0.82 and verified — handing the merchant a screen that read PAYMENT
    # VERIFIED above a red ✗ on the sender row. Weighting the name harder does
    # not fix that; it just moves which combination of three-good-one-bad slips
    # through. Contradiction is categorical, so it is a rule.
    #
    # Placement is the whole design. Above `R080` and `R090` because *both*
    # verifications must be blocked. Below `R020`/`R030` because a reused
    # transaction and an inflated claim are more specific and more serious
    # findings than "a human should look", and this rule must never soften one:
    # `AMT_SCALED` contradicts, so an unplaced version of this rule would steal
    # demo case 2 away from SUSPICIOUS. Below `R040`-`R070` for the same reason
    # — each of those already names the specific thing that is wrong.
    Rule(
        "R075",
        lambda c: c.has_contradicting_field,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (ReasonCode.FIELD_CONTRADICTS_MATCH,),
        "A field on the receipt actively contradicts the transaction it matched.",
    ),
    Rule(
        "R080",
        lambda c: c.best_score >= c.policy.tau_accept
        and c.amount.relation is AmountRelation.OVER,
        Status.VERIFIED,
        Risk.LOW,
        (ReasonCode.AMOUNT_OVERPAID, ReasonCode.STRONG_FIELD_AGREEMENT),
        "Matched; more than the order total was received.",
    ),
    Rule(
        "R090",
        lambda c: c.best_score >= c.policy.tau_accept,
        Status.VERIFIED,
        Risk.LOW,
        (ReasonCode.STRONG_FIELD_AGREEMENT,),
        "A merchant transaction matches this claim on all key fields.",
    ),
    Rule(
        "R999",
        total_else,
        Status.NEEDS_REVIEW,
        Risk.MEDIUM,
        (),
        "Insufficient evidence to decide.",
    ),
)


def _validate(rules: tuple[Rule, ...]) -> None:
    """Structural guarantees, checked once at import.

    Totality is the important one: a rule table that can fall off the end
    leaves a verification with no outcome and no audit row, which is the worst
    failure mode this layer has. It is a construction-time error here rather
    than a runtime surprise on a demo.
    """
    if not rules:
        raise ValueError("the rule table must not be empty")
    ids = [r.id for r in rules]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate rule id in {ids}")
    if ids != sorted(ids):
        raise ValueError(f"rule ids must be listed in ascending order, got {ids}")
    if rules[-1].when is not total_else:
        raise ValueError(
            f"the last rule ({rules[-1].id}) must be the total ELSE — "
            "pass `total_else` as its predicate"
        )
    for rule in rules[:-1]:
        if rule.when is total_else:
            raise ValueError(f"{rule.id} is unconditional but is not the last rule")
    if any(r.status is Status.VERIFIED and not r.reasons for r in rules):
        # A VERIFIED decision with no reason code cannot be explained to the
        # merchant it is telling to hand over goods.
        raise ValueError("a VERIFIED rule must carry at least one reason code")
    _validate_contradiction_precedes_verification(rules)


def _validate_contradiction_precedes_verification(rules: tuple[Rule, ...]) -> None:
    """The contradiction rule outranks every rule that can verify.

    Checked structurally rather than left to the reader's eye on the table,
    because the failure it prevents is silent: reorder `R075` below `R090` and
    every test still passes except the handful that happen to build a
    contradicting field, while the product goes back to showing PAYMENT
    VERIFIED above a red cross. Position is precedence, so position is an
    invariant worth asserting.
    """
    ids = [r.id for r in rules]
    if CONTRADICTION_RULE_ID not in ids:
        raise ValueError(f"the contradiction rule {CONTRADICTION_RULE_ID} has been removed")
    blocker = ids.index(CONTRADICTION_RULE_ID)
    above = [r.id for r in rules[:blocker] if r.status is Status.VERIFIED]
    if above:
        raise ValueError(
            f"{above} can verify but sit above {CONTRADICTION_RULE_ID}; a field "
            "that contradicts the match would no longer block verification"
        )


_validate(RULES)
