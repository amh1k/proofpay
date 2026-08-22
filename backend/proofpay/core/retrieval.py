"""Candidate retrieval: cheap blocking keys, unioned, never intersected.

Retrieval answers one question - *which handful of ledger transactions could
plausibly be the one this screenshot is about?* - and it answers it with dict
lookups, not by scanning the feed. Scoring is expensive and explanatory;
blocking is cheap and recall-only. Getting that split right is what keeps the
engine fast on a merchant with 50 000 transactions.

Four blocking keys, in order of narrowness (guide 3.4):

1. **Reference id** - a printed TID is very nearly a primary key. A reference
   hit is *not* filtered by time or amount, because a claim whose OCR mangled
   the amount still has a perfectly good transaction id.
2. **Time window** - ``|txn.occurred_at - anchor| <= policy.time_window_s``,
   bucketed by UTC day so the lookup stays a dict hit.
3. **Amount** - exact minor units, plus a small OCR-plausible neighbour set
   (a dropped trailing zero, one confusable digit).
4. **Name phonetics** - the recall net, and deliberately the weakest key. It
   earns its place only when the timestamp is missing or the date was inferred.

**Union, never intersection.** Intersecting blocking keys is how a perfectly
good payment becomes ``UNMATCHED`` because OCR dropped one digit of the amount.
Every key is allowed to be wrong; the scorer decides, and a false candidate
costs one comparison.

**Degrade, never crash.** Every claim field read here is optional, because OCR
drops fields routinely. A claim carrying nothing but its ``claim_id`` must
still return a sane, bounded, deterministic candidate list - anchored on
``now``.

**No clock.** The anchor for the time window is ``claim.occurred_at`` when the
screenshot carried a readable timestamp, and the ``now`` handed in otherwise.
``now`` is an argument so a stored decision replays identically forever.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from proofpay.core.models import LedgerTxn, PaymentClaim, ScoredCandidate
from proofpay.core.normalize import (
    COMMON_NAME_TOKENS,
    normalize_name,
    normalize_reference,
    reference_confusable_key,
)
from proofpay.core.phonetics import name_block_keys
from proofpay.core.timex import GRANULARITY_DAY, require_aware

__all__ = [
    "KEY_AMOUNT_EXACT",
    "KEY_AMOUNT_NEIGHBOUR",
    "KEY_NAME_PHONETIC",
    "KEY_REFERENCE_CONFUSABLE",
    "KEY_REFERENCE_EXACT",
    "KEY_REFERENCE_SUFFIX",
    "KEY_TIME_WINDOW",
    "REFERENCE_FIELD",
    "REF_EXACT_LEVEL_CODE",
    "CandidateRanking",
    "RetrievalPolicy",
    "RetrievalResult",
    "TxnIndex",
    "amount_probe_keys",
    "build_idf",
    "candidates",
    "is_dominant",
    "retrieve",
]

#: Ordering key over txn ids: proximity to the anchor, then id.
_OrderKey = Callable[[str], "tuple[float, str]"]


# --------------------------------------------------------------------------
# Policy surface
# --------------------------------------------------------------------------

class RetrievalPolicy(Protocol):
    """The slice of `DecisionPolicy` that retrieval is allowed to see.

    Structural, not nominal, so this module does not import the decision layer
    that sits above it, and a test can pass a three-field stub. Every number
    retrieval uses lives in the real policy object; there are no thresholds
    here.
    """

    time_window_s: int
    max_candidates: int
    blocking_idf_floor: float


# --------------------------------------------------------------------------
# Blocking-key kinds - stable machine identifiers, they reach the audit trail
# --------------------------------------------------------------------------

KEY_REFERENCE_EXACT = "REF_KEY_EXACT"
KEY_REFERENCE_CONFUSABLE = "REF_KEY_CONFUSABLE"
KEY_REFERENCE_SUFFIX = "REF_KEY_SUFFIX"
KEY_TIME_WINDOW = "TIME_WINDOW"
KEY_AMOUNT_EXACT = "AMOUNT_EXACT"
KEY_AMOUNT_NEIGHBOUR = "AMOUNT_NEIGHBOUR"
KEY_NAME_PHONETIC = "NAME_PHONETIC"

#: The reference tiers widen rather than add information: an all-digit id hits
#: all three. Only the narrowest tier that found a transaction is recorded.
_REFERENCE_KINDS = frozenset(
    {KEY_REFERENCE_EXACT, KEY_REFERENCE_CONFUSABLE, KEY_REFERENCE_SUFFIX}
)

#: Field name and level code the dominance escape hatch keys off (guide 6).
REFERENCE_FIELD = "reference"
REF_EXACT_LEVEL_CODE = "REF_EXACT"

#: Shortest reference tail worth indexing. Below this a "suffix" is a common
#: string shared by thousands of ids, which turns the recall net into a scan.
_REF_SUFFIX_LEN = 6


# --------------------------------------------------------------------------
# IDF over the merchant's own feed (guide 3.3)
# --------------------------------------------------------------------------

# The floor on a common token's weight used to be a module constant here, on the
# argument that blocking is recall-only and therefore not decision-steering.
# That was wrong: which token a name is blocked on decides which transactions
# are ever scored, and a candidate that is never retrieved cannot win. It is
# `DecisionPolicy.blocking_idf_floor` now, so changing it moves the fingerprint.
# It is deliberately a *separate* field from `DecisionPolicy.name_idf_floor`,
# which floors the same quantity for scoring: this one bounds recall, that one
# bounds evidence, and tuning one is not a reason to tune the other.


def build_idf(
    all_names: Iterable[tuple[str, ...]],
    floor: float,
) -> dict[str, float]:
    """Inverse document frequency of name tokens, measured on this feed.

    A matcher that treats every value as equally informative catastrophically
    over-weights common ones: two records agreeing on "Muhammad" is nearly zero
    evidence, two agreeing on "Zulqarnain" is very strong evidence. Here the
    IDF decides which token a name is *blocked* on, so blocking follows the
    distinctive token instead of the ubiquitous one.

    `normalize.COMMON_NAME_TOKENS` is applied as a ceiling, not merely as a
    default, because a tiny feed makes a common name look rare: a merchant
    with three transactions would otherwise "learn" that `muhammad` is
    distinctive and block the whole feed on it. Splink's `tf_minimum_u_value`
    exists for the mirror-image reason. Values are clamped into
    ``[floor, 1.0]``: the floor stops a common token from mattering, the
    ceiling stops a single-occurrence token from dominating.
    """
    if not (0.0 <= floor <= 1.0):
        raise ValueError("floor must be within 0.0..1.0")

    docs = [set(toks) for toks in all_names]
    n = len(docs)
    df = Counter(tok for toks in docs for tok in toks)
    # log(1) == 0: a single-document feed carries no frequency information at
    # all, so fall back to a denominator of 1 rather than dividing by zero.
    denom = math.log(n) if n > 1 else 1.0

    idf = {
        tok: min(1.0, max(floor, math.log(n / (1 + count)) / denom))
        for tok, count in df.items()
    }
    for tok in COMMON_NAME_TOKENS:
        idf[tok] = min(idf.get(tok, floor), floor)
    return idf


# --------------------------------------------------------------------------
# Amount probe keys
# --------------------------------------------------------------------------

#: Digit pairs an OCR engine genuinely confuses on receipt fonts. Kept small
#: and symmetric: every extra pair multiplies the probe set for no measured
#: recall gain.
_CONFUSABLE_DIGITS: Mapping[str, str] = MappingProxyType(
    {
        "0": "8",
        "1": "7",
        "3": "8",
        "4": "9",
        "5": "6",
        "6": "58",
        "7": "1",
        "8": "063",
        "9": "4",
    }
)


def amount_probe_keys(minor: int) -> tuple[int, ...]:
    """OCR-plausible neighbours of an amount, in minor units, excluding itself.

    Two failure modes, both seen on real screenshots:

    * a lost or gained trailing zero (`Rs 1,500` read as `Rs 150`), and
    * exactly one confusable digit.

    The result is bounded by roughly twice the digit count, which keeps the
    union cheap. Neighbours are only ever *probes*: the amount comparison, not
    this function, decides whether two amounts agree.
    """
    minor = abs(minor)
    probes: set[int] = {minor * 10}
    if minor % 10 == 0:
        probes.add(minor // 10)

    digits = str(minor)
    for i, ch in enumerate(digits):
        for repl in _CONFUSABLE_DIGITS.get(ch, ""):
            probes.add(int(digits[:i] + repl + digits[i + 1:]))

    probes.discard(minor)
    return tuple(sorted(probes))


# --------------------------------------------------------------------------
# The index
# --------------------------------------------------------------------------

def _day_bucket(epoch_s: float) -> int:
    """UTC day number since the epoch. Floor division, so pre-1970 works."""
    return math.floor(epoch_s / GRANULARITY_DAY)


def _epoch(dt: datetime) -> float:
    return require_aware(dt).timestamp()


def _freeze(buckets: Mapping[Any, list[str]]) -> Mapping[Any, tuple[str, ...]]:
    """Make a bucket map immutable and its contents deterministically ordered."""
    return MappingProxyType({k: tuple(sorted(v)) for k, v in buckets.items()})


@dataclass(frozen=True, slots=True)
class TxnIndex:
    """Blocking keys for one merchant's feed, built once and reused.

    Every map goes key -> tuple of txn ids rather than key -> transactions, so
    the index stays small and each transaction is materialised exactly once, in
    `by_id`. Build cost is O(feed); every query after that is a handful of dict
    hits plus a sort of what those hits returned.
    """

    by_id: Mapping[str, LedgerTxn]
    by_reference: Mapping[str, tuple[str, ...]]
    by_reference_confusable: Mapping[str, tuple[str, ...]]
    by_reference_suffix: Mapping[str, tuple[str, ...]]
    by_amount: Mapping[tuple[str, int], tuple[str, ...]]
    by_day: Mapping[int, tuple[str, ...]]
    by_name_key: Mapping[str, tuple[str, ...]]
    idf: Mapping[str, float]

    @classmethod
    def build(cls, feed: Iterable[LedgerTxn], *, idf_floor: float) -> TxnIndex:
        """Index a feed under one policy's blocking floor.

        `idf_floor` is required and comes from `DecisionPolicy`: it decides
        which token each name is blocked on, so an index built under one floor
        and queried for a decision taken under another is not the index that
        decision's fingerprint describes. A caller reusing one index across a
        batch must therefore reuse the policy that built it.

        Raises on a duplicate `txn_id`: a feed that repeats an id has no total
        order, and every determinism guarantee in this module rests on
        `txn_id` being unique.
        """
        txns: dict[str, LedgerTxn] = {}
        for txn in feed:
            if txn.txn_id in txns:
                raise ValueError(f"duplicate txn_id in feed: {txn.txn_id!r}")
            txns[txn.txn_id] = txn

        # IDF must exist before name keys are built: *which* token a name is
        # blocked on is a function of the whole feed's token frequencies.
        idf = build_idf(
            (
                normalize_name(name)
                for txn in txns.values()
                for name in (txn.sender_name, txn.receiver_name)
                if name
            ),
            floor=idf_floor,
        )

        refs: dict[str, list[str]] = defaultdict(list)
        refs_conf: dict[str, list[str]] = defaultdict(list)
        refs_suffix: dict[str, list[str]] = defaultdict(list)
        amounts: dict[tuple[str, int], list[str]] = defaultdict(list)
        days: dict[int, list[str]] = defaultdict(list)
        names: dict[str, list[str]] = defaultdict(list)

        for txn_id, txn in txns.items():
            raw_ref = txn.reference_id
            if raw_ref:
                ref = normalize_reference(raw_ref)
                if ref:
                    refs[ref].append(txn_id)
                    refs_conf[reference_confusable_key(raw_ref)].append(txn_id)
                    if len(ref) >= _REF_SUFFIX_LEN:
                        refs_suffix[ref[-_REF_SUFFIX_LEN:]].append(txn_id)

            amounts[(txn.amount.currency, txn.amount.minor)].append(txn_id)
            days[_day_bucket(_epoch(txn.occurred_at))].append(txn_id)

            # Sender and receiver names share one key space. A claim's sender
            # phonetically matching a transaction's receiver is a harmless
            # extra candidate; a missed true match is not. Blocking is recall.
            for name in (txn.sender_name, txn.receiver_name):
                if not name:
                    continue
                for key in name_block_keys(normalize_name(name), idf):
                    names[key].append(txn_id)

        return cls(
            by_id=MappingProxyType(txns),
            by_reference=_freeze(refs),
            by_reference_confusable=_freeze(refs_conf),
            by_reference_suffix=_freeze(refs_suffix),
            by_amount=_freeze(amounts),
            by_day=_freeze(days),
            by_name_key=_freeze(names),
            idf=MappingProxyType(idf),
        )

    def __len__(self) -> int:
        return len(self.by_id)


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Candidates plus enough provenance to explain and to profile retrieval."""

    txns: tuple[LedgerTxn, ...]
    #: txn_id -> the blocking-key kinds that retrieved it, narrowest first.
    #: Only for transactions that survived the cap, so it lines up with `txns`.
    hits: Mapping[str, tuple[str, ...]]
    #: Distinct transactions pulled out of buckets, before the cap. This is the
    #: number that has to stay far below `len(feed)`; it is exposed so
    #: "retrieval is not a scan" is a testable claim rather than a comment.
    examined: int
    truncated: bool
    #: The instant the time window was centred on, and whether it came from
    #: `now` because the claim carried no readable timestamp.
    anchor: datetime
    anchored_on_now: bool

    def txn_ids(self) -> tuple[str, ...]:
        return tuple(t.txn_id for t in self.txns)


