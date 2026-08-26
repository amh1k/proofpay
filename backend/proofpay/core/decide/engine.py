"""The decision engine: retrieve, score, rank, rule, assert.

One entry point, `decide(...)`, and a strict pipeline behind it:

1. **Retrieve** a bounded candidate set with cheap blocking keys.
2. **Score** every candidate by running each field `Comparison` against it,
   producing a `FieldOutcome` per field — the rows the merchant will read.
3. **Rank** them in a total, reproducible order and measure the margin.
4. **Gather** the non-field evidence: amount semantics, allocation conflicts,
   image observations.
5. **Rule**: first match in `RULES` wins.
6. **Assert** the invariants, then return.

Three properties are load-bearing:

* **No clock.** `now` is a required keyword argument. Nothing here reads the
  wall clock, which is what lets a stored decision be replayed identically a
  year later from its inputs, ruleset version and policy fingerprint.
* **No thresholds.** Every number that steers an outcome lives in
  `DecisionPolicy` - cut-points and field weights alike, so that a decision's
  policy fingerprint really does pin down how it was taken. The only float
  literals left in this module are the coefficients of the published
  confidence formula, which decide nothing: no value is accepted or rejected
  by comparing against them.
* **Determinism.** Ranking, evidence order, reason order and observation order
  are all functions of the data alone, never of dict or input ordering.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from proofpay.core.compare.amount import (
    AmountEvidence,
    AmountRelation,
    ClaimIntegrity,
    compare_amounts,
)
from proofpay.core.compare.amount_match import AMOUNT_MATCH, compare_amount_match
from proofpay.core.compare.levels import Agreement, Comparison, FieldOutcome
from proofpay.core.compare.name import (
    build_name_idf,
    compare_name,
    name_comparison,
    name_observations,
)
from proofpay.core.compare.reference import REFERENCE, compare_reference
from proofpay.core.compare.timestamp import (
    TIMESTAMP,
    TimestampParams,
    compare_timestamp,
    timestamp_observations,
)
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.decide.rules_v1 import RULES, RULESET_VERSION, Rule
from proofpay.core.duplicates import (
    AllocationIndex,
    DuplicateReport,
    check_ranking,
    index_allocations,
)
from proofpay.core.models import (
    Allocation,
    Decision,
    LedgerTxn,
    Order,
    PaymentClaim,
    ProofFingerprint,
    ScoredCandidate,
)
from proofpay.core.normalize import normalize_name
from proofpay.core.proofs import ProofIndex, ProofReport, check_proof, index_proofs
from proofpay.core.reasons import (
    PARTIALLY_TRUSTED_SOURCES,
    TRUSTED_LEDGER_SOURCES,
    ObservationCode,
    ReasonCode,
    Status,
)
from proofpay.core.retrieval import CandidateRanking, RetrievalResult, TxnIndex, retrieve

__all__ = [
    "COMPARISONS",
    "CONFIDENCE_KEYS",
    "ENGINE_VERSION",
    "SENDER_NAME",
    "TAMPER_OBSERVATION_CODES",
    "Context",
    "aggregate_score",
    "confidence",
    "decide",
    "doubted_fields",
    "first_match",
    "score_candidate",
    "scoring_idf",
]

#: Stamped on every `Decision` beside the ruleset version and policy
#: fingerprint. Bump when the pipeline's behaviour changes, not when a
#: docstring does.
ENGINE_VERSION: Final[str] = "engine-1.2.0"

#: A transliterated Pakistani name is the weakest of the four signals - real
#: customers share `Muhammad Ali`, receipts mask it, and OCR mangles it - so it
#: contributes less weight than a transaction id or an amount. *How much* less
#: is `DecisionPolicy.w_sender_name` rather than a constant here: a field
#: weight steers every aggregate it feeds, so it belongs to the fingerprint.
#: This object owns the ladder, not the field's importance.
SENDER_NAME: Final[Comparison] = name_comparison("sender_name")

#: The fields scored for every candidate, and the source of the weights in the
#: aggregate. `receiver_name` is deliberately absent: it is the merchant's own
#: name on every transaction in the feed, so it cannot help choose *between*
#: candidates and would only dilute the fields that can.
COMPARISONS: Final[tuple[Comparison, ...]] = (
    REFERENCE,
    AMOUNT_MATCH,
    TIMESTAMP,
    SENDER_NAME,
)

#: Which keys of `PaymentClaim.field_confidences` speak for each scored field.
#:
#: `Comparison.field` is `core`'s own vocabulary and an extractor reports under
#: the names it read off the receipt; the two were never negotiated, and this
#: map is where that goes on the record instead of being discovered by a rule
#: that silently never fires. MEASURED against the only extractor that reports
#: confidences at all (`extraction/dashscope_ocr._build_field_evidence`), whose
#: keys are `reference_id, amount, currency, sender_name, receiver_name,
#: receiver_account, timestamp, status, provider`: three of the four scored
#: fields already agree by name, and `reference` alone does not.
#:
#: The map is also the *filter*, not just a translation. `currency`, `status`
#: and `provider` are read off the same receipt and are absent here on purpose:
#: a field no comparison scored contributed nothing to the match, so a shaky
#: reading of it is not a reason to stop an order. Only evidence the verdict
#: actually rests on may hold the verdict up.
CONFIDENCE_KEYS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        REFERENCE.field: ("reference", "reference_id"),
        AMOUNT_MATCH.field: ("amount",),
        TIMESTAMP.field: ("timestamp",),
        SENDER_NAME.field: ("sender_name",),
    }
)

#: Observations that count as *image tamper* signals for `R040`. Parsing notes
#: (an ambiguous thousands separator, a folded Arabic-Indic digit) are honest
#: observations too, but they say something about our reader, not about the
#: image, and must never accumulate toward an accusation.
TAMPER_OBSERVATION_CODES: Final[frozenset[str]] = frozenset(
    {
        ObservationCode.IMAGE_EXIF_MISSING,
        ObservationCode.IMAGE_EDITOR_SIGNATURE,
        ObservationCode.IMAGE_ELA_ANOMALY,
        ObservationCode.IMAGE_RECOMPRESSED,
    }
)

#: What the amount axes say when there is no ledger row to compare against.
#: Every field is UNKNOWN rather than zero: with no transaction there is no
#: shortfall of nothing, and `within_tolerance=True` keeps the underpayment
#: rule from firing on a comparison that never happened.
NO_AMOUNT_EVIDENCE: Final[AmountEvidence] = AmountEvidence(
    relation=AmountRelation.UNKNOWN,
    integrity=ClaimIntegrity.UNKNOWN,
    shortfall=None,
    inflation=None,
    within_tolerance=True,
    material_inflation=False,
    observations=(),
)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_candidate(
    claim: PaymentClaim,
    txn: LedgerTxn,
    *,
    idf: Mapping[str, float],
    policy: DecisionPolicy,
    ts_params: TimestampParams | None = None,
) -> ScoredCandidate:
    """Run every field comparison against one candidate.

    The `FieldOutcome`s are the whole explanation: each one is a labelled row
    with the metrics it fired on, so nothing downstream has to reverse-engineer
    prose out of a float.
    """
    params = ts_params if ts_params is not None else policy.timestamp_params()
    outcomes: dict[str, FieldOutcome] = {
        REFERENCE.field: compare_reference(
            claim.reference_id,
            txn.reference_id,
            min_partial_len=policy.ref_min_partial_len,
        ),
        AMOUNT_MATCH.field: compare_amount_match(
            claim.amount, txn.amount, tolerance_minor=policy.amount_tolerance_minor
        ),
        TIMESTAMP.field: compare_timestamp(claim.occurred_at, txn.occurred_at, params),
        SENDER_NAME.field: compare_name(
            claim.sender_name,
            txn.sender_name,
            idf=idf,
            thresholds=policy.name_thresholds(),
            comparison=SENDER_NAME,
        ),
    }
    return ScoredCandidate(
        txn=txn,
        score=aggregate_score(outcomes, policy),
        outcomes=outcomes,
    )


def aggregate_score(
    outcomes: Mapping[str, FieldOutcome],
    policy: DecisionPolicy,
    comparisons: Sequence[Comparison] = COMPARISONS,
) -> float:
    """Weighted mean of the field scores, with unreadable fields discounted.

    The subtlety is what to do with a field OCR could not read at all, and both
    obvious answers are wrong:

    * Scoring a missing field as 0 treats *absence of evidence* as evidence of
      mismatch. A perfectly good receipt that never printed a transaction id
      would then be capped below `tau_accept` and could never be verified.
    * Excluding it entirely makes a claim carrying nothing but a legible name
      score 1.0 on that name alone, which is precisely the screenshot-only
      verification this system exists to refuse.

    So a missing field is excluded from the numerator but keeps a fraction
    ``p = policy.missing_evidence_penalty`` of its weight in the denominator:
    it never argues against a candidate, but the more of the receipt we could
    not read, the harder it is to reach acceptance. An otherwise-perfect match
    still survives one unread field, and a name-only claim still lands in
    review rather than in VERIFIED.

    **The invariant, and why `p` is not a free knob.** Removing evidence must
    never *raise* a claim's aggregate. Cropping the sender's name off a receipt
    has to make the receipt worse, or a fraud product is rewarding the crop.
    Replacing a present outcome of weight ``w`` and score ``s`` with a MISSING
    one takes ``N/D`` to ``(N - ws) / (D - w(1 - p))``, and that is no larger
    than ``N/D`` exactly when ``s >= (N/D)(1 - p)``. Since the aggregate is
    itself bounded by 1, ``s >= 1 - p`` guarantees it for every possible set of
    sibling fields — which is the guarantee, because it holds whatever else is
    on the receipt.

    At ``p = 0.50`` that covers every AGREE and WEAK rung of every ladder except
    ``NAME_COMMON_ONLY`` (0.20) and ``TS_HOUR_ART`` (0.25).
    ``tests/core/test_properties.py`` enumerates the ladders against this bound
    and pins those two by name in ``KNOWN_ABSENCE_EXPOSURES``, so lowering a
    level score, or lowering ``p`` back, fails there rather than silently
    reopening the hole.

    **The CONTRADICT rungs are a different story, and it is an open one.** A
    contradicted field scores 0, so ``s >= 1 - p`` needs ``p = 1`` -- and
    ``p = 1`` *is* "score a missing field as a mismatch", the first of the two
    wrong answers at the top of this docstring, which
    ``test_an_unreadable_field_never_argues_against_a_candidate`` forbids
    outright. The two properties are therefore in genuine tension: **no value of
    ``p`` satisfies both.** Hiding a contradicted field really does help a
    claim, and it helps it twice over, because it also removes the ``R075``
    block that a contradiction would have put in front of the verification.
    Measured through ``decide()``: a claim agreeing exactly on reference, amount
    and time, under a sender name that flatly contradicts the transaction,
    answers NEEDS_REVIEW / ``R075`` at an aggregate of 0.8235; blank that same
    name and it answers VERIFIED / ``R090`` at 0.9032.

    This is not closable by tuning, and it is not hidden: it is pinned in
    ``KNOWN_VERDICT_EXPOSURES`` in ``tests/core/test_properties.py`` with a test
    that walks it through the real engine, so it fails the day somebody closes
    it and the pin has to be deleted rather than left there reassuring people.
    Closing it means a rule -- the missing-field sibling of ``R075`` -- and that
    rule would overturn two labelled scenarios asserting that a receipt which
    never printed a field can still verify. That is a product decision, not a
    tuning one; see ``DecisionPolicy.missing_evidence_penalty``.

    Weights come from `policy.field_weights()`, falling back to a comparison's
    own declared weight only for a field the policy has never heard of. A
    weight steers every aggregate it feeds - halving the name weight moves
    scores across `tau_accept` - so it is fingerprinted like any other
    tunable number.

    Rounded, so that two candidates that genuinely tie compare equal rather
    than differing in the last bit and manufacturing a fake margin.
    """
    policy_weights = policy.field_weights()
    weights = {c.field: policy_weights.get(c.field, c.weight) for c in comparisons}
    numerator = 0.0
    present_w = 0.0
    missing_w = 0.0
    for field, outcome in outcomes.items():
        weight = weights.get(field, 1.0)
        if outcome.is_missing:
            missing_w += weight
        else:
            present_w += weight
            numerator += weight * outcome.score

    denominator = present_w + policy.missing_evidence_penalty * missing_w
    if denominator <= 0.0:
        return 0.0
    return round(numerator / denominator, 6)


# ---------------------------------------------------------------------------
# The object the rule predicates read
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class Context:
    """Everything a rule may inspect, and nothing it may change.

    Rules are pure predicates over this object. Keeping the derived quantities
    here — rather than recomputing them inside lambdas — means the rule table
    reads as a table, and every number a rule fired on is available afterwards
    for the audit trail.
    """

    claim: PaymentClaim
    order: Order | None
    policy: DecisionPolicy
    now: datetime

    ranking: CandidateRanking
    retrieval: RetrievalResult
    amount: AmountEvidence
    #: Whether `amount` describes a real comparison. False when there was no
    #: candidate credible enough to compare against — see `build_context`.
    amount_compared: bool
    duplicates: DuplicateReport
    #: What this merchant's proof history says about the submitted image. The
    #: image sibling of `duplicates`, and empty whenever the caller passed no
    #: history or the claim carries no content hash.
    proofs: ProofReport
    #: Scored fields the extractor reported low confidence in. `R067`'s
    #: evidence. Kept as the field names rather than as a bare flag for the same
    #: reason `contradicting_fields` is: the audit trail should record *which*
    #: field the reader doubted, and a boolean throws that away at the one
    #: moment somebody would want it.
    low_confidence_fields: tuple[str, ...]
    observations: tuple[str, ...]

    @property
    def best(self) -> ScoredCandidate | None:
        return self.ranking.best

    @property
    def best_score(self) -> float:
        """The winner's aggregate score, or 0.0 when there is no winner.

        `R010` guarantees no later rule is ever evaluated on an empty ranking,
        so this is defence in depth: a None dereference inside a rule lambda
        would turn a benign "no candidates" case into a crashed verification.
        """
        best = self.ranking.best
        return best.score if best is not None else 0.0

    @property
    def dominant(self) -> bool:
        """Exactly one candidate matched the transaction id exactly.

        The margin rule protects against *interchangeable* candidates; a unique
        printed TID means they are not interchangeable, so such a match may win
        regardless of margin.
        """
        return self.ranking.is_dominant

    @property
    def indistinguishable(self) -> bool:
        """Two or more candidates this ranking cannot tell apart.

        A property of the *ranking*, deliberately not of whichever rule happened
        to fire. Which transaction a decision names has to follow from whether
        the ranking could separate them, because that is the fact the caller
        acts on: hand back one of two interchangeable payments and it gets
        allocated, whatever status came with it. Keying the suppression off
        `R050`'s reason codes instead meant that any fall-through - `R999`
        carries no reasons at all - leaked one arbitrary winner.
        """
        return (
            len(self.ranking.scored) >= 2
            and self.ranking.margin < self.policy.tau_margin
            and not self.dominant
        )

    @property
    def ambiguous(self) -> bool:
        """Indistinguishable *and* plausible enough to be worth saying so.

        `R050`'s predicate. The floor is `tau_ambiguous`, not `tau_accept`:
        ambiguity is about indistinguishability, not strength, and two
        candidates that cannot be told apart are ambiguous whether or not either
        clears the acceptance bar. Below the floor there is no credible
        candidate to be confused about, and `R060` has the honest answer.
        """
        return self.indistinguishable and self.best_score >= self.policy.tau_ambiguous

    @property
    def best_partially_trusted(self) -> bool:
        """The winner is a real merchant record, but not a ledger-grade one.

        A CSV import or a hand-keyed row is evidence worth matching against and
        not evidence enough to release goods on, so `R065` routes it to a human
        instead of letting the post-condition assertion kill the verification.
        """
        best = self.ranking.best
        return best is not None and best.txn.source in PARTIALLY_TRUSTED_SOURCES

    @property
    def material_inflation(self) -> bool:
        return self.amount.material_inflation

    @property
    def material_overpayment(self) -> bool:
        """Far more arrived than the order asked for. `R072`'s predicate.

        Computed in `compare_amounts` from `overpayment_material_minor` and
        `overpayment_material_pct`, so the cut-point is in the policy
        fingerprint rather than in a lambda in the rule table.
        """
        return self.amount.material_overpayment

    @property
    def best_is_allocated_elsewhere(self) -> bool:
        return self.duplicates.best_is_allocated_elsewhere

    @property
    def proof_reused(self) -> bool:
        """This exact image was already accepted for another order. `R025`.

        A fact about bytes rather than about the ranking, which is why it is
        the one duplicate signal that does not read `self.ranking` at all — and
        why `R025` sits where it does in the table. See `core/proofs.py`.
        """
        return self.proofs.is_reused

    @property
    def tamper_count(self) -> int:
        """How many *image* observations were reported. Never a verdict."""
        return sum(1 for o in self.observations if o in TAMPER_OBSERVATION_CODES)

    @property
    def evidence(self) -> tuple[FieldOutcome, ...]:
        best = self.ranking.best
        return best.evidence if best is not None else ()

    @property
    def contradicting_fields(self) -> tuple[FieldOutcome, ...]:
        """Winner's fields that were readable on both sides and disagree.

        The direction is `Level.agreement`, declared beside the comparison rung
        itself, so this reads the semantic classification rather than
        re-deriving one from scores or from level codes spelled out here. A
        field that could not be read is `Agreement.MISSING` and is deliberately
        not in this tuple: absence of evidence is not evidence of mismatch.
        """
        return tuple(e for e in self.evidence if e.agreement is Agreement.CONTRADICT)

    @property
    def has_contradicting_field(self) -> bool:
        """`R075`'s predicate: some field actively argues against this match.

        A screen reading `✓ Transaction ID  ✓ Amount  ✓ Timestamp  ✗ Sender
        name` above the words PAYMENT VERIFIED is self-contradictory, and a
        merchant cannot act on it. The aggregate score cannot express this on
        its own — three perfect fields carry a fourth that flatly disagrees over
        `tau_accept` — so it is a rule, not a threshold.
        """
        return bool(self.contradicting_fields)

    @property
    def has_low_confidence_field(self) -> bool:
        """`R067`'s predicate: a field this match rests on was read badly.

        The claim-side twin of `best_partially_trusted`. That property asks how
        much the *ledger* row can be trusted; this one asks the same question of
        the *receipt*, and both have to be settled before any rule offers to
        release goods. Distinct from `has_contradicting_field`: a contradicted
        field was read clearly and disagrees, while this one may well agree —
        the reader simply is not sure it read it.

        Not expressible as a score. Discounting a doubted field in the aggregate
        would make it behave like an absent one, and absence is already spoken
        for by `missing_evidence_penalty`; "read, but not confidently" is a
        third state, and the honest answer to it is a person.
        """
        return bool(self.low_confidence_fields)


def first_match(ctx: Context, rules: Sequence[Rule] = RULES) -> Rule:
    """First rule whose predicate holds. Position is precedence.

    The table is validated total at import, so the trailing raise is
    unreachable in practice and exists so that a hand-built table missing its
    ELSE fails loudly instead of returning `None` into a `Decision`.
    """
    for rule in rules:
        if rule.when(ctx):
            return rule
    raise AssertionError("rule table is not total — the last rule must be `total_else`")


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def confidence(
    ranking: CandidateRanking,
    evidence: Sequence[FieldOutcome],
    policy: DecisionPolicy,
) -> float:
    """Confidence in **this decision**, never a probability of fraud.

    Three ingredients, published so a merchant disputing a number can derive
    it (guide 7.6):

    * half the winner's aggregate score — how well the best candidate fits;
    * three tenths the margin, clipped at one `tau_margin` — how separable the
      winner is from the runner-up;
    * two tenths the evidence coverage — how much of the receipt we could read.

    The coefficients are the formula's, not thresholds: nothing is accepted or
    rejected by comparing against them. A number nobody can derive is worse
    than no number, which is why this stays four lines long.
    """
    coverage = (
        sum(1 for e in evidence if not e.is_missing) / len(evidence) if evidence else 0.0
    )
    best = ranking.best
    best_score = best.score if best is not None else 0.0
    m = min(1.0, ranking.margin / max(policy.tau_margin, 1e-9))
    return round(min(1.0, 0.5 * best_score + 0.3 * m + 0.2 * coverage), 3)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def _enforce_invariants(decision: Decision, ctx: Context) -> Decision:
    """> No screenshot-derived signal may alone establish that payment occurred.

    A post-condition assertion rather than a property of rule ordering we hope
    holds. Rule tables get reordered; this does not care. It runs on every
    decision before it leaves the engine, and it raises `AssertionError`
    because a violation is a bug in this module, not bad input.
    """
    if decision.status is not Status.VERIFIED:
        return decision
    if ctx.best is None:
        raise AssertionError("VERIFIED without a ledger transaction")
    if ctx.best.txn.source not in TRUSTED_LEDGER_SOURCES:
        raise AssertionError(
            f"VERIFIED from non-ledger evidence: {ctx.best.txn.source}"
        )
    if decision.matched_txn_id != ctx.best.txn_id:
        raise AssertionError(
            f"VERIFIED names {decision.matched_txn_id!r} but the winner is "
            f"{ctx.best.txn_id!r}"
        )
    # > A field that actively contradicts the match must block VERIFIED.
    #
    # `R075` is what implements that, and this is the backstop that says so
    # whatever the table looks like tomorrow, exactly as the source check above
    # backstops `R065`. A merchant shown PAYMENT VERIFIED above a red ✗ on the
    # sender row has been handed a self-contradictory screen, and no reordering
    # of the table is allowed to produce one.
    contradicting = ctx.contradicting_fields
    if contradicting:
        raise AssertionError(
            "VERIFIED with a contradicting field: "
            + ", ".join(f"{e.field}={e.level_code}" for e in contradicting)
        )
    return decision


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    """Order-preserving de-duplication. Order is meaning here: the rule's own
    reasons come first, then what the arithmetic adds."""
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(str(item), None)
    return tuple(seen)


def _reasons_for(rule: Rule, ctx: Context) -> tuple[ReasonCode, ...]:
    """The rule's reasons, plus the ones that follow from the amounts alone.

    Amount codes are only appended when the amounts were actually compared:
    with no credible transaction there is nothing to have been underpaid or
    over-claimed, and `MISSING_ORDER_AMOUNT` on an UNMATCHED claim would be
    noise dressed as a finding.
    """
    codes: list[ReasonCode] = list(rule.reasons)
    if ctx.amount_compared:
        codes.extend(ctx.amount.reason_codes)
    return tuple(ReasonCode(c) for c in _dedupe(codes))


def _observations_for(ctx: Context) -> tuple[str, ...]:
    """Image observations, parser notes and comparison notes, in a stable order.

    Observations are never a verdict. They record what had to be assumed and
    what was noticed, so that a borderline case can be pushed to review with a
    specific, auditable justification rather than a hunch.
    """
    notes: list[str] = list(ctx.observations)
    notes.extend(ctx.claim.notes)
    notes.extend(ctx.amount.observations)
    # Which earlier order this image already paid. Emitted whenever the history
    # says so, not only when `R025` is the rule that fired: when a reused proof
    # ALSO points at an allocated transaction, `R020` wins the verdict and the
    # merchant is owed both facts. Never a verdict on its own — see
    # `ObservationCode.PROOF_PREVIOUSLY_SUBMITTED`.
    notes.extend(ctx.proofs.observations)
    best = ctx.best
    if best is not None:
        ts = best.outcomes.get(TIMESTAMP.field)
        if ts is not None:
            notes.extend(timestamp_observations(ts))
        name = best.outcomes.get(SENDER_NAME.field)
        if name is not None:
            notes.extend(name_observations(name.detail))
    return _dedupe(notes)


def _matched_txn_id(rule: Rule, ctx: Context) -> str | None:
    """Which transaction, if any, this decision names.

    Nothing is named when the claim is UNMATCHED (there is no match to name) or
    when the ranking could not separate its candidates - naming one of several
    interchangeable payments is the exact bug `R050` exists to prevent, and
    doing it in the payload hands the caller a transaction to allocate anyway.

    The second test is `ctx.indistinguishable`, a fact about the *ranking*, and
    not "did the rule that fired carry AMBIGUOUS_CANDIDATES". That earlier form
    was only ever as good as the rule table's coverage of ambiguity: a tie that
    fell through to `R999` - which carries no reason codes at all - named one
    arbitrary winner out of two identical payments.

    The third is `Rule.reads_ranking`, and it is that doctrine one step further
    back: a rule that reached its verdict without looking at the candidates must
    not point at one. `R025` decides on the image bytes alone, and the best
    candidate for THIS order can contradict the receipt on every field - so
    naming it produced a DUPLICATE screen describing a stranger's payment as the
    payment behind the receipt. See the flag's comment in `rules_v1.py`.
    """
    if ctx.best is None:
        return None
    if rule.status is Status.UNMATCHED:
        return None
    if ctx.indistinguishable:
        return None
    if not rule.reads_ranking:
        return None
    return ctx.best.txn_id


def scoring_idf(index: TxnIndex, policy: DecisionPolicy) -> Mapping[str, float]:
    """Term weights for *scoring* names, which are not the blocking weights.

    `TxnIndex.idf` answers "which token should this name be blocked on?" — a
    relative question, where every token of a three-transaction feed sitting at
    the floor is harmless. Scoring asks an absolute question: "how much
    evidence is agreement on this token worth?" On a cold feed the honest
    answer for a distinctive surname is *a lot*, and `build_name_idf` gives
    exactly that by falling back to the static common-name list rather than
    inventing document frequencies from one document.

    Recomputed per verification. A caller verifying a batch against one feed
    should build this once and pass it to `build_context`.
    """
    return build_name_idf(
        (
            normalize_name(name)
            for txn in index.by_id.values()
            for name in (txn.sender_name, txn.receiver_name)
            if name
        ),
        floor=policy.name_idf_floor,
    )


def doubted_fields(
    claim: PaymentClaim,
    policy: DecisionPolicy,
    comparisons: Sequence[Comparison] = COMPARISONS,
) -> tuple[str, ...]:
    """Scored fields whose extraction confidence falls under the policy bar.

    Returned in `comparisons` order so two claims that doubted the same fields
    produce the same tuple whatever order the extractor happened to report them
    in — the same determinism rule the evidence rows follow.

    A field is doubted when *any* key that speaks for it (see `CONFIDENCE_KEYS`)
    came back under `min_field_confidence`. The minimum rather than the first
    hit: if an extractor reports both `reference` and `reference_id` and is sure
    of only one of them, it is not sure of the reference. A key the extractor
    never mentioned is not a doubt — `confidence_for` defaults to 1.0, because
    an extractor that reports no confidences at all (every offline path today)
    must not thereby fail every verification.
    """
    doubted: list[str] = []
    for comparison in comparisons:
        keys = CONFIDENCE_KEYS.get(comparison.field, (comparison.field,))
        reported = [
            claim.field_confidences[key] for key in keys if key in claim.field_confidences
        ]
        if reported and min(reported) < policy.min_field_confidence:
            doubted.append(comparison.field)
    return tuple(doubted)


def build_context(
    claim: PaymentClaim,
    order: Order | None,
    ledger: Iterable[LedgerTxn] | TxnIndex,
    allocations: Iterable[Allocation] | AllocationIndex,
    *,
    now: datetime,
    policy: DecisionPolicy,
    observations: Iterable[str] = (),
    prior_proofs: Iterable[ProofFingerprint] | ProofIndex = (),
    name_idf: Mapping[str, float] | None = None,
) -> Context:
    """Everything before the rule table: retrieve, score, rank, gather.

    Exposed separately from `decide` so a test can inspect exactly what the
    rules saw, and so a caller batching many claims can reuse a prebuilt
    `TxnIndex`, `AllocationIndex` and name-IDF map instead of rebuilding all
    three once per claim.
    """
    index = (
        ledger
        if isinstance(ledger, TxnIndex)
        else TxnIndex.build(ledger, idf_floor=policy.blocking_idf_floor)
    )
    allocs = (
        allocations
        if isinstance(allocations, AllocationIndex)
        else index_allocations(allocations)
    )
    proofs = (
        prior_proofs
        if isinstance(prior_proofs, ProofIndex)
        else index_proofs(prior_proofs)
    )
    idf = name_idf if name_idf is not None else scoring_idf(index, policy)

    result = retrieve(claim, index, policy, now=now)
    ts_params = policy.timestamp_params()
    ranking = CandidateRanking.of(
        score_candidate(claim, txn, idf=idf, policy=policy, ts_params=ts_params)
        for txn in result.txns
    )

    # Amounts are only compared against a candidate we actually believe is
    # this payment. Below `tau_reject` the winner is not credible, and
    # comparing amounts anyway manufactures an accusation out of a coincidence:
    # any unrelated smaller transaction that happened to fall inside the time
    # window would make the claim look "materially inflated" and fire `R030`
    # SUSPICIOUS on a claim whose real answer is UNMATCHED. Weak candidates
    # fall through to `R060` instead, which is the honest outcome.
    best = ranking.best
    amount_compared = best is not None and best.score >= policy.tau_reject
    amount = (
        compare_amounts(
            order.expected if order is not None else None,
            best.txn.amount,  # type: ignore[union-attr]  # narrowed by amount_compared
            claim.amount,
            policy,
        )
        if amount_compared
        else NO_AMOUNT_EVIDENCE
    )

    return Context(
        claim=claim,
        order=order,
        policy=policy,
        now=now,
        ranking=ranking,
        retrieval=result,
        amount=amount,
        amount_compared=amount_compared,
        duplicates=check_ranking(
            ranking,
            order_id=order.order_id if order is not None else None,
            allocations=allocs,
        ),
        # Deliberately not conditioned on the ranking. Whether this image has
        # been accepted before is true or false regardless of what the feed
        # holds today, and gating it on a candidate would mean a reused
        # screenshot stopped being reused the moment its transaction aged out
        # of the retrieval window.
        proofs=check_proof(
            claim.proof_sha256,
            order_id=order.order_id if order is not None else None,
            proofs=proofs,
        ),
        # Read off the claim rather than off the ranking: how well the receipt
        # was READ is a property of the receipt, and it is the same answer
        # whichever candidate ends up winning. `R067` then guards it behind
        # `>= tau_accept`, so a doubted field only ever adds a reason to stop --
        # it can never rescue a claim that had no business verifying.
        low_confidence_fields=doubted_fields(claim, policy),
        observations=_dedupe(observations),
    )


def decide(
    claim: PaymentClaim,
    order: Order | None,
    ledger: Iterable[LedgerTxn] | TxnIndex,
    allocations: Iterable[Allocation] | AllocationIndex,
    *,
    now: datetime,
    policy: DecisionPolicy,
    observations: Iterable[str] = (),
    prior_proofs: Iterable[ProofFingerprint] | ProofIndex = (),
) -> Decision:
    """Verify one claim against one merchant's ledger. The engine's front door.

    `now` is required and keyword-only: it is the instant the decision was
    taken, it is stamped onto the result, and it is the only clock this layer
    has. `observations` carries image-forensics signals produced above `core`
    (which owns no image toolkit) as opaque `ObservationCode` strings.

    `prior_proofs` is this merchant's already-accepted proof images, and it is
    the exact sibling of `allocations`: rows a caller read from a store, which
    core indexes and compares but never produces. Core hashes nothing — it is
    told what the bytes were, on `PaymentClaim.proof_sha256` — so a caller that
    passes nothing here simply gets no reuse finding, which is the honest answer
    when there is no history to consult. Keyword-only with a default for the
    same reason `observations` is: adding an input must not silently re-point
    the four positional arguments at every existing call site.
    """
    ctx = build_context(
        claim,
        order,
        ledger,
        allocations,
        now=now,
        policy=policy,
        observations=observations,
        prior_proofs=prior_proofs,
    )
    rule = first_match(ctx)
    evidence = ctx.evidence

    decision = Decision(
        status=rule.status,
        risk=rule.risk,
        confidence=confidence(ctx.ranking, evidence, policy),
        reasons=_reasons_for(rule, ctx),
        matched_txn_id=_matched_txn_id(rule, ctx),
        fired_rule_id=rule.id,
        evidence=evidence,
        observations=_observations_for(ctx),
        ruleset_version=RULESET_VERSION,
        policy_fingerprint=policy.fingerprint(),
        engine_version=ENGINE_VERSION,
        evaluated_at=now,
    )
    return _enforce_invariants(decision, ctx)
