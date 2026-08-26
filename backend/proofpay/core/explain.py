"""Turning a `Decision` into something a shopkeeper can act on.

ProofPay must never answer

    Fraud probability: 87%

Nobody can act on that, nobody can dispute it, and it is not a number this
system is entitled to compute. The product's answer is the *evidence*: what the
screenshot said, what the ledger says, which fields agree, what was noticed,
and what to do next. That is what this module builds, and it is why explanation
is a domain requirement here rather than a UI nicety.

Everything comes from data already on the `Decision` — the `FieldOutcome` rows
are literally the UI rows, and each carries the label its comparison chose when
it fired. No prose is reverse-engineered out of a float, and no verdict is
re-derived: the frontend formats this contract, it does not reinterpret it.

The one thing this module does decide is *display*: which mark a row wears and,
for a couple of levels, how the row is worded. Neither can move a decision, and
both are chosen from what the level **means**, never from its score. A score
says how much evidence a field is worth; it does not say which way that
evidence points, and rendering "the names agree, but on a name too common to
prove anything" as a red ✗ tells the merchant the opposite of what the engine
found.

That meaning is *not this module's to decide*. It is `Level.agreement`,
declared beside the rung it describes in `compare/levels.py`, and the rule
table reads the same field to refuse to verify a match some field contradicts.
This module used to keep its own copy keyed by level code, which made
presentation the only layer that knew what a level meant and left the engine
unable to consult it without importing a renderer. There is one source now; the
mark is a translation of it.

Two deliberate absences:

* **No percentage of anything.** Not fraud, not confidence. `Decision.risk` is
  an ordinal band because a merchant acts on a band, and a fabricated
  probability invites false precision.
* **No policy.** This module never sees `DecisionPolicy`, so it cannot
  accidentally re-litigate a threshold. It renders a decision already taken.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Final

from proofpay.core.compare.levels import Agreement, FieldOutcome
from proofpay.core.models import Decision, LedgerTxn, Order, PaymentClaim
from proofpay.core.money import Money
from proofpay.core.reasons import ObservationCode, ReasonCode, Risk, Status
from proofpay.core.timex import GRANULARITY_DAY, PKT, ClaimedInstant

__all__ = [
    "ABSENT",
    "MARK_AGREE",
    "MARK_CAUTION",
    "MARK_CONFLICT",
    "MARK_UNKNOWN",
    "Explanation",
    "FieldRow",
    "explain",
    "format_money",
    "render_text",
]

# --------------------------------------------------------------------------
# Display vocabulary
# --------------------------------------------------------------------------

MARK_AGREE: Final[str] = "✓"      # ✓  this field supports the match
MARK_CAUTION: Final[str] = "⚠"    # ⚠  partial, assumed, or noticed
MARK_CONFLICT: Final[str] = "✗"   # ✗  this field contradicts the match
MARK_UNKNOWN: Final[str] = "?"         # unreadable — absence, not disagreement

#: The mark a row gets, decided by what its level *means* rather than by how
#: much evidence it is worth. Those are different questions, and deriving the
#: mark from the score answers the wrong one: `NAME_COMMON_ONLY` (0.20) says the
#: names *agree* on a name too common to be evidence, and a score band renders
#: that agreement as `✗ contradicts`; `AMT_SCALED` (0.35) is a deliberate digit
#: edit — the most incriminating amount finding there is — and a score band
#: renders it *softer* than a plain mismatch. Direction and strength are both
#: real, so keep them apart: the mark carries the direction, `FieldOutcome.score`
#: still carries the strength, and neither changes a decision.
#:
#: The direction itself is **not decided here**. It is `Level.agreement`,
#: declared beside the rung it describes in `compare/levels.py`, because the
#: rule table blocks a verification on a contradicting field and this module
#: draws a cross on it — the same question, asked by two layers that must never
#: answer it differently. This module owns only the glyph.
#:
#: Total by construction: `Agreement` is a closed enum and every level is
#: required to declare one, so there is no unclassified level to fall back for.
#: The score band that used to serve as that fallback is gone with it — it was
#: the thing that rendered `NAME_COMMON_ONLY`'s agreement as a red cross.
_MARK_BY_AGREEMENT: Final[Mapping[Agreement, str]] = {
    Agreement.AGREE: MARK_AGREE,
    Agreement.WEAK: MARK_CAUTION,
    Agreement.CONTRADICT: MARK_CONFLICT,
    Agreement.MISSING: MARK_UNKNOWN,
}

#: The order a person reads the evidence in, which is not alphabetical.
#: Anything unlisted follows, sorted, so a new comparison still renders.
_FIELD_ORDER: Final[tuple[str, ...]] = ("reference", "amount", "timestamp", "sender_name")

_FIELD_LABELS: Final[Mapping[str, str]] = {
    "reference": "Transaction ID",
    "amount": "Amount",
    "timestamp": "Timestamp",
    "sender_name": "Sender name",
    "receiver_name": "Receiver name",
}

_HEADLINES: Final[Mapping[Status, str]] = {
    Status.VERIFIED: "✅ PAYMENT VERIFIED",
    Status.UNMATCHED: "❓ PAYMENT NOT FOUND",
    Status.SUSPICIOUS: "⚠ PAYMENT DETAILS DO NOT MATCH",
    Status.DUPLICATE: "\U0001f501 PAYMENT ALREADY USED",
    Status.NEEDS_REVIEW: "⚠ MANUAL REVIEW REQUIRED",
}

#: What the merchant should do, per system design 12.1. One imperative
#: sentence each: an explanation that does not end in an action is a report,
#: and the person reading it is standing at a counter with a customer waiting.
_ACTIONS: Final[Mapping[Status, str]] = {
    Status.VERIFIED: "Continue with the order. The payment is in your transaction feed.",
    Status.UNMATCHED: (
        "Do not approve yet. The payment may still be processing — check again "
        "shortly, or look through your transaction feed."
    ),
    Status.SUSPICIOUS: "Do not approve the order yet.",
    Status.DUPLICATE: (
        "Do not approve the order. This payment was already used for another "
        "order — check that order before doing anything else."
    ),
    Status.NEEDS_REVIEW: "Check this payment yourself before approving the order.",
}

#: The DUPLICATE action, reworded for a reused *image*. The mapping above talks
#: about a payment that was already used, which is exactly right when a
#: transaction was allocated twice and exactly wrong when the same picture was
#: sent twice — there, the payment behind it may be perfectly good and the
#: merchant's next move is to ask for a fresh receipt rather than to go hunting
#: through an earlier order's money.
_PROOF_REUSE_ACTION: Final[str] = (
    "Do not approve the order. Ask the customer for a fresh receipt for this "
    "order — this one has been sent before."
)


def _action_for(decision: Decision) -> str:
    """The imperative sentence, chosen by status and then by what was found."""
    if decision.status is Status.DUPLICATE and ReasonCode.PROOF_REUSED in decision.reasons:
        return _PROOF_REUSE_ACTION
    return _ACTIONS[decision.status]

#: Plain-language readings of the neutral notes. Unmapped codes render as
#: themselves rather than being dropped: an observation nobody has written
#: prose for is still an observation the merchant is entitled to see.
_OBSERVATION_LABELS: Final[Mapping[str, str]] = {
    ObservationCode.IMAGE_EXIF_MISSING: "Image metadata is missing",
    ObservationCode.IMAGE_EDITOR_SIGNATURE: "Image was saved by photo-editing software",
    ObservationCode.IMAGE_ELA_ANOMALY: "Possible editing detected in part of the image",
    ObservationCode.IMAGE_RECOMPRESSED: "Image was re-saved after its original capture",
    ObservationCode.AMOUNT_OCR_GLYPH_FIXUP: "Some amount characters had to be corrected when reading",
    ObservationCode.AMOUNT_SEPARATOR_AMBIGUOUS: "The amount's decimal separator was ambiguous",
    ObservationCode.AMOUNT_NON_ASCII_DIGITS: "The amount was written in non-Latin digits",
    ObservationCode.CLAIM_INFLATED_ROUND: "The claimed amount is the received amount with a digit added",
    ObservationCode.TIME_MERIDIEM_AMBIGUOUS: "The receipt did not make AM or PM clear",
    ObservationCode.TIME_DATE_INFERRED: "The receipt showed no date, so today's date was assumed",
    ObservationCode.TIME_TZ_ASSUMED: "The receipt showed no time zone, so Pakistan time was assumed",
    ObservationCode.TIME_WHOLE_HOUR_OFFSET: "The times differ by a whole number of hours",
    ObservationCode.NAME_MASKED: "The sender name was partly hidden by the wallet",
    ObservationCode.NAME_COMMON_TOKENS_ONLY: "The names agree only on a very common name",
}

#: Merchant-facing wording that replaces a level's own label on the row.
#: A comparison labels a level for the person reading the ladder; this table
#: exists for the handful of labels that, standing alone on a row next to a
#: mark, read as the opposite of what the level means. Keyed by the stable
#: level code — the code and the score reach the row untouched, and nothing
#: here can change a decision.
_VERDICT_OVERRIDES: Final[Mapping[str, str]] = {
    # "Only a very common name matched" reads as a failure. It is not: the
    # names agree, the agreement is simply not distinctive enough to identify
    # anyone. Say that, so the row and its ⚠ tell the same story.
    "NAME_COMMON_ONLY": "Name agrees, but only on a very common name",
}

#: Levels that establish the claimed and ledger amounts were *equal*. Used to
#: recover the received amount when the caller replayed a decision without the
#: ledger row; anything weaker than equality would be inventing a number.
_AMOUNT_EQUAL_LEVELS: Final[frozenset[str]] = frozenset({"AMT_EXACT"})

#: What a row prints when there was nothing to print. Part of this module's
#: OUTPUT CONTRACT and therefore public: it is what `render_text` draws into a
#: column, and a caller rendering somewhere other than a terminal has to be able
#: to recognise it and substitute its own idea of a hole. `api/verification_mapper`
#: does exactly that -- an em dash is a drawing, and a JSON client needs `null`,
#: which is why this stopped being private the moment a second renderer existed.
ABSENT: Final[str] = "—"  # em dash: nothing was read for this field

#: Why an `R065` match is in front of a human. The fields all agree — that is
#: the point of the rule, which only fires on a match strong enough to have
#: verified — so "there is not enough evidence" is the one thing this screen
#: must not say: it sits directly above four ✓ rows and reads as a system
#: fault. What is missing is provenance, not evidence.
#:
#: Worded without naming *which* partially trusted source it was, because the
#: renderer must not depend on the ledger row: `explain` takes `txn` optionally
#: and a caller replaying a stored decision has only the `Decision`. The reason
#: code is on the decision; `txn.source` may not be there at all.
_PARTIALLY_TRUSTED_SENTENCE: Final[str] = (
    "This transaction came from an imported or hand-entered record rather than "
    "your live bank feed, so a person needs to confirm it."
)

#: `R067`'s sentence, and the blame in it points at us.
#:
#: The customer did nothing wrong here: the payment may well be perfect and the
#: fields may all agree. What happened is that our reader could not make out
#: part of the picture, so "the receipt is unclear" would accuse them of sending
#: a bad one. It also has to survive being read by a merchant who is looking at
#: four ✓ rows, which is why it names the reading rather than the evidence.
#:
#: Last of the review parts, after the contradiction and the money: those name
#: something about the payment, and this names something about us.
_LOW_CONFIDENCE_SENTENCE: Final[str] = (
    "Part of this screenshot could not be read clearly, so a person should "
    "check it against the transaction."
)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def format_money(amount: Money | None) -> str:
    """`Rs 5,000` / `Rs 1,234.50`, or an em dash when there is nothing to show.

    Thousands separators because that is how a receipt prints it, and the
    trailing `.00` dropped because a merchant reading `Rs 2,000` does not want
    to check two zeroes. Display only — `Money` arithmetic never touches this.
    """
    if amount is None:
        return ABSENT
    major, _, minor = amount.as_major_str.partition(".")
    grouped = f"{int(major):,}"
    if minor and int(minor):
        return f"Rs {grouped}.{minor}"
    return f"Rs {grouped}"


def _format_instant(when: datetime | None, tz: tzinfo) -> str:
    if when is None:
        return ABSENT
    return when.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _format_claimed_instant(claimed: ClaimedInstant | None, tz: tzinfo) -> str:
    """A reading is an interval, so show only what it actually pinned down.

    Printing `2026-03-04 00:00` for a receipt that showed a bare date invents a
    midnight the customer never claimed, and is exactly the false precision the
    timestamp comparison goes out of its way to avoid.
    """
    if claimed is None:
        return ABSENT
    local = claimed.resolved_utc.astimezone(tz)
    if claimed.granularity_s >= GRANULARITY_DAY:
        return local.strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%d %H:%M")


def _mark(outcome: FieldOutcome) -> str:
    """The tick, cross, warning or question mark for one evidence row.

    A pure translation of `FieldOutcome.agreement` — the level's own declared
    meaning — into a glyph, never a reading of its score: a cross is an
    accusation, and a field that agrees weakly must not make one. Absence
    arrives as `Agreement.MISSING` and gets its own mark, because an unread
    field is not a disagreement.
    """
    return _MARK_BY_AGREEMENT[outcome.agreement]


def _verdict(outcome: FieldOutcome) -> str:
    """The row's wording: the comparison's own label unless overridden here."""
    return _VERDICT_OVERRIDES.get(outcome.level_code, outcome.label)


def _field_sort_key(field: str) -> tuple[int, str]:
    try:
        return (_FIELD_ORDER.index(field), "")
    except ValueError:
        return (len(_FIELD_ORDER), field)


# --------------------------------------------------------------------------
# The model
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True, kw_only=True)
class FieldRow:
    """One line of the evidence table: claimed, actual, and the verdict on it."""

    field: str
    label: str          # human name of the field ("Transaction ID")
    claimed: str        # what the screenshot said
    actual: str         # what the merchant's ledger says
    verdict: str        # the level's label, or its merchant-facing rewording
    level_code: str     # the stable machine id behind that label
    mark: str

    @property
    def agrees(self) -> bool:
        return self.mark == MARK_AGREE


@dataclass(frozen=True, slots=True, kw_only=True)
class Explanation:
    """The merchant-facing view of one decision. Renderable, not re-derivable."""

    status: Status
    risk: Risk
    headline: str
    summary: str
    rows: tuple[FieldRow, ...]
    observations: tuple[str, ...]      # plain-language readings, display order
    recommended_action: str
    reasons: tuple[ReasonCode, ...]    # machine codes, for the API payload
    matched_txn_id: str | None
    fired_rule_id: str
    ruleset_version: str

    def render(self) -> str:
        return render_text(self)


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------

def _claimed_value(field: str, claim: PaymentClaim, tz: tzinfo) -> str:
    match field:
        case "reference":
            return claim.reference_id or ABSENT
        case "amount":
            return format_money(claim.amount)
        case "timestamp":
            return _format_claimed_instant(claim.occurred_at, tz)
        case "sender_name":
            return claim.sender_name or ABSENT
        case "receiver_name":
            return claim.receiver_name or ABSENT
    return ABSENT


def _actual_value(field: str, txn: LedgerTxn | None, tz: tzinfo) -> str:
    if txn is None:
        return ABSENT
    match field:
        case "reference":
            return txn.reference_id or ABSENT
        case "amount":
            return format_money(txn.amount)
        case "timestamp":
            return _format_instant(txn.occurred_at, tz)
        case "sender_name":
            return txn.sender_name or ABSENT
        case "receiver_name":
            return txn.receiver_name or ABSENT
    return ABSENT


def _received_amount(
    decision: Decision, claim: PaymentClaim, txn: LedgerTxn | None
) -> str:
    """What the merchant actually received, however this was called.

    `txn` is optional — a caller replaying a stored decision has the decision
    but may not have re-fetched the ledger row — so the received amount cannot
    come from `txn` alone. When it is absent, the decision itself may still
    establish the number: if the amount comparison landed on a level that means
    *equal*, then the ledger amount was the claimed amount, and saying so is
    reporting the recorded evidence rather than guessing at it.

    Anything weaker than equality yields `ABSENT`, and every caller checks for
    that rather than printing it — an em dash in the middle of a sentence about
    money is worse than a shorter sentence.
    """
    if txn is not None:
        return format_money(txn.amount)
    amount = decision.evidence_by_field().get("amount")
    if (
        amount is not None
        and amount.level_code in _AMOUNT_EQUAL_LEVELS
        and claim.amount is not None
    ):
        return format_money(claim.amount)
    return ABSENT


def _contradiction_sentence(decision: Decision) -> str:
    """Which field disagrees, in the merchant's own words.

    Names the field, because "needs review" on its own sends a shopkeeper back
    to a table to work out what the engine noticed. Deliberately says *does not
    match* and not *fraud*: the engine found a disagreement between a receipt
    and a ledger row, which a wrong customer, a joint account, a shared phone
    or a genuinely edited screenshot can all produce. Deciding which of those it
    was is the human's job, and the sentence is worded so it does not pre-empt
    them.

    Built from `decision.evidence` alone, so a caller replaying a stored
    decision without the ledger row gets the same sentence.
    """
    fields = [
        _FIELD_LABELS.get(e.field, e.field.replace("_", " ")).lower()
        for e in sorted(decision.evidence, key=lambda e: _field_sort_key(e.field))
        if e.contradicts
    ]
    if not fields:
        # Only reachable if a caller hand-built a decision carrying the reason
        # code without the evidence behind it. Say the true, weaker thing.
        return "One of the details does not match the transaction this receipt points to."
    if len(fields) == 1:
        return (
            f"The {fields[0]} does not match the transaction this receipt "
            f"otherwise points to."
        )
    listed = f"{', '.join(fields[:-1])} and {fields[-1]}"
    return (
        f"The {listed} do not match the transaction this receipt otherwise "
        f"points to."
    )


def _shortfall_sentence(received: str, expected: str) -> str:
    """The underpayment, worded down to whatever is actually known.

    Shared by the plain underpaid review and the imported-row one so the two
    cannot drift into describing the same shortfall differently. Like every
    other sentence here it drops a clause rather than printing `ABSENT` into
    the middle of one.
    """
    if received != ABSENT and expected != ABSENT:
        return f"{received} was received against an order for {expected}."
    if expected != ABSENT:
        return f"Less than the order total of {expected} was received."
    return "Less was received than this order asked for."


def _overpayment_sentence(received: str, expected: str) -> str:
    """The overpayment, worded down to whatever is actually known.

    The mirror of `_shortfall_sentence`, and it degrades the same way: a clause
    is dropped rather than a hole rendered into the middle of a sentence. Says
    what arrived and what was asked for, and stops there — whether the customer
    fat-fingered a digit or sent another order's money is the human's call, and
    this sentence exists to put the two numbers in front of them.
    """
    if received != ABSENT and expected != ABSENT:
        return f"{received} was received against an order for {expected}."
    if expected != ABSENT:
        return f"Much more than the order total of {expected} was received."
    return "Much more was received than this order asked for."


def _earlier_proof_order(decision: Decision) -> str | None:
    """Which order this same image already paid, if the engine recorded it.

    `core/proofs.py` publishes that as a `CODE:detail` observation rather than
    as a field on `Decision`, so this reads it back out. Reading a structured
    note is the same move as reading a reason code — both are machine-stable
    parts of the decision, and neither is prose being reverse-engineered.

    "Already used" without a place to look is an argument the merchant cannot
    win, so the sentence below is worth this much: with the order named they can
    go and check it, and without it they are being asked to take our word.
    """
    prefix = f"{ObservationCode.PROOF_PREVIOUSLY_SUBMITTED}:"
    for note in decision.observations:
        if note.startswith(prefix):
            ref = note[len(prefix) :].strip()
            if ref:
                return ref
    return None


def _summary(
    decision: Decision,
    claim: PaymentClaim,
    txn: LedgerTxn | None,
    order: Order | None,
) -> str:
    """One or two sentences naming the specific thing that happened.

    Specific beats generic here: "two transactions match equally well" tells a
    merchant what to go and look at, "needs review" does not.

    Every branch that names money is guarded on that money being known. A
    sentence is dropped rather than rendered with a hole in it: `— received.`
    is not a shorter truth, it is an unreadable one.
    """
    reasons = set(decision.reasons)
    received = _received_amount(decision, claim, txn)
    claimed = format_money(claim.amount)
    expected = format_money(order.expected) if order is not None else ABSENT
    have_received = received != ABSENT
    have_expected = expected != ABSENT

    match decision.status:
        case Status.VERIFIED:
            # Two lines, as in the product overview §5: the money first, because
            # that is the thing the merchant is deciding about.
            lines: list[str] = []
            if have_received:
                lines.append(f"{received} received.")
            if decision.matched_txn_id:
                lines.append(
                    f"Transaction {decision.matched_txn_id} matches the submitted proof."
                )
            if ReasonCode.AMOUNT_OVERPAID in reasons and have_received and have_expected:
                lines.append(f"That is more than the order total of {expected}.")
            return "\n".join(lines) or "This payment matches a transaction in your feed."
        case Status.UNMATCHED:
            if ReasonCode.NO_CANDIDATES in reasons:
                return "No matching transaction was found in your feed."
            return "No transaction in your feed matched this proof closely enough."
        case Status.SUSPICIOUS:
            if ReasonCode.CLAIM_INFLATED in reasons and have_received and claimed != ABSENT:
                return f"The screenshot claims {claimed}, but {received} was received."
            if ReasonCode.TAMPER_OBSERVATIONS in reasons:
                return "The image looks edited and the details match only weakly."
            return "A transaction was found, but the details conflict."
        case Status.DUPLICATE:
            # Two different accusations wear one status word, and the sentence
            # must not blur them. A reused TRANSACTION means the money arrived
            # once and is being spent twice. A reused SCREENSHOT means the
            # picture is a re-run — the transaction behind it may never have
            # been claimed by anyone. Saying "this transaction was already
            # used" on a `R025` verdict states something the engine did not
            # find, and a merchant who checks will find it false.
            if ReasonCode.PROOF_REUSED in reasons:
                earlier = _earlier_proof_order(decision)
                if earlier is not None:
                    return f"This same screenshot was already used for order {earlier}."
                return "This same screenshot was already used for an earlier order."
            return "This transaction was already used for another order."
        case Status.NEEDS_REVIEW:
            if ReasonCode.AMBIGUOUS_CANDIDATES in reasons:
                return "More than one transaction matches this screenshot equally well."
            # Underpayment and provenance are not alternatives. `R065` outranks
            # `R070`, and `AMOUNT_UNDERPAID` is derived from the arithmetic
            # rather than attached to a rule, so a short payment against an
            # imported row carries both codes and the merchant is owed both
            # facts. Money leads, per the product overview §5: the shortfall is
            # the thing being decided about, the provenance is why it is here.
            parts: list[str] = []
            # The contradiction leads when there is one: it is *why* this
            # decision is in front of a person, and the shortfall or the
            # provenance below it is context for that, not a competing
            # headline. (The two amount rules that lead with money, `R070` and
            # `R065`, both outrank `R075`, so a decision reaching here with a
            # contradiction really was routed by the contradiction.)
            if ReasonCode.FIELD_CONTRADICTS_MATCH in reasons:
                parts.append(_contradiction_sentence(decision))
            # `AMOUNT_OVERPAID_MATERIAL` and not `AMOUNT_OVERPAID`: the plain
            # code rides along on any overpaid claim, including ones sent here
            # by `R999` for reasons that have nothing to do with the money
            # (fixture G05 is exactly that), and announcing the overpayment
            # there would name the wrong cause. The magnitude code says the
            # overpayment is big enough to be worth a sentence of its own.
            #
            # It is derived in `compare_amounts` alongside the direction, NOT
            # carried by `R072` alone. When it was `R072`'s, every rule above
            # `R072` silently swallowed the overpayment: `R065` and `R067` both
            # outrank it, so a Rs 5,000 payment against a Rs 1,500 order was
            # announced to the merchant as "part of this screenshot could not
            # be read clearly" and nothing else. That is exactly the asymmetry
            # the comment above rejects for the shortfall case.
            if ReasonCode.AMOUNT_OVERPAID_MATERIAL in reasons:
                parts.append(_overpayment_sentence(received, expected))
            if ReasonCode.AMOUNT_UNDERPAID in reasons:
                parts.append(_shortfall_sentence(received, expected))
            if ReasonCode.SOURCE_PARTIALLY_TRUSTED in reasons:
                parts.append(_PARTIALLY_TRUSTED_SENTENCE)
            if ReasonCode.LOW_EXTRACTION_CONFIDENCE in reasons:
                parts.append(_LOW_CONFIDENCE_SENTENCE)
            if parts:
                return "\n".join(parts)
            # `R999` really does mean this, and only it should say it.
            return "There is not enough evidence to decide this automatically."
    return "This payment could not be decided automatically."


def _observation_line(code: str) -> str:
    """One neutral note, in words, falling back to the code itself.

    The `PROOF_PREVIOUSLY_SUBMITTED:<order>` note is special-cased rather than
    handled by a general `CODE:detail` split, and narrowly on purpose: the
    other note that carries a payload today is `IMAGE_PHASH:phash:<64 hex>`,
    whose detail is a hash no merchant has any use for, and a general rule
    would start printing it into the observation list. When a second note earns
    a rendered payload, that is the moment to generalise — not before.
    """
    prefix = f"{ObservationCode.PROOF_PREVIOUSLY_SUBMITTED}:"
    if code.startswith(prefix):
        ref = code[len(prefix) :].strip()
        if ref:
            return f"This same screenshot was submitted for order {ref}"
        return "This same screenshot was submitted before"
    return _OBSERVATION_LABELS.get(code, code)


def _observation_lines(codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(_observation_line(code) for code in codes)


def explain(
    decision: Decision,
    *,
    claim: PaymentClaim,
    txn: LedgerTxn | None = None,
    order: Order | None = None,
    tz: tzinfo = PKT,
) -> Explanation:
    """Build the merchant-facing explanation of a decision already taken.

    `txn` is the matched transaction when there is one; without it the actual
    column reads as absent, which is the honest rendering of `UNMATCHED`. `tz`
    defaults to Pakistan time because that is the merchant's clock — the stored
    instants are UTC, and showing them as UTC would make a correct match look
    five hours wrong.
    """
    rows = tuple(
        FieldRow(
            field=outcome.field,
            label=_FIELD_LABELS.get(outcome.field, outcome.field.replace("_", " ").title()),
            claimed=_claimed_value(outcome.field, claim, tz),
            actual=_actual_value(outcome.field, txn, tz),
            verdict=_verdict(outcome),
            level_code=outcome.level_code,
            mark=_mark(outcome),
        )
        for outcome in sorted(decision.evidence, key=lambda o: _field_sort_key(o.field))
    )
    return Explanation(
        status=decision.status,
        risk=decision.risk,
        headline=_HEADLINES[decision.status],
        summary=_summary(decision, claim, txn, order),
        rows=rows,
        observations=_observation_lines(decision.observations),
        recommended_action=_action_for(decision),
        reasons=decision.reasons,
        matched_txn_id=decision.matched_txn_id,
        fired_rule_id=decision.fired_rule_id,
        ruleset_version=decision.ruleset_version,
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _amount_block(rows: tuple[FieldRow, ...]) -> list[str]:
    """The two headline numbers, right-aligned so the digits line up.

    Aligned columns are what make `Rs 5,000` against `Rs   500` readable at a
    glance; that contrast is the single most important thing on the page when
    an amount has been edited.
    """
    amount = next((r for r in rows if r.field == "amount"), None)
    if amount is None or amount.actual == ABSENT:
        return []
    labels = ("Screenshot:", "Received:")
    values = (amount.claimed, amount.actual)
    label_w = max(len(label) for label in labels)
    value_w = max(len(value) for value in values)
    return [f"{label:<{label_w}} {value:>{value_w}}" for label, value in zip(labels, values)]


def render_text(explanation: Explanation) -> str:
    """The plain-text explanation from the product overview, section 5.

    Deliberately plain text: it is what the terminal demo prints, what a
    WhatsApp reply could carry, and a format nobody can mistake for a score.
    Contains no percentage of any kind.
    """
    lines: list[str] = [explanation.headline, "", explanation.summary]

    block = _amount_block(explanation.rows)
    if block:
        lines.extend(["", *block])

    if explanation.rows:
        lines.append("")
        lines.extend(f"{row.mark} {row.label}: {row.verdict}" for row in explanation.rows)

    if explanation.observations:
        lines.append("")
        lines.extend(f"{MARK_CAUTION} {note}" for note in explanation.observations)

    lines.extend(["", f"Risk: {explanation.risk}", "", "Recommended action:", explanation.recommended_action])
    return "\n".join(lines)
