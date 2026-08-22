"""The decision layer: policy, rules, engine.

The three files map onto the three things that must be independently
versionable when a decision is questioned months later:

* `policy.py` — every threshold, frozen and fingerprinted. The only module in
  `proofpay.core` allowed to hold a float literal threshold.
* `rules_v1.py` — the ordered rule table, first-match, ending in a total ELSE.
  Pinned by `RULESET_VERSION`; the `_v1` in the filename is deliberate, since a
  `rules_v2` must be able to exist beside it without disturbing stored history.
* `engine.py` — the pipeline that turns a claim plus a ledger into a
  `Decision`, and the post-condition assertion that no screenshot-derived
  signal ever establishes on its own that payment occurred.

Nothing below this package imports it: `core.compare` and `core.retrieval`
declare the slices of policy they need as structural `Protocol`s, so the
dependency runs one way only.
"""

from proofpay.core.decide.engine import (
    ENGINE_VERSION,
    Context,
    aggregate_score,
    confidence,
    decide,
    first_match,
    score_candidate,
)
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.decide.rules_v1 import RULES, RULESET_VERSION, Rule

__all__ = [
    "ENGINE_VERSION",
    "RULES",
    "RULESET_VERSION",
    "Context",
    "DecisionPolicy",
    "Rule",
    "aggregate_score",
    "confidence",
    "decide",
    "first_match",
    "score_candidate",
]
