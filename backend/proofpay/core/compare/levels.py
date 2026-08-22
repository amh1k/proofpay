"""The comparison-level machinery — the spine of the engine.

Adapted from Splink's Comparison / ComparisonLevel design: each field is a
`Comparison` holding ordered, mutually exclusive `Level`s evaluated as an
if/elif/else chain, first match wins, always ending in a catch-all ELSE. The
output per field is a discrete labelled category, never a bare float.

Three payoffs, all of which matter more than they look:

1. The explanation is free — the level's `label` *is* the UI row, so nobody has
   to reverse-engineer prose out of 0.7314.
2. The tests are finite — a five-level comparison has five outcomes.
3. Thresholds become visible objects rather than magic numbers buried in `if`s.

Conventions, fixed here and relied on everywhere:

* **`>=` everywhere.** Every threshold comparison in every level predicate is
  inclusive. A value exactly on a threshold belongs to the better level.
* **Scores are non-increasing** down the level list. If a lower level scored
  higher, the ordering would contradict the number and the explanation would be
  a lie. Enforced in `__post_init__`.
* **The last level is total.** It must be `always` (exported below). A missing
  ELSE means a field with no outcome, which is the worst possible failure mode
  for an audit trail — so it is a construction-time error, not a runtime one.
* **`ctx` carries the metrics.** Predicates read pre-computed numbers out of
  `ctx` (e.g. `ctx["token_score"]`) rather than computing them, so the same
  numbers can be shown in the evidence drawer without recomputation. By default
  `ctx` becomes `FieldOutcome.detail` verbatim.
* **Every level declares what it *means*.** `Level.agreement` says which way a
  level's evidence points — see `Agreement`. It is a required field, so a level
  cannot be added without someone deciding whether it supports the match or
  argues against it, and it travels onto the `FieldOutcome`, which is what the
  decision engine and the renderer both read. Direction is not derivable from
  `score`: `NAME_COMMON_ONLY` (0.20) says the names *agree* on a name too common
  to prove anything, and `AMT_SCALED` (0.35) is a deliberate factor-of-ten digit
  edit — the most incriminating amount finding there is. A score band gets both
  of those backwards, which is why direction lives here, beside the level, and
  is stated rather than inferred.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

__all__ = [
    "Agreement",
    "Comparison",
    "FieldOutcome",
    "Level",
    "MetricsFn",
    "Predicate",
    "always",
    "default_metrics",
    "else_level",
]


class Agreement(StrEnum):
    """Which way one field's evidence points. The single source of truth.

    This is the semantic classification of a comparison level, and it lives
    here — beside the ladder that declares it — because two very different
    consumers need exactly the same answer and must never drift apart:

    * the **rule table** blocks a verification on a field that contradicts it;
    * the **renderer** picks the tick, cross or warning the merchant reads.

    It is deliberately not derived from `Level.score`. A score says *how much*
    evidence a field is worth; it does not say *which way* that evidence
    points, and the two genuinely disagree at both ends of the ladder.

    Members are stable machine identifiers on the same footing as a level code:
    they may be added, never renamed.
    """

    #: This field supports the match.
    AGREE = "AGREE"
    #: Consistent with the match, but not strong evidence for it — the two
    #: records do not disagree, they simply fail to pin anything down
    #: (`NAME_COMMON_ONLY`, `TS_DATE_ONLY`).
    WEAK = "WEAK"
    #: This field actively contradicts the match: we read both sides and they
    #: disagree (`NAME_ELSE`, `AMT_ELSE`, `AMT_SCALED`, `REF_ELSE`, `TS_ELSE`).
    CONTRADICT = "CONTRADICT"
    #: Not readable. Absence of evidence, never evidence of mismatch — which is
    #: why it is its own member rather than a weak flavour of CONTRADICT.
    MISSING = "MISSING"

#: Predicate signature: (left, right, ctx) -> bool.
Predicate = Callable[[Any, Any, Mapping[str, Any]], bool]

#: Metrics extractor: (left, right, ctx) -> detail mapping for the outcome.
MetricsFn = Callable[[Any, Any, Mapping[str, Any]], Mapping[str, Any]]

_EMPTY: Mapping[str, Any] = MappingProxyType({})


def always(left: Any, right: Any, ctx: Mapping[str, Any]) -> bool:
    """The unconditional ELSE predicate. Identity-checked, so totality is a
    structural property of a `Comparison` rather than a hope."""
    return True


def default_metrics(
    left: Any, right: Any, ctx: Mapping[str, Any]
) -> Mapping[str, Any]:
    """`ctx` is already the computed metric bundle; expose it read-only."""
    return MappingProxyType(dict(ctx))


@dataclass(frozen=True, slots=True)
class Level:
    """One rung of a comparison ladder.

    `code` is a stable machine id — it reaches golden files, the database and
    analytics, and may never be reworded. `label` is human text and may be
    reworded at will. `score` is this field's evidence strength in 0.0..1.0 when
    this level fires, and `agreement` is which way that evidence points.

    `agreement` has no default on purpose. A level whose meaning nobody declared
    is a level the rule table and the renderer would each have to guess at, and
    they would guess differently; requiring it makes "what does this rung mean"
    a question that must be answered when the rung is written.
    """

    code: str
    label: str
    score: float
    predicate: Predicate
    agreement: Agreement

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("Level.code must be a non-empty stable identifier")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"{self.code}: score must be within 0.0..1.0")
        # `FieldOutcome.is_missing` reads the `*_MISSING` suffix and evidence
        # coverage keys off it, so the suffix convention and the declared
        # meaning are the same statement made twice. Tie them together here and
        # they cannot disagree.
        missing_suffix = self.code.rsplit("_", 1)[-1] == "MISSING"
        if missing_suffix != (self.agreement is Agreement.MISSING):
            raise ValueError(
                f"{self.code}: a level declares Agreement.MISSING if and only if "
                f"its code ends in _MISSING (got {self.agreement})"
            )


@dataclass(frozen=True, slots=True)
class FieldOutcome:
    """The result of evaluating one `Comparison`: one UI row, one audit row."""

    field: str
    level_code: str
    label: str
    score: float
    agreement: Agreement
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def contradicts(self) -> bool:
        """This field was read on both sides and the two disagree.

        The decision engine reads outcomes, not levels, so the classification
        declared on `Level` is exposed here — one property, one meaning, no
        second table to fall out of step with the first.
        """
        return self.agreement is Agreement.CONTRADICT

    @property
    def is_missing(self) -> bool:
        """True when this field could not be read at all.

        The `*_MISSING` suffix is a naming convention shared by every
        comparison, and evidence coverage in the confidence formula depends on
        it, so it is expressed once here rather than re-derived per caller.
        """
        return self.level_code.rsplit("_", 1)[-1] == "MISSING"


@dataclass(frozen=True, slots=True)
class Comparison:
    """An ordered ladder of mutually exclusive levels for one field."""

    field: str
    levels: tuple[Level, ...]
    weight: float = 1.0
    metrics: MetricsFn = default_metrics

    def __post_init__(self) -> None:
        if not self.levels:
            raise ValueError(f"{self.field}: no levels")
        scores = [lvl.score for lvl in self.levels]
        if scores != sorted(scores, reverse=True):
            raise ValueError(
                f"{self.field}: levels must be ordered most->least similar "
                f"(scores must be non-increasing, got {scores})"
            )
        codes = [lvl.code for lvl in self.levels]
        if len(set(codes)) != len(codes):
            raise ValueError(f"{self.field}: duplicate level codes in {codes}")
        if self.levels[-1].predicate is not always:
            raise ValueError(
                f"{self.field}: the last level ({self.levels[-1].code}) must be the "
                "catch-all ELSE — build it with else_level(...) or pass "
                "predicate=always from proofpay.core.compare.levels"
            )
        if self.weight < 0.0:
            raise ValueError(f"{self.field}: weight must be >= 0")

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(lvl.code for lvl in self.levels)

    def evaluate(self, left: Any, right: Any, ctx: Mapping[str, Any] = _EMPTY) -> FieldOutcome:
        """Return the first matching level as a `FieldOutcome`.

        Totality is guaranteed by construction; the trailing raise is defence in
        depth against a level predicate that raises rather than returns.
        """
        for lvl in self.levels:
            if lvl.predicate(left, right, ctx):
                return FieldOutcome(
                    field=self.field,
                    level_code=lvl.code,
                    label=lvl.label,
                    score=lvl.score,
                    agreement=lvl.agreement,
                    detail=self.metrics(left, right, ctx),
                )
        raise AssertionError(f"{self.field}: comparison is not total — add an ELSE level")


def else_level(
    code: str,
    label: str,
    score: float = 0.0,
    *,
    agreement: Agreement = Agreement.CONTRADICT,
) -> Level:
    """Build the mandatory catch-all level for a comparison.

    `agreement` defaults to `CONTRADICT` because that is what a comparison's
    ELSE means: both sides were readable — an unreadable field has already been
    caught by the ladder's `*_MISSING` rung — and none of the agreeing rungs
    fired, so the two records disagree. The default is also the fail-closed
    direction: a new comparison whose author forgets to think about its ELSE
    sends the decision to a human rather than quietly verifying it.
    """
    return Level(
        code=code, label=label, score=score, predicate=always, agreement=agreement
    )
