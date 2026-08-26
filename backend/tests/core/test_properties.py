"""Property-based tests: the invariants that must hold for *every* input.

Guide 9.3. The parametrised tables in `test_engine.py` cover the finite things
— the rule table, one scenario per rung. This file covers the infinite ones:
the scorers, the level machinery, money arithmetic, and the single
architectural commitment the whole product rests on.

Seven properties are load-bearing, and each has a section below:

1. **An empty ledger can never be VERIFIED** (guide 7.5). No screenshot-derived
   signal may alone establish that payment occurred. Every other test in this
   repository could be deleted before this one.
2. **Every `Comparison` is total.** For any pair of inputs — `None`, empty,
   whitespace, Arabic-Indic digits, mask glyphs, arbitrary Unicode — evaluating
   a field returns a `FieldOutcome` and never raises.
3. **Level scores are non-increasing** down every ladder in the codebase, and
   every ladder ends in the structural `always` ELSE.
4. **Money round-trips** through its display form, and never touches a float.
5. **Ranking is deterministic**: shuffling the feed cannot change a decision.
6. **Timestamp similarity is monotone**: closer never scores lower than further.
7. **Removing evidence never helps**: a field the reader could not make out
   must not score better than the same field read and found weak, or cropping
   the sender's name off a receipt would improve the receipt.

Two conventions this file relies on and re-asserts:

* **`>=` everywhere.** A value exactly on a threshold belongs to the better
  level. The exact-boundary cases live in `test_boundaries.py`.
* **Comparisons are discovered, not listed.** `ALL_COMPARISONS` walks
  `proofpay.core.compare` at import, so a new field ladder is covered by
  properties 2 and 3 the moment it is written, and a removed one fails loudly.
"""

from __future__ import annotations

import importlib
import math
import os
import pkgutil
import random
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import proofpay.core.compare as compare_pkg
from proofpay.core.compare.amount_match import compare_amount_match
from proofpay.core.compare.decay import exponential, gauss
from proofpay.core.compare.levels import Agreement, Comparison, FieldOutcome, always
from proofpay.core.compare.name import (
    build_name_idf,
    compare_name,
    token_alignment,
)
from proofpay.core.compare.reference import compare_reference
from proofpay.core.compare.timestamp import (
    compare_timestamp,
    window_gap_s,
)
from proofpay.core.decide.engine import (
    COMPARISONS,
    SENDER_NAME,
    aggregate_score,
    build_context,
    confidence,
    decide,
    score_candidate,
    scoring_idf,
)
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.models import LedgerTxn, Order, PaymentClaim
from proofpay.core.money import Money
from proofpay.core.normalize import normalize_name, parse_amount_money
from proofpay.core.reasons import (
    TRUSTED_LEDGER_SOURCES,
    ObservationCode,
    Risk,
    Status,
)
from proofpay.core.retrieval import TxnIndex
from proofpay.core.timex import PKT, ClaimedInstant

MERCHANT = "M-1"
NOW = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
POLICY = DecisionPolicy()
TS_PARAMS = POLICY.timestamp_params()
NAME_T = POLICY.name_thresholds()

#: Hypothesis defaults would flag `decide` as slow on a cold Windows import and
#: the deadline as flaky under coverage. Neither says anything about the code,
#: so both are turned off rather than worked around.
#:
#: 200 examples per property keeps the suite under fifteen seconds, which is
#: the budget that keeps people running it. To hunt harder — after touching a
#: scorer, or when a shrunk counterexample looks suspiciously specific — set
#: `PROOFPAY_HYPOTHESIS_EXAMPLES=5000` and run this file alone.
PROPERTY = settings(
    max_examples=int(os.environ.get("PROOFPAY_HYPOTHESIS_EXAMPLES", "200")),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


# ==========================================================================
# Strategies
# ==========================================================================

#: Inputs that have historically broken text handling somewhere: empty and
#: whitespace-only strings, mask glyphs, non-ASCII digits, zero-width
#: characters, a lone initial, and a bare label with no value.
NASTY_TEXT: tuple[str, ...] = (
    "",
    " ",
    "\t\n ",
    "*",
    "****",
    "x",
    "xx",
    "M. Ali",
    "MUHAMMAD A***",
    "محمد علی",
    "١٥٠٠",
    "\u200b",
    "TID:",
    "TID: 0000",
    "0",
    "-",
    "..",
    "Rs. 1,500/-",
    "ß",
    "\x00",
)

NAME_TOKENS: tuple[str, ...] = (
    "muhammad",
    "mohammad",
    "ali",
    "khan",
    "zulqarnain",
    "haider",
    "farhat",
    "kanwal",
    "fatima",
    "syed",
    "m",
    "a",
)

nasty_text = st.sampled_from(NASTY_TEXT)
maybe_text = st.one_of(st.none(), nasty_text, st.text(max_size=40))

realistic_names = st.lists(st.sampled_from(NAME_TOKENS), min_size=1, max_size=4).map(
    " ".join
)
maybe_name = st.one_of(st.none(), realistic_names, nasty_text, st.text(max_size=30))

references = st.text(alphabet="0123456789ABCDEFOISabcdef -:", min_size=1, max_size=16)
maybe_ref = st.one_of(st.none(), references, nasty_text)

#: Bounded so the generated data stays inside the domain the engine is for
#: (a merchant's payments over a few years) rather than exercising the C
#: library's date arithmetic.
aware_datetimes = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2028, 1, 1),
    timezones=st.just(UTC),
)

#: Non-negative: a negative claimed amount is not a thing a receipt can say.
#: `Money`'s own algebra is exercised over the signed range separately.
money = st.builds(Money, st.integers(min_value=0, max_value=10**10))

claimed_instants = st.builds(
    ClaimedInstant,
    resolved_utc=aware_datetimes,
    granularity_s=st.sampled_from([1, 60, 86_400]),
    tz_stated=st.booleans(),
    date_inferred=st.booleans(),
)

claims = st.builds(
    PaymentClaim,
    claim_id=st.text(min_size=1, max_size=10),
    merchant_id=st.one_of(st.none(), st.just(MERCHANT), st.just("M-OTHER")),
    provider=st.one_of(st.none(), st.sampled_from(["easypaisa", "jazzcash", "raast"])),
    amount=st.one_of(st.none(), money),
    sender_name=maybe_name,
    receiver_name=maybe_name,
    sender_account=maybe_text,
    receiver_account=maybe_text,
    reference_id=maybe_ref,
    occurred_at=st.one_of(st.none(), claimed_instants),
    notes=st.lists(st.sampled_from(list(ObservationCode)), max_size=3).map(tuple),
)

orders = st.builds(
    Order,
    order_id=st.text(min_size=1, max_size=8),
    expected=st.one_of(st.none(), money),
    merchant_id=st.just(MERCHANT),
)

#: Only ledger-grade provenance. A feed row sourced from a customer screenshot
#: is a *programming* error by design — `_enforce_invariants` raises on it, and
#: `test_engine.py` pins that behaviour — so generating one here would be
#: testing the assertion, not the properties.
trusted_sources = st.sampled_from(sorted(TRUSTED_LEDGER_SOURCES))


@st.composite
def feeds(draw: st.DrawFn, *, min_size: int = 0, max_size: int = 4) -> list[LedgerTxn]:
    """A merchant feed with unique transaction ids.

    `TxnIndex.build` refuses a repeated `txn_id` — every determinism guarantee
    in retrieval rests on that id being unique — so uniqueness is generated in
    rather than filtered out.
    """
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    return [
        LedgerTxn(
            txn_id=f"TX{i:03d}",
            amount=draw(money),
            occurred_at=draw(aware_datetimes),
            merchant_id=MERCHANT,
            external_id=draw(maybe_ref),
            sender_name=draw(maybe_name),
            source=draw(trusted_sources),
        )
        for i in range(size)
    ]


