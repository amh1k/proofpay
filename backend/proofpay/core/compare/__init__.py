"""Per-field comparisons.

`levels.py` holds the machinery; each sibling module defines the `Comparison`
for one field (sender name, amount, timestamp, reference, channel). Field
modules own their level ladders; every threshold they test lives in
`DecisionPolicy` and reaches them through the evaluation `ctx`.
"""

from proofpay.core.compare.levels import (
    Agreement,
    Comparison,
    FieldOutcome,
    Level,
    MetricsFn,
    Predicate,
    always,
    default_metrics,
    else_level,
)

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
