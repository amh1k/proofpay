"""The `reference` comparison: transaction / reference IDs.

A reference ID is the highest-information field in the whole claim. Names are
transliterated, amounts repeat all day, timestamps drift - but a provider TID is
close to unique, which is why the decision engine keys its dominance escape
hatch on exactly one level code from this module:

    ``REF_EXACT`` - a unique exact reference match wins regardless of margin.

That string is a contract. It may never be reworded, and no other level may be
allowed to drift into meaning "exact".

Below exact sit the two ways real receipts disagree with a ledger:

* **Confusable glyphs.** OCR reads `O` for `0`, `I` for `1`, `S` for `5`. The
  reference is *the same reference*, misread. Strong evidence, but not proof -
  two genuinely different ids can also collide under that folding, so it scores
  below exact and never satisfies dominance.
* **Truncation.** Wallet receipts and SMS confirmations habitually print only
  the tail: "TID ...4821", "Ref: 4821". A comparison with no partial level
  scores a perfectly legitimate payment as a mismatch. The tail is real
  evidence, but weak - four digits collide often - so it is scored as such and
  is deliberately not enough on its own.

Everything is compared on `normalize_reference` output (upper-case, alphanumeric
only, provider label stripped), so `TID: 1234-5678`, `1234 5678` and
`tid12345678` are one string.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from proofpay.core.compare.levels import Comparison, FieldOutcome, Level, else_level
from proofpay.core.normalize import normalize_reference, reference_confusable_key

__all__ = [
    "REFERENCE",
    "common_suffix_len",
    "compare_reference",
    "reference_ctx",
]

# The shortest tail that counts as evidence used to be a module constant here.
# It is `DecisionPolicy.ref_min_partial_len` now: shortening it turns noise into
# a partial match and moves verdicts, and a number that moves a verdict has to
# be inside the policy fingerprint. It arrives as an argument, is published into
# `FieldOutcome.detail` as `t_min_partial_len`, and the REF_PARTIAL predicate
# reads it from there.


def common_suffix_len(left: str, right: str) -> int:
    """Length of the longest shared tail. Both sides already normalised.

    Compared from the tail rather than the head because that is the end
    receipts truncate: providers mask or drop the prefix, never the suffix.
    """
    n = 0
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            break
        n += 1
    return n


def reference_ctx(
    claim_ref: str | None, txn_ref: str | None, *, min_partial_len: int
) -> Mapping[str, Any]:
    """Pre-compute every metric the reference levels read.

    Each relation is resolved to a bool here, guarded by `both_present`, for one
    reason: two absent references normalise to the same empty string, and an
    unguarded equality test would report that as an exact match - the single
    most dangerous false positive this comparison could produce.
    """
    left = normalize_reference(claim_ref) if claim_ref else ""
    right = normalize_reference(txn_ref) if txn_ref else ""
    both = bool(left) and bool(right)

    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    suffix = common_suffix_len(left, right) if both else 0
    long_enough = both and len(shorter) >= min_partial_len

    equal = both and left == right
    confusable = (
        both
        and not equal
        and reference_confusable_key(left) == reference_confusable_key(right)
    )
    is_suffix = long_enough and not equal and longer.endswith(shorter)
    contains = long_enough and not equal and shorter in longer

    return MappingProxyType(
        {
            "left_norm": left,
            "right_norm": right,
            "both_present": both,
            "equal": equal,
            "confusable_equal": confusable,
            "is_suffix": is_suffix,
            "contains": contains,
            "common_suffix_len": suffix,
            "shorter_len": len(shorter) if both else 0,
            "longer_len": len(longer) if both else 0,
            "t_min_partial_len": min_partial_len,
        }
    )


#: The field weight (how much a reference verdict counts towards the aggregate)
#: lives in `DecisionPolicy.w_reference`, not here; this object owns the ladder.
REFERENCE: Final[Comparison] = Comparison(
    field="reference",
    levels=(
        # The dominance escape hatch in the decision engine tests for this exact
        # code string. Do not rename it.
        Level(
            "REF_EXACT",
            "Transaction ID matches exactly",
            1.00,
            lambda a, b, c: c["equal"],
        ),
        Level(
            "REF_CONFUSABLE",
            "Transaction ID matches apart from easily misread characters",
            0.90,
            lambda a, b, c: c["confusable_equal"],
        ),
        Level(
            "REF_SUFFIX",
            "Receipt shows only the last characters of this transaction ID",
            0.75,
            lambda a, b, c: c["is_suffix"],
        ),
        # Containment elsewhere in the string, or a shared tail when *both*
        # sides are truncated differently. Weaker than a clean suffix because
        # the alignment itself is a guess.
        Level(
            "REF_PARTIAL",
            "Transaction IDs partially match",
            0.55,
            lambda a, b, c: c["contains"]
            or c["common_suffix_len"] >= c["t_min_partial_len"],
        ),
        Level(
            "REF_MISSING",
            "No transaction ID to compare",
            0.00,
            lambda a, b, c: not c["both_present"],
        ),
        else_level("REF_ELSE", "Transaction IDs do not match"),
    ),
)


def compare_reference(
    claim_ref: str | None, txn_ref: str | None, *, min_partial_len: int
) -> FieldOutcome:
    """Build the metrics and evaluate the ladder - the callable most callers want.

    `min_partial_len` is required rather than defaulted: a tolerance that can be
    forgotten is a tolerance nobody versioned, and the whole point of moving it
    out of this module was that every caller has to name the policy it decided
    under.
    """
    return REFERENCE.evaluate(
        claim_ref, txn_ref, reference_ctx(claim_ref, txn_ref, min_partial_len=min_partial_len)
    )