# ==========================================================================
# The comparison registry: discovered, never hand-listed
# ==========================================================================

def _discover_comparisons() -> dict[str, Comparison]:
    """Every `Comparison` instance reachable in `proofpay.core.compare`.

    Walking the package rather than importing four names by hand is what makes
    properties 2 and 3 cover a ladder nobody remembered to add here.
    """
    found: dict[str, Comparison] = {}
    for info in pkgutil.iter_modules(compare_pkg.__path__):
        module = importlib.import_module(f"{compare_pkg.__name__}.{info.name}")
        for attr, value in vars(module).items():
            if isinstance(value, Comparison):
                found[f"{info.name}.{attr}"] = value
    # Built at engine import from `name_comparison`, so it is not a module-level
    # attribute of the compare package but is very much a live ladder.
    found["engine.SENDER_NAME"] = SENDER_NAME
    return found


ALL_COMPARISONS: dict[str, Comparison] = _discover_comparisons()

#: Field name -> the module entry point that builds the metrics and evaluates
#: the ladder. Totality is a property of *this* call, not of `evaluate` handed
#: a ctx someone constructed by hand: the predicates read pre-computed metrics,
#: so an arbitrary ctx would be testing `dict.__getitem__`.
DRIVERS: dict[str, Callable[[Any, Any], FieldOutcome]] = {
    "reference": lambda a, b: compare_reference(
        a, b, min_partial_len=POLICY.ref_min_partial_len
    ),
    "amount": lambda a, b: compare_amount_match(a, b, tolerance_minor=0),
    "timestamp": lambda a, b: compare_timestamp(a, b, TS_PARAMS),
    "sender_name": lambda a, b: compare_name(a, b, idf={}, thresholds=NAME_T),
}


def test_every_discovered_comparison_has_a_totality_driver():
    """A new field ladder must arrive with a way to drive it from raw inputs.

    Without this the discovery above would silently stop covering a comparison
    the day someone adds one, which is exactly when the coverage matters.
    """
    fields = {c.field for c in ALL_COMPARISONS.values()}
    assert fields == set(DRIVERS), (
        f"comparison fields {sorted(fields)} != drivers {sorted(DRIVERS)}"
    )
    assert {c.field for c in COMPARISONS} <= fields


def test_discovery_found_the_known_ladders():
    """Guards the discovery mechanism itself against silently finding nothing."""
    assert {c.field for c in ALL_COMPARISONS.values()} == {
        "reference",
        "amount",
        "timestamp",
        "sender_name",
    }


# ==========================================================================
# 1. The most important property in the project (guide 7.5)
# ==========================================================================

@given(
    claim=claims,
    order=st.one_of(st.none(), orders),
    observations=st.lists(st.sampled_from(list(ObservationCode)), max_size=6),
)
@PROPERTY
def test_an_empty_ledger_can_never_be_verified(claim, order, observations):
    """> No screenshot-derived signal may alone establish that payment occurred.

    For *any* claim — every field readable, a perfect transaction id, a
    plausible amount, a name, a timestamp, and any set of image observations —
    against a merchant with no transactions at all, the answer is never
    VERIFIED. There is no evidence in the world that can be carried by a
    screenshot alone.

    `R010` is asserted alongside the status because "not VERIFIED" could be
    reached by accident from a dozen rules; the honest answer to "we have no
    ledger" is specifically "no candidates".
    """
    decision = decide(
        claim,
        order,
        (),
        (),
        now=NOW,
        policy=POLICY,
        observations=tuple(observations),
    )
    assert decision.status is not Status.VERIFIED
    assert decision.status is Status.UNMATCHED
    assert decision.fired_rule_id == "R010"
    assert decision.matched_txn_id is None
    assert decision.evidence == ()


@given(claim=claims, order=st.one_of(st.none(), orders), feed=feeds(max_size=5))
@PROPERTY
def test_verified_always_names_a_transaction_that_is_in_the_feed(claim, order, feed):
    """VERIFIED is only ever reachable by pointing at a real ledger row.

    The same invariant as above, stated over an arbitrary feed instead of an
    empty one: a VERIFIED decision must name a transaction, that transaction
    must be one the merchant actually holds, and it must be the ranking's
    winner rather than any row that happened to be retrieved.
    """
    decision = decide(claim, order, feed, (), now=NOW, policy=POLICY)
    if decision.status is not Status.VERIFIED:
        return
    assert decision.matched_txn_id in {t.txn_id for t in feed}
    ctx = build_context(claim, order, feed, (), now=NOW, policy=POLICY)
    assert ctx.best is not None
    assert decision.matched_txn_id == ctx.best.txn_id
    assert ctx.best.txn.source in TRUSTED_LEDGER_SOURCES


@given(claim=claims, order=st.one_of(st.none(), orders), feed=feeds(max_size=5))
@PROPERTY
def test_no_verified_decision_ever_rests_on_a_contradicted_field(claim, order, feed):
    """> A field that actively contradicts the match must block VERIFIED.

    The blanket statement, over arbitrary claims and arbitrary feeds rather
    than over the handful of situations somebody thought to write down. It was
    unassertable before `Agreement` existed: "which levels mean the field
    disagrees" lived only in the renderer, so a test at this layer would have
    had to import presentation to say what a contradiction is - or hard-code a
    second list of level codes and watch it drift.

    Reaching VERIFIED with a red cross on a row is not a scoring near-miss to
    be retuned. It is a screen that tells a shopkeeper two opposite things at
    once, and no combination of inputs may produce one.
    """
    decision = decide(claim, order, feed, (), now=NOW, policy=POLICY)
    if decision.status is not Status.VERIFIED:
        return
    contradicting = [e.level_code for e in decision.evidence if e.contradicts]
    assert not contradicting, (
        f"VERIFIED on evidence containing {contradicting}"
    )


@given(claim=claims, order=st.one_of(st.none(), orders), feed=feeds(max_size=5))
@PROPERTY
def test_a_contradicted_match_is_always_routed_to_a_human_or_worse(claim, order, feed):
    """The other half: a contradiction never lands on a *reassuring* verdict.

    VERIFIED is blocked by the rule above it, and the statuses that remain are
    all ones that stop the merchant - review, unmatched, suspicious, duplicate.
    Stated as a set rather than as "== NEEDS_REVIEW" because the safety
    negative rules outrank `R075` on purpose and must keep doing so.
    """
    decision = decide(claim, order, feed, (), now=NOW, policy=POLICY)
    if not any(e.contradicts for e in decision.evidence):
        return
    assert decision.status is not Status.VERIFIED
    assert decision.risk in {Risk.MEDIUM, Risk.HIGH}


@given(claim=claims, order=st.one_of(st.none(), orders), feed=feeds(max_size=5))
@PROPERTY
def test_a_decision_is_always_well_formed(claim, order, feed):
    """Whatever the input, the output is a complete, renderable audit row.

    Degrading is mandatory here: OCR drops fields routinely, and a claim
    carrying nothing but its id must still produce a decision rather than an
    exception. Every field a caller reads is checked, because the API layer
    will serialise all of them.
    """
    decision = decide(claim, order, feed, (), now=NOW, policy=POLICY)

    assert 0.0 <= decision.confidence <= 1.0
    assert decision.evaluated_at == NOW
    assert decision.fired_rule_id.startswith("R")
    assert len(set(decision.reasons)) == len(decision.reasons)
    assert len(set(decision.observations)) == len(decision.observations)
    if decision.evidence:
        fields = [e.field for e in decision.evidence]
        assert fields == sorted(fields)              # deterministic render order
        assert len(set(fields)) == len(fields)       # one row per comparison
        assert set(fields) == {c.field for c in COMPARISONS}