def retrieve(
    claim: PaymentClaim,
    feed: Iterable[LedgerTxn] | TxnIndex,
    policy: RetrievalPolicy,
    *,
    now: datetime,
) -> RetrievalResult:
    """Union the blocking keys, narrowest first, and cap at `max_candidates`.

    `feed` may be a prebuilt `TxnIndex`, which is how a caller avoids rebuilding
    the index once per claim when verifying a batch.
    """
    if policy.time_window_s < 0:
        raise ValueError("time_window_s must be >= 0")
    if policy.max_candidates < 1:
        raise ValueError("max_candidates must be >= 1")

    index = (
        feed
        if isinstance(feed, TxnIndex)
        else TxnIndex.build(feed, idf_floor=policy.blocking_idf_floor)
    )
    now = require_aware(now)

    claimed = claim.occurred_at
    anchor = claimed.resolved_utc if claimed is not None else now
    anchor_epoch = _epoch(anchor)

    def order_key(txn_id: str) -> tuple[float, str]:
        """Time proximity to the anchor, ties broken by id.

        A total order over every group, so truncation keeps the most plausible
        members rather than whichever ones the feed happened to list first.
        """
        return (abs(_epoch(index.by_id[txn_id].occurred_at) - anchor_epoch), txn_id)

    limit = policy.max_candidates
    groups: list[tuple[str, tuple[str, ...]]] = [
        *_by_reference(claim, index, order_key),
        (
            KEY_TIME_WINDOW,
            _by_time_window(index, anchor_epoch, policy.time_window_s, claim, order_key),
        ),
        *_by_amount(claim, index, order_key),
        (KEY_NAME_PHONETIC, _by_name_phonetics(claim, index, order_key)),
    ]

    examined: set[str] = set()
    hits: dict[str, list[str]] = {}
    ordered: list[str] = []
    for kind, txn_ids in groups:
        for txn_id in txn_ids:
            examined.add(txn_id)
            if txn_id in hits:
                _record(hits[txn_id], kind)        # another key found it too
            elif len(ordered) < limit:
                hits[txn_id] = [kind]
                ordered.append(txn_id)

    return RetrievalResult(
        txns=tuple(index.by_id[i] for i in ordered),
        hits=MappingProxyType({i: tuple(hits[i]) for i in ordered}),
        examined=len(examined),
        truncated=len(examined) > len(ordered),
        anchor=anchor,
        anchored_on_now=claimed is None,
    )


