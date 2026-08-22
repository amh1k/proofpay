"""Transaction reuse: detected and explained here, enforced by the database.

The distinction these tests exist to pin down is *whose* order already holds
the transaction. Another order means the customer is reusing a payment. The
same order means somebody refreshed the page. Collapsing the two would turn
idempotency into a fraud accusation, so it gets its own test rather than a
comment.
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta

import pytest

from proofpay.core.duplicates import (
    AllocationConflict,
    check_candidate,
    check_ranking,
    index_allocations,
)
from proofpay.core.models import Allocation, LedgerTxn, ScoredCandidate
from proofpay.core.money import Money
from proofpay.core.reasons import ReasonCode
from proofpay.core.retrieval import CandidateRanking
from proofpay.core.timex import UTC

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def scored(txn_id: str, score: float) -> ScoredCandidate:
    return ScoredCandidate(
        txn=LedgerTxn(txn_id=txn_id, amount=Money(150_000), occurred_at=NOW),
        score=score,
    )


def alloc(txn_id: str, order_id: str, *, at: datetime | None = NOW, vid: str | None = None):
    return Allocation(txn_id=txn_id, order_id=order_id, allocated_at=at, verification_id=vid)


# --------------------------------------------------------------------------
# check_candidate
# --------------------------------------------------------------------------

def test_a_free_transaction_has_no_conflict():
    index = index_allocations([])
    assert len(index) == 0
    assert check_candidate("T1", order_id="O1", allocations=index) is None


def test_a_transaction_held_by_another_order_conflicts():
    index = index_allocations([alloc("T1", "O_other", vid="V9")])
    conflict = check_candidate("T1", order_id="O1", allocations=index)
    assert conflict == AllocationConflict(
        txn_id="T1",
        allocated_to_order_id="O_other",
        allocated_at=NOW,
        verification_id="V9",
    )
    assert conflict.reason is ReasonCode.TXN_ALREADY_ALLOCATED


def test_a_transaction_held_by_this_same_order_is_idempotency_not_reuse():
    index = index_allocations([alloc("T1", "O1")])
    assert check_candidate("T1", order_id="O1", allocations=index) is None


def test_an_orderless_claim_treats_any_existing_allocation_as_reuse():
    # No order means there is no "same order" to be idempotent about.
    index = index_allocations([alloc("T1", "O1")])
    conflict = check_candidate("T1", order_id=None, allocations=index)
    assert conflict is not None
    assert conflict.allocated_to_order_id == "O1"


def test_allocations_for_other_transactions_are_ignored():
    index = index_allocations([alloc("T2", "O_other"), alloc("T3", "O_other")])
    assert check_candidate("T1", order_id="O1", allocations=index) is None


# --------------------------------------------------------------------------
# Contested input — the database forbids it, a stale read can still show it
# --------------------------------------------------------------------------

def test_the_earliest_allocation_wins_when_a_transaction_shows_two():
    index = index_allocations(
        [
            alloc("T1", "O_late", at=NOW),
            alloc("T1", "O_early", at=NOW - timedelta(hours=3)),
        ]
    )
    assert index.for_txn("T1").order_id == "O_early"
    assert index.contested == frozenset({"T1"})


def test_contested_allocations_without_timestamps_still_resolve_deterministically():
    rows = [alloc("T1", "O_b", at=None), alloc("T1", "O_a", at=None)]
    rng = random.Random(3)
    for _ in range(10):
        rng.shuffle(rows)
        assert index_allocations(rows).for_txn("T1").order_id == "O_a"


def test_a_well_formed_allocation_set_is_not_contested():
    index = index_allocations([alloc("T1", "O1"), alloc("T2", "O2")])
    assert index.contested == frozenset()


# --------------------------------------------------------------------------
# check_ranking
# --------------------------------------------------------------------------

def test_the_best_candidate_being_taken_is_what_the_rule_table_reads():
    ranking = CandidateRanking.of([scored("T1", 0.95), scored("T2", 0.60)])
    report = check_ranking(
        ranking, order_id="O1", allocations=index_allocations([alloc("T1", "O_other")])
    )
    assert report.best_is_allocated_elsewhere is True
    assert report.best_conflict.allocated_to_order_id == "O_other"
    assert report.reasons == (ReasonCode.TXN_ALREADY_ALLOCATED,)
    assert report.free_txn_ids == ("T2",)


def test_a_taken_runner_up_is_history_not_a_reason():
    ranking = CandidateRanking.of([scored("T1", 0.95), scored("T2", 0.60)])
    report = check_ranking(
        ranking, order_id="O1", allocations=index_allocations([alloc("T2", "O_other")])
    )
    assert report.best_is_allocated_elsewhere is False
    assert report.reasons == ()
    assert report.free_txn_ids == ("T1",)
    assert [c.txn_id for c in report.conflicts] == ["T2"]


def test_every_candidate_taken_leaves_nothing_free():
    ranking = CandidateRanking.of([scored("T1", 0.95), scored("T2", 0.90)])
    report = check_ranking(
        ranking,
        order_id="O1",
        allocations=index_allocations([alloc("T1", "O_x"), alloc("T2", "O_y")]),
    )
    assert report.free_txn_ids == ()
    assert [c.allocated_to_order_id for c in report.conflicts] == ["O_x", "O_y"]


def test_conflicts_follow_ranking_order():
    ranking = CandidateRanking.of([scored("T1", 0.95), scored("T2", 0.90), scored("T3", 0.85)])
    report = check_ranking(
        ranking,
        order_id="O1",
        allocations=index_allocations([alloc("T3", "O_z"), alloc("T2", "O_y")]),
    )
    assert [c.txn_id for c in report.conflicts] == ["T2", "T3"]


def test_re_verifying_the_same_order_reports_nothing():
    ranking = CandidateRanking.of([scored("T1", 0.95)])
    report = check_ranking(
        ranking, order_id="O1", allocations=index_allocations([alloc("T1", "O1")])
    )
    assert report.best_is_allocated_elsewhere is False
    assert report.conflicts == ()
    assert report.free_txn_ids == ("T1",)


def test_an_empty_ranking_produces_an_empty_report():
    report = check_ranking(
        CandidateRanking(), order_id="O1", allocations=index_allocations([alloc("T1", "O_x")])
    )
    assert report.conflicts == ()
    assert report.best_conflict is None
    assert report.best_is_allocated_elsewhere is False
    assert report.reasons == ()


def test_a_contested_candidate_is_surfaced_for_review():
    ranking = CandidateRanking.of([scored("T1", 0.95)])
    report = check_ranking(
        ranking,
        order_id="O1",
        allocations=index_allocations(
            [alloc("T1", "O_a", at=NOW), alloc("T1", "O_b", at=NOW + timedelta(minutes=1))]
        ),
    )
    assert report.contested_txn_ids == ("T1",)
    assert report.best_conflict.allocated_to_order_id == "O_a"


def test_shuffling_the_allocation_rows_never_changes_the_report():
    rows = [alloc(f"T{i}", f"O_{i}", at=NOW + timedelta(minutes=i)) for i in range(6)]
    ranking = CandidateRanking.of([scored(f"T{i}", 0.9 - i / 100) for i in range(6)])
    rng = random.Random(11)
    baseline = check_ranking(ranking, order_id="O_none", allocations=index_allocations(rows))
    for _ in range(15):
        rng.shuffle(rows)
        assert check_ranking(
            ranking, order_id="O_none", allocations=index_allocations(rows)
        ) == baseline


def test_the_report_is_frozen():
    report = check_ranking(CandidateRanking(), order_id="O1", allocations=index_allocations([]))
    with pytest.raises(FrozenInstanceError):
        report.best_conflict = None      # type: ignore[misc]