# ==========================================================================
# 2. Every comparison is total
# ==========================================================================

@pytest.mark.parametrize("field", sorted(DRIVERS))
def test_comparison_totality_on_nasty_inputs(field):
    """Every ladder survives every pathological *text* input, both sides.

    Written as an exhaustive loop rather than a Hypothesis strategy because
    `NASTY_TEXT` is the accumulated list of things that have actually broken
    text handling, and an exhaustive cross-product of twenty values is both
    cheaper and more honest than sampling it.
    """
    driver = DRIVERS[field]
    lefts: list[Any] = [None, *NASTY_TEXT]
    rights: list[Any] = lefts
    if field == "amount":
        # A zero amount is the one that most looks like "no amount"; a negative
        # one cannot come off a receipt but can come off a reversal row.
        lefts = rights = [None, Money(0), Money(-1), Money(1), Money(150_000)]
    if field == "timestamp":
        # The two sides are different types here: a claimed *interval* on the
        # left, a ledger *instant* on the right. A day-granularity reading and
        # an instant an epoch away are the degenerate cases.
        lefts = [
            None,
            ClaimedInstant(resolved_utc=NOW),
            ClaimedInstant(resolved_utc=NOW, granularity_s=86_400, date_inferred=True),
            ClaimedInstant(resolved_utc=datetime(1970, 1, 1, tzinfo=UTC)),
        ]
        rights = [None, NOW, NOW + timedelta(hours=1), datetime(2200, 1, 1, tzinfo=UTC)]
    for left in lefts:
        for right in rights:
            outcome = driver(left, right)
            assert isinstance(outcome, FieldOutcome)
            assert outcome.field == field
            assert 0.0 <= outcome.score <= 1.0


@given(left=maybe_text, right=maybe_text)
@PROPERTY
def test_reference_comparison_is_total(left, right):
    outcome = compare_reference(left, right, min_partial_len=POLICY.ref_min_partial_len)
    _assert_valid_outcome(outcome, "reference")


@given(left=maybe_name, right=maybe_name)
@PROPERTY
def test_name_comparison_is_total(left, right):
    outcome = compare_name(left, right, idf={}, thresholds=NAME_T)
    _assert_valid_outcome(outcome, "sender_name")


@given(
    left=st.one_of(st.none(), money),
    right=st.one_of(st.none(), money),
    tolerance=st.integers(min_value=0, max_value=10_000),
)
@PROPERTY
def test_amount_match_comparison_is_total(left, right, tolerance):
    outcome = compare_amount_match(left, right, tolerance_minor=tolerance)
    _assert_valid_outcome(outcome, "amount")


@given(
    left=st.one_of(st.none(), claimed_instants),
    right=st.one_of(st.none(), aware_datetimes),
)
@PROPERTY
def test_timestamp_comparison_is_total(left, right):
    outcome = compare_timestamp(left, right, TS_PARAMS)
    _assert_valid_outcome(outcome, "timestamp")


def _assert_valid_outcome(outcome: FieldOutcome, field: str) -> None:
    """An outcome is only useful if it is a rung of its own ladder."""
    comparison = next(c for c in ALL_COMPARISONS.values() if c.field == field)
    assert isinstance(outcome, FieldOutcome)
    assert outcome.field == field
    assert outcome.level_code in comparison.codes
    assert outcome.score in {lvl.score for lvl in comparison.levels}
    assert 0.0 <= outcome.score <= 1.0
    assert isinstance(outcome.detail, Mapping)


@pytest.mark.parametrize("field", sorted(DRIVERS))
def test_absent_evidence_is_never_scored_as_agreement(field):
    """Two unread fields are MISSING, never a match.

    This is the single most dangerous false positive the layer could produce:
    two absent references both normalise to `""`, two absent names both
    normalise to `()`, and an unguarded equality test would report either as a
    perfect match — verifying a payment on the strength of a receipt that said
    nothing at all.
    """
    outcome = DRIVERS[field](None, None)
    assert outcome.is_missing, outcome.level_code
    assert outcome.score == 0.0


@pytest.mark.parametrize("field", sorted(DRIVERS))
@pytest.mark.parametrize("side", ["left", "right"])
def test_one_absent_side_is_missing_not_mismatched(field, side):
    """A field only one side could supply is unknown, not contradicted.

    `MISSING` and `ELSE` both score 0.0, and they are told apart by
    `is_missing` alone — which is what evidence coverage in the confidence
    formula keys off. Collapsing them would make an unreadable receipt look
    exactly as confident as a contradicted one.
    """
    present: Any = {
        "reference": "TX1001",
        "amount": Money(150_000),
        "timestamp": ClaimedInstant(resolved_utc=NOW),
        "sender_name": "Zulqarnain Haider",
    }[field]
    other: Any = present
    if field == "timestamp":
        other = NOW  # the ledger side of a timestamp is a plain datetime
    pair = (present, None) if side == "left" else (None, other)
    assert DRIVERS[field](*pair).is_missing


# ==========================================================================
# 3. Ladder structure
# ==========================================================================

@pytest.mark.parametrize("name", sorted(ALL_COMPARISONS))
def test_level_scores_are_monotonically_non_increasing(name):
    """A lower rung may never score higher than the one above it.

    If it could, the ordering would contradict the number and the explanation
    would be a lie: the merchant would read "partial match" beside a score
    higher than "exact match". Equal adjacent scores are allowed — two rungs
    can carry the same weight of evidence for different reasons.
    """
    scores = [lvl.score for lvl in ALL_COMPARISONS[name].levels]
    assert scores == sorted(scores, reverse=True), scores
    assert all(0.0 <= s <= 1.0 for s in scores)


@pytest.mark.parametrize("name", sorted(ALL_COMPARISONS))
def test_every_ladder_ends_in_the_structural_else(name):
    """Totality is checked by identity, not by hope.

    `lambda a, b, c: True` would be a *behavioural* ELSE that no test can
    distinguish from a predicate that happens to be true today. `always` is
    the sentinel, and the last rung must be it.
    """
    comparison = ALL_COMPARISONS[name]
    assert comparison.levels[-1].predicate is always
    assert not any(lvl.predicate is always for lvl in comparison.levels[:-1])


@pytest.mark.parametrize("name", sorted(ALL_COMPARISONS))
def test_every_level_declares_which_way_its_evidence_points(name):
    """Every rung of every discovered ladder carries an `Agreement`.

    Discovered, not hand-listed: this is the check that covers a comparison
    somebody adds next month. `Level.agreement` is a required field so the
    construction cannot omit it, and this says the shipped ladders really do
    satisfy that rather than trusting the dataclass in the abstract.

    The `*_MISSING` pairing is asserted alongside because the two are one
    statement made twice - `FieldOutcome.is_missing` reads the suffix, evidence
    coverage in the aggregate reads `is_missing`, and the rule table reads the
    agreement. If the two ever disagreed, an unreadable field would start
    arguing against the candidate that could not be read.
    """
    for level in ALL_COMPARISONS[name].levels:
        assert isinstance(level.agreement, Agreement), (
            f"{name}: {level.code} declares no Agreement"
        )
        assert (level.agreement is Agreement.MISSING) == (
            level.code.rsplit("_", 1)[-1] == "MISSING"
        ), f"{name}: {level.code} declares {level.agreement}"