def candidates(
    claim: PaymentClaim,
    feed: Iterable[LedgerTxn] | TxnIndex,
    policy: RetrievalPolicy,
    *,
    now: datetime,
) -> list[LedgerTxn]:
    """The guide's plain signature: just the candidate transactions."""
    return list(retrieve(claim, feed, policy, now=now).txns)


def _record(kinds: list[str], kind: str) -> None:
    """Add a blocking-key kind to a transaction's provenance, once.

    A widening tier inside the same family (the three reference tiers) adds no
    information over the narrower one that already fired, so it is not
    recorded - the evidence drawer should read "found by transaction id", not
    "found by transaction id three times".
    """
    if kind in kinds:
        return
    if kind in _REFERENCE_KINDS and any(k in _REFERENCE_KINDS for k in kinds):
        return
    kinds.append(kind)


def _tenant_ok(claim: PaymentClaim, txn: LedgerTxn) -> bool:
    """Tenant isolation is the one hard filter in retrieval.

    Provider deliberately is *not* filtered on: a misread provider logo must
    not hide the true transaction, so provider stays a scoring signal. A
    merchant mismatch is different in kind - returning another merchant's
    transaction is a data-leak bug, not a recall trade-off.
    """
    return (
        claim.merchant_id is None
        or txn.merchant_id is None
        or txn.merchant_id == claim.merchant_id
    )


