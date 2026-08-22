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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = [
    "Comparison",
    "FieldOutcome",
    "Level",
    "MetricsFn",
    "Predicate",
    "always",
    "default_metrics",
    "else_level",
]

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
    this level fires.
    """

    code: str
    label: str
    score: float
    predicate: Predicate

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("Level.code must be a non-empty stable identifier")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"{self.code}: score must be within 0.0..1.0")


@dataclass(frozen=True, slots=True)
class FieldOutcome:
    """The result of evaluating one `Comparison`: one UI row, one audit row."""

    field: str
    level_code: str
    label: str
    score: float
    detail: Mapping[str, Any] = field(default_factory=dict)

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
                    detail=self.metrics(left, right, ctx),
                )
        raise AssertionError(f"{self.field}: comparison is not total — add an ELSE level")


def else_level(code: str, label: str, score: float = 0.0) -> Level:
    """Build the mandatory catch-all level for a comparison."""
    return Level(code=code, label=label, score=score, predicate=always)