@pytest.mark.parametrize("name", sorted(ALL_COMPARISONS))
def test_every_ladder_can_actually_reach_a_contradiction(name):
    """A ladder whose ELSE agrees would silently opt its field out of `R075`.

    Each comparison's catch-all means "both sides were readable and none of the
    agreeing rungs fired", which is a disagreement. If a ladder is ever written
    whose last rung declares otherwise, the field it describes can never block
    a verification, and nothing else in the suite would notice.
    """
    assert ALL_COMPARISONS[name].levels[-1].agreement is Agreement.CONTRADICT


@pytest.mark.parametrize("name", sorted(ALL_COMPARISONS))
def test_level_codes_are_unique_and_stable_shaped(name):
    """Codes reach the database, the API and the frontend translation table.

    Uniqueness makes them addressable; the shape check keeps a lowercase or
    spaced code from ever being written, since renaming one later is a
    breaking change to stored history.
    """
    codes = ALL_COMPARISONS[name].codes
    assert len(set(codes)) == len(codes)
    for code in codes:
        assert code == code.upper()
        assert " " not in code
    missing = [c for c in codes if c.rsplit("_", 1)[-1] == "MISSING"]
    assert len(missing) <= 1, f"{name}: more than one MISSING rung: {missing}"


# ==========================================================================
# 4. Money
# ==========================================================================

signed_minor = st.integers(min_value=-(10**15), max_value=10**15)


@given(minor=signed_minor)
@PROPERTY
def test_money_round_trips_through_its_display_form(minor):
    """`from_major(as_major_str(m)) == m`, exactly, for every amount.

    The display form is the only lossy-looking thing `Money` exposes, and a
    receipt total that does not survive a round trip is a reconciliation
    difference nobody can explain.
    """
    m = Money(minor)
    assert Money.from_major(m.as_major_str) == m
    assert isinstance(m.minor, int)
    assert not isinstance(m.minor, bool)


@given(a=signed_minor, b=signed_minor)
@PROPERTY
def test_money_arithmetic_is_exact_integer_algebra(a, b):
    """No float anywhere: `(x + y) - y == x` holds bit-exactly, always.

    The same identity in IEEE-754 fails for ordinary rupee amounts, which is
    the whole reason this type exists.
    """
    x, y = Money(a), Money(b)
    assert (x + y) - y == x
    assert (x + y).minor == a + b
    negated = -x
    assert -negated == x
    assert abs(x).minor == abs(a)
    assert isinstance((x + y).minor, int)


@given(major=st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False))
@PROPERTY
def test_from_major_round_trips_a_two_place_decimal(major):
    """A `Decimal` already quantised to paisa survives both directions.

    `Decimal` is allowed in exactly one place — this constructor — and must
    never leak: the result is an `int`, and comparing back is done on the
    display string, not on the `Decimal`.
    """
    m = Money.from_major(major)
    assert isinstance(m.minor, int)
    assert Money.from_major(m.as_major_str) == m
    assert Decimal(m.as_major_str) == major


@given(value=st.floats(allow_nan=True, allow_infinity=True))
@PROPERTY
def test_money_refuses_every_float(value):
    """By the time a float exists the precision is already gone.

    Accepting one would legitimise the representation this class exists to
    forbid, so it is refused for NaN, infinities and perfectly round values
    alike.
    """
    with pytest.raises(TypeError):
        Money.from_major(value)
    with pytest.raises(TypeError):
        Money(value)  # type: ignore[arg-type]


@given(rupees=st.integers(min_value=0, max_value=10**9))
@PROPERTY
def test_grouped_receipt_totals_parse_to_exact_paisa(rupees):
    """`Rs. 1,234,567` is the same number as `1234567`, to the paisa.

    Thousands separators are the most common thing on a Pakistani receipt and
    the easiest thing for a parser to turn into a decimal point. The parser's
    output is `Money`, so a failure here is a wrong amount, not a rounding
    nuance.
    """
    parsed, _notes = parse_amount_money(f"Rs. {rupees:,}/-")
    assert parsed == Money(rupees * 100)


# ==========================================================================
# 5. Determinism
# ==========================================================================

#: A feed built to make ranking hard: identical amounts at identical instants
#: with different ids, which is the tea-shop case where a stable tie-break is
#: the difference between allocating the right payment and the wrong one.
COLLIDING_AT = datetime(2026, 3, 4, 10, 42, tzinfo=UTC)


@st.composite
def colliding_feeds(draw: st.DrawFn) -> list[LedgerTxn]:
    size = draw(st.integers(min_value=2, max_value=6))
    return [
        LedgerTxn(
            txn_id=f"TX{i:03d}",
            amount=draw(st.sampled_from([Money(25_000), Money(200_000)])),
            occurred_at=COLLIDING_AT
            + timedelta(seconds=draw(st.sampled_from([0, 0, 0, 30, 600]))),
            merchant_id=MERCHANT,
            external_id=None,
            sender_name=draw(st.sampled_from(["Zulqarnain Haider", "Muhammad Ali"])),
            source=draw(trusted_sources),
        )
        for i in range(size)
    ]


DETERMINISM_CLAIM = PaymentClaim(
    claim_id="C-1",
    merchant_id=MERCHANT,
    amount=Money(25_000),
    reference_id=None,
    sender_name="Zulqarnain Haider",
    occurred_at=ClaimedInstant.from_local(
        datetime(2026, 3, 4, 15, 42), tz=PKT, granularity_s=60
    ),
)
DETERMINISM_ORDER = Order(order_id="O-1", expected=Money(25_000), merchant_id=MERCHANT)


@given(feed=colliding_feeds(), seed=st.integers(min_value=0, max_value=2**32 - 1))
@PROPERTY
def test_a_decision_is_invariant_under_feed_order(feed, seed):
    """Shuffling the ledger cannot change the verdict — or anything in it.

    Float ties plus list-sort stability plus a dict-ordered candidate list is a
    reproducibility bug waiting for a demo: the engine picks `TX002` today and
    the equally-good `TX005` tomorrow, allocates the wrong payment, and the
    conflict surfaces days later as an incoherent DUPLICATE. Whole-`Decision`
    equality is asserted, not just the status, because the evidence rows and
    the confidence number are stored and shown too.
    """
    baseline = decide(
        DETERMINISM_CLAIM, DETERMINISM_ORDER, feed, (), now=NOW, policy=POLICY
    )
    shuffled = random.Random(seed).sample(feed, len(feed))
    replayed = decide(
        DETERMINISM_CLAIM, DETERMINISM_ORDER, shuffled, (), now=NOW, policy=POLICY
    )
    assert replayed == baseline
    assert replayed.matched_txn_id == baseline.matched_txn_id
    assert replayed.confidence == baseline.confidence


@given(feed=colliding_feeds(), seed=st.integers(min_value=0, max_value=2**32 - 1))
@PROPERTY
def test_the_ranking_itself_is_a_function_of_the_data_alone(feed, seed):
    """The candidate order — not merely the winner — is order-independent.

    Asserted separately from the decision because `margin` is computed from the
    runner-up, so a ranking that agrees on first place and disagrees on second
    would silently move `R050` in and out of play.
    """
    shuffled = random.Random(seed).sample(feed, len(feed))
    left = build_context(
        DETERMINISM_CLAIM, DETERMINISM_ORDER, feed, (), now=NOW, policy=POLICY
    )
    right = build_context(
        DETERMINISM_CLAIM, DETERMINISM_ORDER, shuffled, (), now=NOW, policy=POLICY
    )
    assert left.ranking.txn_ids() == right.ranking.txn_ids()
    assert left.ranking.margin == right.ranking.margin
    assert [c.score for c in left.ranking.scored] == [
        c.score for c in right.ranking.scored
    ]