def _collect(
    index: TxnIndex,
    claim: PaymentClaim,
    txn_ids: Iterable[str],
    order_key: _OrderKey,
) -> tuple[str, ...]:
    """Tenant-filter, de-duplicate and order one blocking group.

    Groups are returned whole rather than pre-capped, so `max_candidates` is
    applied once, to the union, and `examined` reports what retrieval actually
    looked at instead of what survived.
    """
    kept = {i for i in txn_ids if _tenant_ok(claim, index.by_id[i])}
    return tuple(sorted(kept, key=order_key))


def _by_reference(
    claim: PaymentClaim,
    index: TxnIndex,
    order_key: _OrderKey,
) -> list[tuple[str, tuple[str, ...]]]:
    """The narrowest key, in three widening tiers.

    Reference hits ignore the time window and the amount entirely: a printed
    transaction id is near-unique evidence, and dropping it because OCR also
    mangled the timestamp is exactly the failure this ordering prevents.
    """
    raw = claim.reference_id
    if not raw:
        return []
    ref = normalize_reference(raw)
    if not ref:
        return []

    tiers: list[tuple[str, tuple[str, ...]]] = [
        (KEY_REFERENCE_EXACT, index.by_reference.get(ref, ())),
        (
            KEY_REFERENCE_CONFUSABLE,
            index.by_reference_confusable.get(reference_confusable_key(raw), ()),
        ),
    ]
    if len(ref) >= _REF_SUFFIX_LEN:
        # Providers print the same id with different prefixes and labels; the
        # tail is the part that survives.
        tiers.append(
            (KEY_REFERENCE_SUFFIX, index.by_reference_suffix.get(ref[-_REF_SUFFIX_LEN:], ()))
        )
    return [(kind, _collect(index, claim, ids, order_key)) for kind, ids in tiers]


