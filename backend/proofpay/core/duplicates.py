"""Transaction-reuse detection: pure observation, never enforcement.

One trusted transaction pays for one order. The **database** enforces that - a
partial unique index on `merchant_transaction_id` where the allocation is
active, written inside the same transaction as the accepting decision, so two
concurrent verifications cannot both consume the same payment. That constraint
is Phase 2 and it is the actual guarantee.

This module does something narrower and complementary: given the allocations a
caller has already read, it *detects and explains* that a candidate is spoken
for, early enough that the engine can return `DUPLICATE` with a reason a human
can act on instead of surfacing a raw integrity error. Detection here is
advisory and can be stale; the constraint is authoritative and never is.

The distinction that carries all the weight:

* allocated **to another order** - the customer is reusing a payment, and the
  merchant must not ship twice. `TXN_ALREADY_ALLOCATED`, `DUPLICATE`.
* allocated **to this same order** - a re-submitted screenshot, a retried
  request, a page refresh. Not fraud, not a duplicate: the order is simply
  already paid by exactly the transaction the claim points at. Reporting that
  as `DUPLICATE` turns idempotency into an accusation.

Screenshot reuse (`PROOF_REUSED`) is a separate signal, computed from proof
hashes rather than allocations, and is not implemented here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from proofpay.core.models import Allocation
from proofpay.core.reasons import ReasonCode
from proofpay.core.retrieval import CandidateRanking

__all__ = [
    "AllocationConflict",
    "AllocationIndex",
    "DuplicateReport",
    "check_candidate",
    "check_ranking",
    "index_allocations",
]

#: Sorts before every real timestamp, so an allocation that never recorded one
#: still orders deterministically and still loses to one that did.
_EPOCH = datetime(1, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class AllocationConflict:
    """One candidate transaction, already consumed by a different order.

    Carries the *other* order's id because that is the only actionable thing a
    merchant can be told: "this payment already paid order #1183".
    """

    txn_id: str
    #: The order that already holds this transaction. Never the order under
    #: verification - that case is idempotency, not a conflict.
    allocated_to_order_id: str
    allocated_at: datetime | None = None
    verification_id: str | None = None

    @property
    def reason(self) -> ReasonCode:
        return ReasonCode.TXN_ALREADY_ALLOCATED


@dataclass(frozen=True, slots=True)
class AllocationIndex:
    """Active allocations, keyed by the transaction they consumed.

    The database permits at most one active allocation per transaction, so this
    map is one-to-one *when the input is well formed*. When it is not - a stale
    read straddling a release, a caller that passed released rows - the
    earliest allocation wins, mirroring the first-writer-wins behaviour of the
    unique index. Silently picking an arbitrary one instead would make a
    `DUPLICATE` verdict depend on dict ordering.
    """

    by_txn: Mapping[str, Allocation]
    #: Transaction ids that arrived with more than one allocation. A non-empty
    #: set means the caller's view of allocations disagrees with the database's
    #: invariant; the engine may treat it as a review trigger.
    contested: frozenset[str] = frozenset()

    def for_txn(self, txn_id: str) -> Allocation | None:
        return self.by_txn.get(txn_id)

    def __len__(self) -> int:
        return len(self.by_txn)


def _allocation_order(alloc: Allocation) -> tuple[datetime, str, str]:
    """Total order over allocations: earliest first, then order id, then id.

    Total rather than merely sorted-by-time, because two allocations written in
    the same millisecond must still resolve the same way on every replay.
    """
    return (alloc.allocated_at or _EPOCH, alloc.order_id, alloc.verification_id or "")


def index_allocations(allocations: Iterable[Allocation]) -> AllocationIndex:
    """Group allocations by transaction, resolving conflicts deterministically.

    Callers pass only *active* allocations; a released one has given its
    transaction back and must not be presented as a conflict. This layer has no
    way to tell the difference (the core `Allocation` carries no status), so the
    filtering is the adapter's job and is documented here rather than guessed
    at.
    """
    grouped: dict[str, list[Allocation]] = {}
    for alloc in allocations:
        grouped.setdefault(alloc.txn_id, []).append(alloc)

    winners = {
        txn_id: min(allocs, key=_allocation_order)
        for txn_id, allocs in grouped.items()
    }
    contested = frozenset(txn_id for txn_id, allocs in grouped.items() if len(allocs) > 1)
    return AllocationIndex(by_txn=MappingProxyType(winners), contested=contested)


def check_candidate(
    txn_id: str,
    *,
    order_id: str | None,
    allocations: AllocationIndex,
) -> AllocationConflict | None:
    """Is this transaction already consumed by a *different* order?

    `order_id is None` - a proof submitted with no order attached - means there
    is no "same order" to be idempotent about, so any existing allocation is a
    conflict.
    """
    alloc = allocations.for_txn(txn_id)
    if alloc is None:
        return None
    if order_id is not None and alloc.order_id == order_id:
        return None                      # idempotent re-verification, not reuse
    return AllocationConflict(
        txn_id=txn_id,
        allocated_to_order_id=alloc.order_id,
        allocated_at=alloc.allocated_at,
        verification_id=alloc.verification_id,
    )


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    """What allocation state says about a whole ranking.

    The engine needs more than a boolean on the winner. When the best candidate
    is taken but the runner-up is free, that is a genuinely different situation
    from every candidate being taken: the first often means the matcher picked
    the wrong one of several identical payments, the second means the customer
    is reusing a receipt. `free_txn_ids` is what lets a later stage tell those
    apart without re-deriving the allocation state.
    """

    #: Conflicts in ranking order, so `conflicts[0]` concerns the best
    #: candidate when there is one.
    conflicts: tuple[AllocationConflict, ...] = ()
    best_conflict: AllocationConflict | None = None
    #: Candidates with no conflict, in ranking order.
    free_txn_ids: tuple[str, ...] = ()
    #: Candidates whose allocation state was self-contradictory in the input.
    contested_txn_ids: tuple[str, ...] = ()

    @property
    def best_is_allocated_elsewhere(self) -> bool:
        """The predicate the rule table's `R020` reads."""
        return self.best_conflict is not None

    @property
    def reasons(self) -> tuple[ReasonCode, ...]:
        """Reason codes for the *decision*, which only the winner can justify.

        A taken runner-up is not a reason to reject anything - it is ordinary
        history - so it never contributes a code.
        """
        if self.best_conflict is None:
            return ()
        return (ReasonCode.TXN_ALREADY_ALLOCATED,)


def check_ranking(
    ranking: CandidateRanking,
    *,
    order_id: str | None,
    allocations: AllocationIndex,
) -> DuplicateReport:
    """Allocation state for every candidate, in ranking order."""
    conflicts: list[AllocationConflict] = []
    free: list[str] = []
    contested: list[str] = []

    for cand in ranking.scored:
        txn_id = cand.txn_id
        if txn_id in allocations.contested:
            contested.append(txn_id)
        conflict = check_candidate(txn_id, order_id=order_id, allocations=allocations)
        if conflict is None:
            free.append(txn_id)
        else:
            conflicts.append(conflict)

    best = ranking.best
    best_conflict = None
    if best is not None and conflicts and conflicts[0].txn_id == best.txn_id:
        best_conflict = conflicts[0]

    return DuplicateReport(
        conflicts=tuple(conflicts),
        best_conflict=best_conflict,
        free_txn_ids=tuple(free),
        contested_txn_ids=tuple(contested),
    )