@given(feed=colliding_feeds())
@PROPERTY
def test_scoring_is_pure(feed):
    """Scoring the same candidate twice gives the same number, forever."""
    index = TxnIndex.build(feed, idf_floor=POLICY.blocking_idf_floor)
    idf = scoring_idf(index, POLICY)
    for txn in feed:
        first = score_candidate(DETERMINISM_CLAIM, txn, idf=idf, policy=POLICY)
        again = score_candidate(DETERMINISM_CLAIM, txn, idf=idf, policy=POLICY)
        assert first.score == again.score
        assert first.evidence == again.evidence
        assert 0.0 <= first.score <= 1.0


# ==========================================================================
# 6. Timestamp monotonicity
# ==========================================================================

distances = st.floats(min_value=0.0, max_value=1e7, allow_nan=False, allow_infinity=False)


@given(d1=distances, d2=distances)
@PROPERTY
def test_gaussian_decay_is_monotone_in_distance(d1, d2):
    """Closer is never worth less. The whole reason a decay curve replaced a
    boolean window — 14m59s must not be perfect while 15m01s is worthless."""
    assume(d1 <= d2)
    assert gauss(d1, 120.0, 900.0) >= gauss(d2, 120.0, 900.0) - 1e-12
    assert exponential(d1, 120.0, 900.0) >= exponential(d2, 120.0, 900.0) - 1e-12


@given(d=distances)
@PROPERTY
def test_both_decay_curves_are_bounded_and_agree_at_their_anchors(d):
    """`offset` and `offset + scale` are the two points a reviewer can argue
    about, so both curves are pinned to 1.0 and 0.5 there by construction."""
    for curve in (gauss, exponential):
        value = curve(d, 120.0, 900.0)
        assert 0.0 <= value <= 1.0
        assert curve(120.0, 120.0, 900.0) == 1.0
        assert curve(1020.0, 120.0, 900.0) == pytest.approx(0.5)


@given(
    instant=claimed_instants,
    near=st.floats(min_value=0.0, max_value=5e5, allow_nan=False),
    far=st.floats(min_value=0.0, max_value=5e5, allow_nan=False),
)
@PROPERTY
def test_timestamp_similarity_never_rewards_the_further_transaction(instant, near, far):
    """A transaction closer to the receipt's window never scores lower.

    Distances are measured from the *end* of the claimed window, so both probes
    are outside it and `window_gap_s` is exactly the offset — which keeps this
    a test of the similarity curve rather than of interval arithmetic.

    Note what is deliberately *not* asserted: the level *score* is not monotone,
    and must not be. A transaction exactly one hour away scores `TS_HOUR_ART`
    (0.25) while a nearer but arbitrary miss scores `TS_ELSE` (0.00), because
    a whole-hour difference is a specific, reportable story and a random miss
    is not.
    """
    assume(near <= far)
    _, end = instant.window()
    close_txn = end + timedelta(seconds=near)
    far_txn = end + timedelta(seconds=far)

    assert window_gap_s(instant, close_txn) <= window_gap_s(instant, far_txn) + 1e-9

    close_sim = compare_timestamp(instant, close_txn, TS_PARAMS).detail["sim"]
    far_sim = compare_timestamp(instant, far_txn, TS_PARAMS).detail["sim"]
    assert close_sim >= far_sim - 1e-12


@given(instant=claimed_instants, offset=st.floats(min_value=0.0, max_value=1e5))
@PROPERTY
def test_a_transaction_inside_the_claimed_window_is_a_perfect_time_match(
    instant, offset
):
    """A reading pins down an interval, not an instant.

    A date-only receipt must not be judged as if it had claimed midnight, so
    anything inside its window is zero distance and full similarity.
    """
    start, end = instant.window()
    inside = start + timedelta(
        seconds=min(offset, (end - start).total_seconds() / 2)
    )
    assert window_gap_s(instant, inside) == 0.0
    assert compare_timestamp(instant, inside, TS_PARAMS).detail["sim"] == 1.0


# ==========================================================================
# Scorer properties: names, references, amounts
# ==========================================================================

@given(a=realistic_names, b=realistic_names)
@PROPERTY
def test_name_token_score_is_symmetric(a, b):
    """Which side is the claim must not change how well two names agree.

    Greedy alignment is not symmetric by construction — it walks one side and
    consumes tokens from the other — so this is the property most likely to
    catch a real defect, and it is asserted rather than assumed.
    """
    left = normalize_name(a)
    right = normalize_name(b)
    forward = token_alignment(left, right, {}, pair_min=NAME_T.pair_min)
    backward = token_alignment(right, left, {}, pair_min=NAME_T.pair_min)
    assert forward["token_score"] == pytest.approx(backward["token_score"], abs=1e-9)


@given(name=realistic_names)
@PROPERTY
def test_a_name_always_matches_itself_perfectly(name):
    """Identity is the one alignment that can never be wrong.

    Every token pairs with its own occurrence — including a repeated one, since
    `Muhammad Muhammad` has two tokens to account for and pairing only one of
    them would leave the other counted in the denominator as a miss.
    """
    tokens = normalize_name(name)
    assume(tokens)
    result = token_alignment(tokens, tokens, {}, pair_min=NAME_T.pair_min)
    assert result["token_score"] == pytest.approx(1.0)
    assert len(result["pairs"]) == len(tokens)
    assert result["unmatched_truth"] == ()


@given(a=maybe_name, b=maybe_name)
@PROPERTY
def test_name_scores_stay_inside_the_unit_interval(a, b):
    """Both alignment scores are evidence fractions, so both are bounded.

    `idf_weighted_score` divides by a denominator that counts every token as
    fully distinctive, so it can never exceed the plain token score.
    """
    result = token_alignment(
        normalize_name(a or ""), normalize_name(b or ""), {}, pair_min=NAME_T.pair_min
    )
    assert 0.0 <= result["token_score"] <= 1.0
    assert 0.0 <= result["idf_weighted_score"] <= 1.0
    assert result["idf_weighted_score"] <= result["token_score"] + 1e-9


@given(names=st.lists(realistic_names, min_size=0, max_size=8))
@PROPERTY
def test_common_name_tokens_are_never_learned_to_be_rare(names):
    """A three-transaction merchant cannot discover that `Muhammad` is rare.

    Measured document frequency on a tiny feed says exactly that, and acting on
    it is how the engine confidently matches the wrong transaction. The static
    seed list is applied on top of the measurement, not merely as a fallback.
    """
    idf = build_name_idf(
        (normalize_name(n) for n in names), floor=POLICY.name_idf_floor
    )
    assert idf["muhammad"] == POLICY.name_idf_floor
    assert all(POLICY.name_idf_floor <= v <= 1.0 for v in idf.values())


@given(a=maybe_ref, b=maybe_ref)
@PROPERTY
def test_reference_comparison_is_symmetric(a, b):
    """Truncation happens on either side of a comparison.

    A receipt shows the tail of the ledger's id as often as a ledger export
    shows the tail of the provider's, so the rung must not depend on argument
    order.
    """
    assert compare_reference(a, b, min_partial_len=POLICY.ref_min_partial_len).level_code == compare_reference(b, a, min_partial_len=POLICY.ref_min_partial_len).level_code


@given(a=st.one_of(st.none(), money), b=st.one_of(st.none(), money))
@PROPERTY
def test_amount_match_is_symmetric(a, b):
    """`AMT_SCALED` is checked in both directions on purpose — the ladder does
    not care which side lost the trailing zero, only that one of them did."""
    assert (
        compare_amount_match(a, b, tolerance_minor=0).level_code
        == compare_amount_match(b, a, tolerance_minor=0).level_code
    )


