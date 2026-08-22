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

__all__ = ["RULES", "RULESET_VERSION", "Rule", "total_else"]

#: Pinned alongside the policy fingerprint on every `Decision`. Bump on any
#: change to the table — including a reordering, which changes outcomes.
RULESET_VERSION = "rules-v1.4.0"


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


_validate(RULES)