def _by_time_window(
    index: TxnIndex,
    anchor_epoch: float,
    window_s: int,
    claim: PaymentClaim,
    order_key: _OrderKey,
) -> tuple[str, ...]:
    """Everything within +/- `window_s` of the anchor, via day buckets.

    The bucket span is normally three days, so this is a handful of dict hits.
    When a policy asks for a window wider than the feed itself spans, iterating
    the index's own day keys is cheaper and gives an identical answer - no
    arbitrary cap, and no unbounded loop over empty days.
    """
    first = _day_bucket(anchor_epoch - window_s)
    last = _day_bucket(anchor_epoch + window_s)
    span = last - first + 1
    day_keys: Iterable[int]
    if span <= len(index.by_day):
        day_keys = range(first, last + 1)
    else:
        day_keys = sorted(d for d in index.by_day if first <= d <= last)

    found = [
        txn_id
        for day in day_keys
        for txn_id in index.by_day.get(day, ())
        if abs(_epoch(index.by_id[txn_id].occurred_at) - anchor_epoch) <= window_s
    ]
    return _collect(index, claim, found, order_key)


def _by_amount(
    claim: PaymentClaim,
    index: TxnIndex,
    order_key: _OrderKey,
) -> list[tuple[str, tuple[str, ...]]]:
    """Exact amount first, then OCR-plausible neighbours as a separate tier."""
    amount = claim.amount
    if amount is None:
        return []
    ccy = amount.currency
    exact = index.by_amount.get((ccy, amount.minor), ())
    neighbours = [
        txn_id
        for probe in amount_probe_keys(amount.minor)
        for txn_id in index.by_amount.get((ccy, probe), ())
    ]
    return [
        (KEY_AMOUNT_EXACT, _collect(index, claim, exact, order_key)),
        (KEY_AMOUNT_NEIGHBOUR, _collect(index, claim, neighbours, order_key)),
    ]