@given(a=money)
@PROPERTY
def test_an_amount_always_matches_itself_exactly(a):
    outcome = compare_amount_match(a, a, tolerance_minor=0)
    assert outcome.level_code == "AMT_EXACT"
    assert outcome.score == 1.0


# ==========================================================================
# Aggregation and confidence
# ==========================================================================

field_scores = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@st.composite
def outcome_sets(draw: st.DrawFn) -> dict[str, FieldOutcome]:
    """One outcome per scored comparison, each either present or MISSING."""
    out: dict[str, FieldOutcome] = {}
    for comparison in COMPARISONS:
        missing = draw(st.booleans())
        prefix = comparison.codes[0].split("_")[0]
        out[comparison.field] = FieldOutcome(
            field=comparison.field,
            level_code=f"{prefix}_MISSING" if missing else f"{prefix}_TEST",
            label="generated",
            score=0.0 if missing else draw(field_scores),
            agreement=Agreement.MISSING if missing else Agreement.AGREE,
        )
    return out


@given(outcomes=outcome_sets())
@PROPERTY
def test_the_aggregate_score_is_a_bounded_weighted_mean(outcomes):
    """The aggregate is compared against `tau_accept`, so it must be a fraction.

    An aggregate above 1.0 would make `tau_accept` unreachable in one direction
    and meaningless in the other; below 0.0 would do the same to `tau_reject`.
    """
    score = aggregate_score(outcomes, POLICY)
    assert 0.0 <= score <= 1.0


@given(outcomes=outcome_sets())
@PROPERTY
def test_an_unreadable_field_never_argues_against_a_candidate(outcomes):
    """Absence of evidence is not evidence of mismatch.

    Turning a MISSING field into a zero-scored present one may only ever lower
    the aggregate: a receipt that never printed a transaction id must not be
    treated as a receipt printing the *wrong* transaction id.
    """
    as_zero = {
        name: FieldOutcome(
            field=o.field,
            level_code=o.level_code.replace("_MISSING", "_ELSE"),
            label=o.label,
            score=0.0,
            agreement=Agreement.CONTRADICT,
        )
        if o.is_missing
        else o
        for name, o in outcomes.items()
    }
    assert aggregate_score(outcomes, POLICY) >= aggregate_score(as_zero, POLICY) - 1e-9