def _by_name_phonetics(
    claim: PaymentClaim,
    index: TxnIndex,
    order_key: _OrderKey,
) -> tuple[str, ...]:
    """The recall net, for claims whose timestamp is missing or inferred.

    Deliberately last: phonetic codes are coarse English-phonology encoders and
    are noisy on transliterated Urdu names. Noisy is acceptable for a key whose
    only job is "do not miss the true match", and fatal for a score.
    """
    keys: set[str] = set()
    for raw in (claim.sender_name, claim.receiver_name):
        if raw:
            keys |= name_block_keys(normalize_name(raw), index.idf)
    if not keys:
        return ()
    found = [txn_id for key in sorted(keys) for txn_id in index.by_name_key.get(key, ())]
    return _collect(index, claim, found, order_key)


# --------------------------------------------------------------------------
# Ranking (guide 6)
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CandidateRanking:
    """Scored candidates in a total, reproducible order.

    Ambiguity is a first-class outcome, not low confidence. A tea shop selling
    a Rs. 250 item takes ten identical Rs. 250 payments an hour; silently
    picking `s1` over an equal `s2` allocates the *wrong* transaction, which
    then trips the allocation uniqueness constraint for the other order and
    surfaces as an incoherent `DUPLICATE` days later. `margin` is what the rule
    table tests in order to refuse that guess.

    Construct with `CandidateRanking.of(...)`, which sorts. The constructor
    validates rather than sorts, so a caller cannot quietly hand the engine an
    order that fell out of a dict.
    """

    scored: tuple[ScoredCandidate, ...] = ()

    def __post_init__(self) -> None:
        keys = [c.sort_key() for c in self.scored]
        if keys != sorted(keys):
            raise ValueError("CandidateRanking.scored must be sorted; use CandidateRanking.of()")
        ids = [c.txn_id for c in self.scored]
        if len(set(ids)) != len(ids):
            # Two entries for one transaction make `margin` meaningless: the
            # runner-up would be the same transaction as the winner.
            raise ValueError(f"duplicate candidate txn_id in ranking: {ids}")

    @classmethod
    def of(cls, cands: Iterable[ScoredCandidate]) -> CandidateRanking:
        """Sort by `(-score, txn_id)`.

        Total, so the ranking is a function of the data alone and never of the
        input list's order. Float ties plus list-sort stability plus a
        dict-ordered candidate list is a reproducibility bug waiting for a demo.
        """
        return cls(scored=tuple(sorted(cands, key=ScoredCandidate.sort_key)))

    @property
    def best(self) -> ScoredCandidate | None:
        return self.scored[0] if self.scored else None

    @property
    def runner_up(self) -> ScoredCandidate | None:
        return self.scored[1] if len(self.scored) > 1 else None

    @property
    def margin(self) -> float:
        """Separation between the winner and the runner-up.

        A lone candidate has nothing to be confused with, so its margin is the
        maximum: the margin rule must never veto an unambiguous match.
        """
        if len(self.scored) < 2:
            return 1.0
        return self.scored[0].score - self.scored[1].score

    @property
    def is_dominant(self) -> bool:
        """See `is_dominant()` - the escape hatch, reachable as a property."""
        return is_dominant(self)

    def __len__(self) -> int:
        return len(self.scored)

    def __bool__(self) -> bool:
        return bool(self.scored)

    def txn_ids(self) -> tuple[str, ...]:
        return tuple(c.txn_id for c in self.scored)


def is_dominant(ranking: CandidateRanking) -> bool:
    """True when exactly one candidate matched the reference id exactly **and
    that candidate is the one that won**.

    The margin rule exists to protect against *interchangeable* candidates. A
    unique exact transaction id means they are not interchangeable, so such a
    match may win regardless of margin - but only for the candidate that
    actually carries the id. Dominance that ignored rank would let an unrelated
    row deep in the ranking (wrong amount, hours away, different name, but a
    reference that happens to collide with the claim's) switch off the
    ambiguity rule for two interchangeable payments at the top, and the engine
    would then name and allocate one of them. Rank is therefore part of the
    definition, not an assumption about it.

    `.get` rather than `[...]`: a candidate scored before the reference
    comparison ran simply has no opinion here, and a missing opinion must not
    raise inside a decision.
    """
    exact = [
        c
        for c in ranking.scored
        if (outcome := c.outcomes.get(REFERENCE_FIELD)) is not None
        and outcome.level_code == REF_EXACT_LEVEL_CODE
    ]
    if len(exact) != 1:
        return False
    winner = ranking.best
    return winner is not None and exact[0].txn_id == winner.txn_id