@given(
    outcomes=outcome_sets(),
    best=field_scores,
    margin=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@PROPERTY
def test_confidence_is_bounded_and_derivable(outcomes, best, margin):
    """The published formula, recomputed independently (guide 7.6).

    A number nobody can derive is worse than no number, so the test derives it
    from the same three ingredients rather than from the implementation.
    """
    from proofpay.core.models import LedgerTxn as _Txn
    from proofpay.core.models import ScoredCandidate
    from proofpay.core.retrieval import CandidateRanking

    def _cand(txn_id: str, score: float) -> ScoredCandidate:
        return ScoredCandidate(
            txn=_Txn(txn_id=txn_id, amount=Money(1), occurred_at=NOW), score=score
        )

    runner = max(0.0, best - margin)
    ranking = CandidateRanking.of([_cand("TX1", best), _cand("TX2", runner)])
    evidence = tuple(outcomes.values())

    value = confidence(ranking, evidence, POLICY)
    coverage = sum(1 for e in evidence if not e.is_missing) / len(evidence)
    expected = round(
        min(
            1.0,
            0.5 * ranking.best.score
            + 0.3 * min(1.0, ranking.margin / POLICY.tau_margin)
            + 0.2 * coverage,
        ),
        3,
    )
    assert value == expected
    assert 0.0 <= value <= 1.0


# ==========================================================================
# 7. Removing evidence must never help
# ==========================================================================
#
# The other half of `test_an_unreadable_field_never_argues_against_a_candidate`
# above, and the half that was wrong for most of this engine's life. That test
# says a MISSING field must not be scored as a *mismatch*. This section says
# the opposite abuse is also forbidden: a MISSING field must not score better
# than a field that was read and turned out to be weak. If it can, then
# cropping the sender's name off a receipt improves the receipt, and a fraud
# product is rewarding the destruction of evidence.
#
# The arithmetic, from `aggregate_score`: replacing a present outcome of weight
# `w` and score `s` with a MISSING one takes `N/D` to `(N - ws) / (D - w(1-p))`
# for `p = missing_evidence_penalty`. That is no larger than `N/D` exactly when
# `s >= (N/D)(1-p)`, and since the aggregate is itself bounded by 1, the
# sufficient condition on the *ladder* - the one that holds whatever else is on
# the receipt - is `s >= 1 - p`.
#
# CONTRADICT rungs are excluded from the bound below, and the reason written
# here for a while was the exact inverse of the mechanism. It read: "`R075`
# blocks a verification on a contradicted field at any score, so a claim can
# never be helped across `tau_accept` by hiding one." Hiding the field REMOVES
# the `R075` block, because `R075` reads a field that is no longer there - and
# it raises the score at the same time, because a contradicted field scores 0
# and an absent one costs only `p` of its weight. The exclusion helped twice, in
# the direction this section exists to forbid.
#
# The exclusion itself has to stay, because a CONTRADICT rung scores 0 and
# `s >= 1 - p` would then demand `p = 1` - which is precisely "an unreadable
# field argues against the candidate", forbidden two hundred lines up by
# `test_an_unreadable_field_never_argues_against_a_candidate`. No penalty
# satisfies both properties. So this is a real, open exposure rather than a case
# the bound quietly covers, and it is pinned as one in `KNOWN_VERDICT_EXPOSURES`
# below and walked through the real `decide()` there. The bound in this section
# is what the AGREE and WEAK rungs - which block nothing at all - have to earn
# on their own.

#: The lower bound every agreeing rung has to clear for absence never to beat
#: presence. Derived from the policy rather than written as 0.5, so retuning
#: `missing_evidence_penalty` re-derives the bound instead of leaving a stale
#: constant asserting the old one.
ABSENCE_FLOOR: float = 1.0 - POLICY.missing_evidence_penalty

#: The rungs that still score below `ABSENCE_FLOOR`, named one by one with the
#: reason each is tolerated - the same pin-don't-hide shape
#: `KNOWN_DISAGREEMENTS` uses in the manifest harness. A third entry appearing
#: here is a decision somebody has to make out loud, which is why the test
#: below fails rather than widening the set.
#:
#: Closing the last of the hole means `missing_evidence_penalty >= 0.7561`,
#: which drops two labelled scenarios in `scenarios.yaml`
#: (`no-transaction-id-printed` and `amount-unreadable-on-receipt`) below
#: `tau_accept` - they assert that a receipt which simply never printed a field
#: can still verify. Raising these two rung scores instead moves every score in
#: the corpus. Both are product calls; neither is a tuning one.
KNOWN_ABSENCE_EXPOSURES: dict[str, str] = {
    "NAME_COMMON_ONLY": (
        "Agreeing on `Muhammad Ali` is close to no evidence at all, and 0.20 is "
        "the honest weight for it. Raising it to clear the floor would make the "
        "commonest name in Pakistan into real evidence, which is the failure "
        "this rung exists to prevent."
    ),
    "TS_HOUR_ART": (
        "A receipt exactly one hour out is either a timezone rendering bug or a "
        "different transaction, and 0.25 says the engine cannot tell which. "
        "Scoring it higher would let an AM/PM artefact carry a verification."
    ),
}


@pytest.mark.parametrize("name", sorted(ALL_COMPARISONS))
def test_no_agreeing_rung_scores_below_what_its_own_absence_is_worth(name):
    """Every rung that supports a match, on every discovered ladder.

    Parametrised over the discovered comparisons rather than over a written
    list, so a ladder somebody adds next month is held to the same bound on
    the day it is written.
    """
    for level in ALL_COMPARISONS[name].levels:
        if level.agreement in (Agreement.MISSING, Agreement.CONTRADICT):
            continue
        if level.code in KNOWN_ABSENCE_EXPOSURES:
            continue
        assert level.score >= ABSENCE_FLOOR, (
            f"{name}: {level.code} scores {level.score}, below the "
            f"{ABSENCE_FLOOR} an absent field is worth. A receipt would score "
            f"better with this field cropped off than with it read. Either "
            f"raise the rung, raise missing_evidence_penalty, or add it to "
            f"KNOWN_ABSENCE_EXPOSURES with the reason it is tolerated."
        )


def test_every_named_absence_exposure_is_a_real_rung_that_is_still_exposed():
    """A pin for a hole that has been closed is a lie in the other direction.

    Both halves matter. A code naming no rung is a typo nobody would notice,
    since the check above silently skips it; a rung that now clears the floor
    is an exemption still being granted to something that no longer needs one,
    and the entry has to be deleted rather than left there to reassure people.
    """
    by_code = {
        level.code: level
        for comparison in ALL_COMPARISONS.values()
        for level in comparison.levels
    }
    for code, why in KNOWN_ABSENCE_EXPOSURES.items():
        assert code in by_code, f"{code} names no rung on any ladder"
        assert why.strip(), f"{code} is exempted without saying why"
        assert by_code[code].score < ABSENCE_FLOOR, (
            f"{code} now scores {by_code[code].score}, at or above the "
            f"{ABSENCE_FLOOR} floor. Delete its KNOWN_ABSENCE_EXPOSURES entry."
        )


#: The exposure the bound above CANNOT cover, named rather than left to be
#: rediscovered. Keyed by the ladder rung that gets blanked.
#:
#: `test_a_contradicted_field_is_still_worth_hiding` walks this one through the
#: real engine and asserts the hole is still open, exactly as
#: `test_every_named_absence_exposure_is_a_real_rung_that_is_still_exposed`
#: does for `KNOWN_ABSENCE_EXPOSURES`: a pin for a hole somebody has closed is a
#: lie in the other direction, so closing it must fail here and the entry has to
#: be deleted rather than left reassuring people.
#:
#: **Why it is not closed here.** Not by tuning - see the algebra in the section
#: comment above, where no value of `missing_evidence_penalty` satisfies both
#: properties at once. Closing it needs a RULE: the missing-field sibling of
#: `R075`, refusing to verify a claim whose ledger row carries a value for a
#: field the receipt does not show. That rule would overturn
#: `no-transaction-id-printed` and `amount-unreadable-on-receipt` in
#: `scenarios.yaml`, both of which assert on purpose that a receipt which simply
#: never printed a field can still verify. Which of those two products this is,
#: is a decision for whoever owns the rule table, and not one to take by editing
#: a threshold until a test goes green.
KNOWN_VERDICT_EXPOSURES: dict[str, str] = {
    "NAME_ELSE": (
        "A sender name that flatly contradicts the transaction blocks the "
        "verification through `R075`. Cropping that name off the receipt "
        "removes the field, so `R075` has nothing left to read, AND raises the "
        "aggregate, because a CONTRADICT rung scores 0 while an absent field "
        "costs only `missing_evidence_penalty` of its weight. The claim goes "
        "from NEEDS_REVIEW to VERIFIED. Every CONTRADICT rung on every ladder "
        "has this shape; the sender name is the one a pair of scissors reaches "
        "most easily, which is why it is the one walked through the engine."
    ),
}


def _contradicting_name_case(sender_name):
    """One claim, twice: the sender name read, and the sender name cropped off.

    Everything else is held identical and deliberately strong - reference,
    amount and timestamp all agree exactly - so the ONLY variable is whether the
    contradicting field is on the receipt. That is what makes the comparison a
    statement about the field rather than about the arrangement around it.

    Returns the decision and the winner's aggregate together, because the
    exposure has two halves and each is checked separately: the rule that fired,
    and the score that let it.
    """
    occurred = datetime(2026, 8, 22, 8, 54, tzinfo=UTC)
    txn = LedgerTxn(
        txn_id="EP0000011",
        amount=Money(150_000),
        occurred_at=occurred,
        sender_name="Shoaib Malik",
        provider="easypaisa",
    )
    order = Order(order_id="O-1", expected=Money(150_000), reference="ORD-1")
    claim = PaymentClaim(
        claim_id="contradiction",
        provider="easypaisa",
        amount=Money(150_000),
        sender_name=sender_name,
        reference_id="EP0000011",
        occurred_at=ClaimedInstant(resolved_utc=occurred, tz_stated=True),
    )
    now = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    args = (claim, order, [txn], [])
    decision = decide(*args, now=now, policy=POLICY)
    ctx = build_context(*args, now=now, policy=POLICY)
    return decision, ctx.best.score


def test_a_contradicted_field_is_still_worth_hiding():
    """The strongest surviving form of the defect this section exists to catch.

    Not a synthetic aggregate: this is `decide()`, the real rule table and the
    shipped policy. A sender name that contradicts the matched transaction sends
    the claim to a human; the same receipt with that name cropped away comes back
    VERIFIED. "Crop the sender's name off" is the first thing anybody pokes at on
    a fraud product, and the honest answer today is that it works - on a
    contradicted field, though no longer on a weakly-agreeing one, which is what
    raising `missing_evidence_penalty` to 0.50 did fix.

    Asserted as a CURRENT FACT, so closing it fails here. When it does: delete
    the `NAME_ELSE` entry from `KNOWN_VERDICT_EXPOSURES` and delete this test,
    rather than relaxing either.
    """
    read, read_score = _contradicting_name_case("Bilal Chaudhry")
    cropped, cropped_score = _contradicting_name_case(None)

    assert read.status is Status.NEEDS_REVIEW
    assert read.fired_rule_id == "R075"
    assert cropped.status is Status.VERIFIED, (
        "Hiding a contradicted field no longer buys a verification. That is the "
        "hole KNOWN_VERDICT_EXPOSURES pins as open - delete the NAME_ELSE entry "
        "and this test."
    )
    # Both halves are live, rather than one masking the other: the rule stopped
    # blocking AND the score went up.
    assert cropped_score > read_score


def test_every_named_verdict_exposure_names_a_real_rung():
    """The same both-directions check `KNOWN_ABSENCE_EXPOSURES` gets.

    A code naming no rung is a typo nobody would notice, because nothing else
    reads this table; an entry with no reason is an exemption granted in
    silence. The "is it still open" half lives in the test above, which walks
    the engine rather than the ladder.
    """
    by_code = {
        level.code
        for comparison in ALL_COMPARISONS.values()
        for level in comparison.levels
    }
    for code, why in KNOWN_VERDICT_EXPOSURES.items():
        assert code in by_code, f"{code} names no rung on any ladder"
        assert why.strip(), f"{code} is exempted without saying why"


#: Field -> the prefix its level codes are built from, so a synthetic outcome
#: can be given the `_MISSING` suffix `FieldOutcome.is_missing` actually reads.
_CODE_PREFIX: dict[str, str] = {c.field: c.codes[0].split("_")[0] for c in COMPARISONS}


def _blanked(o: FieldOutcome) -> FieldOutcome:
    """The same field, unreadable: zero score, MISSING agreement, MISSING code."""
    return FieldOutcome(
        field=o.field,
        level_code=f"{_CODE_PREFIX[o.field]}_MISSING",
        label="unreadable",
        score=0.0,
        agreement=Agreement.MISSING,
    )


def _outcome_at(field: str, score: float) -> FieldOutcome:
    return FieldOutcome(
        field=field,
        level_code=f"{_CODE_PREFIX[field]}_TEST",
        label="generated",
        score=score,
        agreement=Agreement.AGREE,
    )


@st.composite
def outcomes_no_weaker_than_the_floor(draw: st.DrawFn) -> dict[str, FieldOutcome]:
    """One present outcome per scored comparison, none below `ABSENCE_FLOOR`."""
    return {
        c.field: _outcome_at(
            c.field,
            draw(st.floats(min_value=ABSENCE_FLOOR, max_value=1.0, allow_nan=False)),
        )
        for c in COMPARISONS
    }


@given(
    outcomes=outcomes_no_weaker_than_the_floor(),
    blanked=st.sampled_from([c.field for c in COMPARISONS]),
)
@PROPERTY
def test_removing_evidence_can_never_raise_the_aggregate(outcomes, blanked):
    """The invariant itself, over every arrangement of the sibling fields.

    An example would say only that one particular receipt does not improve
    when a field is cropped away. The claim a merchant relies on is stronger:
    for *any* combination of sibling evidence at or above `ABSENCE_FLOOR`,
    destroying one field cannot raise the score. That is the guarantee the
    floor was chosen to buy, so it is asserted at the floor rather than at the
    scores the shipped ladders happen to carry today.
    """
    before = aggregate_score(outcomes, POLICY)
    after = aggregate_score({**outcomes, blanked: _blanked(outcomes[blanked])}, POLICY)
    assert after <= before + 1e-9, (
        f"blanking {blanked} (score {outcomes[blanked].score}) raised the "
        f"aggregate from {before} to {after}"
    )


def test_the_residual_hole_is_real_and_this_is_what_it_looks_like():
    """The exposure the table above tolerates, demonstrated rather than described.

    `NAME_COMMON_ONLY` still scores below the floor, so a receipt whose sender
    line was cropped away really does aggregate higher than the same receipt
    with a common name printed on it. What `missing_evidence_penalty` 0.50
    changed is the size of the gap and, on the pair that matters, the verdict:
    `scenarios.yaml` carries those two receipts as labelled rows and both now
    land in review, where at 0.25 the cropped one verified and the honest one
    did not.

    Written as a test so that the day somebody closes this properly it fails
    and points at the comment saying what to delete.
    """
    common = {
        "reference": _outcome_at("reference", 1.0),  # REF_EXACT
        "amount": _outcome_at("amount", 1.0),  # AMT_EXACT
        "timestamp": _outcome_at("timestamp", 0.6),  # TS_DATE_ONLY
        "sender_name": _outcome_at("sender_name", 0.2),  # NAME_COMMON_ONLY
    }
    cropped = {**common, "sender_name": _blanked(common["sender_name"])}

    assert aggregate_score(cropped, POLICY) > aggregate_score(common, POLICY)
    assert aggregate_score(cropped, POLICY) < POLICY.tau_accept, (
        "the cropped receipt is back above tau_accept: the hole is no longer "
        "only a scoring artefact and is deciding verdicts again"
    )


# ==========================================================================
# Tenant isolation, allocation safety, and the batching path
# ==========================================================================

@given(claim=claims, feed=feeds(max_size=5), foreign=feeds(max_size=3))
@PROPERTY
def test_retrieval_never_returns_another_merchants_transaction(claim, feed, foreign):
    """The one hard filter in retrieval, asserted as an absolute.

    Provider is deliberately *not* filtered — a misread logo must not hide the
    true transaction — but a merchant mismatch is different in kind: returning
    another merchant's payment is a data-leak bug, not a recall trade-off. It
    is asserted here rather than in retrieval's own tests because the property
    must hold for every blocking key at once, including the ones that ignore
    the time window.
    """
    assume(claim.merchant_id is not None)
    others = [
        LedgerTxn(
            txn_id=f"FOREIGN-{t.txn_id}",
            amount=t.amount,
            occurred_at=t.occurred_at,
            merchant_id="M-SOMEONE-ELSE",
            external_id=t.external_id,
            sender_name=t.sender_name,
            source=t.source,
        )
        for t in foreign
    ]
    assume(claim.merchant_id != "M-SOMEONE-ELSE")

    ctx = build_context(claim, None, [*feed, *others], (), now=NOW, policy=POLICY)
    retrieved = {t.merchant_id for t in ctx.retrieval.txns}
    assert "M-SOMEONE-ELSE" not in retrieved


@given(claim=claims, order=orders, feed=feeds(min_size=1, max_size=4))
@PROPERTY
def test_a_transaction_allocated_to_another_order_is_never_verified(
    claim, order, feed
):
    """One trusted transaction pays for one order.

    The database is the enforcer; this layer only observes. But if the engine
    can ever return VERIFIED naming a payment another order already consumed,
    the merchant ships goods twice for one payment — so the observation must
    outrank every positive rule, whatever the scores say.
    """
    from proofpay.core.models import Allocation

    allocations = [
        Allocation(txn_id=t.txn_id, order_id="O-SOMEWHERE-ELSE") for t in feed
    ]
    assume(order.order_id != "O-SOMEWHERE-ELSE")

    decision = decide(claim, order, feed, allocations, now=NOW, policy=POLICY)
    assert decision.status is not Status.VERIFIED
    assert decision.matched_txn_id is None or decision.status is Status.DUPLICATE


@given(claim=claims, order=orders, feed=feeds(min_size=1, max_size=4))
@PROPERTY
def test_re_verifying_the_same_order_is_idempotent_not_a_duplicate(
    claim, order, feed
):
    """A resubmitted screenshot is a page refresh, not an accusation.

    Allocating a transaction to *this* order and asking again must not turn
    idempotency into DUPLICATE — the order is simply already paid by exactly
    the transaction the claim points at.
    """
    from proofpay.core.models import Allocation

    allocations = [
        Allocation(txn_id=t.txn_id, order_id=order.order_id) for t in feed
    ]
    decision = decide(claim, order, feed, allocations, now=NOW, policy=POLICY)
    assert decision.status is not Status.DUPLICATE


@given(claim=claims, order=st.one_of(st.none(), orders), feed=feeds(max_size=5))
@PROPERTY
def test_the_batching_path_agrees_with_the_simple_path(claim, order, feed):
    """A prebuilt index must not change the answer, only the cost.

    Phase 2 will verify many claims against one feed and will pass a
    `TxnIndex` in rather than rebuilding it per claim. If that path ever
    diverges, the fast route silently decides differently from the route every
    test exercises.
    """
    from proofpay.core.duplicates import index_allocations

    simple = decide(claim, order, feed, (), now=NOW, policy=POLICY)
    batched = decide(
        claim,
        order,
        TxnIndex.build(feed, idf_floor=POLICY.blocking_idf_floor),
        index_allocations(()),
        now=NOW,
        policy=POLICY,
    )
    assert batched == simple


# ==========================================================================
# Policy
# ==========================================================================

@given(tau=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
@PROPERTY
def test_changing_any_threshold_moves_the_policy_fingerprint(tau):
    """A policy change that does not move the fingerprint is a broken
    fingerprint — an old decision would replay against the wrong thresholds and
    nothing would say so."""
    from dataclasses import replace

    baseline = DecisionPolicy()
    assume(not math.isclose(tau, baseline.tau_accept))
    assume(tau >= baseline.tau_reject)
    changed = replace(baseline, tau_accept=tau)
    assert changed.fingerprint() != baseline.fingerprint()
    assert changed.fingerprint() == replace(baseline, tau_accept=tau).fingerprint()
    assert len(changed.fingerprint()) == 16
