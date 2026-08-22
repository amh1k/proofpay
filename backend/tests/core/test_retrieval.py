"""Retrieval must find the true transaction, stay bounded, and never wobble.

Three properties are load-bearing and each has tests that assert values rather
than truthiness:

1. **Recall.** Any one blocking key alone is enough. Every test here kills all
   the other keys (wrong amount, timestamp weeks away, no name) so the key
   under test is provably the one that found the transaction.
2. **Boundedness.** `examined` proves retrieval touched a handful of the feed,
   not all of it.
3. **Determinism.** Shuffling the feed must not change one id or one hit kind.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from proofpay.core.compare.levels import Agreement, FieldOutcome
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.models import LedgerTxn, PaymentClaim, ScoredCandidate
from proofpay.core.money import Money
from proofpay.core.retrieval import (
    KEY_AMOUNT_EXACT,
    KEY_AMOUNT_NEIGHBOUR,
    KEY_NAME_PHONETIC,
    KEY_REFERENCE_CONFUSABLE,
    KEY_REFERENCE_EXACT,
    KEY_REFERENCE_SUFFIX,
    KEY_TIME_WINDOW,
    CandidateRanking,
    RetrievalResult,
    TxnIndex,
    amount_probe_keys,
    build_idf,
    candidates,
    is_dominant,
    retrieve,
)
from proofpay.core.timex import UTC, ClaimedInstant

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Policy:
    """A `RetrievalPolicy` stub — structural typing means no import upward."""

    time_window_s: int = 86_400
    max_candidates: int = 25
    blocking_idf_floor: float = 0.15


#: The floor on a common token's blocking weight is `DecisionPolicy` now, not a
#: constant in `retrieval`: which token a name is blocked on decides which
#: transactions are ever scored, and a candidate that is never retrieved cannot
#: win, so it has to reach the fingerprint like every other steering number.
COMMON_NAME_IDF = DecisionPolicy().blocking_idf_floor


def txn(
    txn_id: str,
    *,
    minor: int = 150_000,
    at: datetime = NOW,
    external_id: str | None = None,
    sender: str | None = None,
    receiver: str | None = None,
    merchant_id: str | None = "m1",
) -> LedgerTxn:
    return LedgerTxn(
        txn_id=txn_id,
        amount=Money(minor),
        occurred_at=at,
        merchant_id=merchant_id,
        external_id=external_id,
        sender_name=sender,
        receiver_name=receiver,
    )


def claim_at(offset_s: int = 0, **kw) -> PaymentClaim:
    """A claim whose readable timestamp sits `offset_s` from NOW."""
    return PaymentClaim(
        claim_id="c1",
        merchant_id="m1",
        occurred_at=ClaimedInstant(resolved_utc=NOW + timedelta(seconds=offset_s)),
        **kw,
    )


def ids(result: RetrievalResult) -> tuple[str, ...]:
    return result.txn_ids()


# --------------------------------------------------------------------------
# build_idf
# --------------------------------------------------------------------------

def test_idf_floors_a_common_token_and_rewards_a_rare_one():
    idf = build_idf(
        [("muhammad", "ali"), ("muhammad", "zulqarnain"), ("fatima", "noor")],
        floor=COMMON_NAME_IDF,
    )
    assert idf["muhammad"] == COMMON_NAME_IDF
    assert idf["zulqarnain"] == pytest.approx(0.369, abs=1e-3)
    assert idf["noor"] == pytest.approx(0.369, abs=1e-3)
    # Rarer than "muhammad" *in this feed*, but still a name half the country
    # shares: the seed list overrides the measurement, not the other way round.
    assert idf["ali"] == COMMON_NAME_IDF


def test_idf_seeds_exist_even_for_an_empty_feed():
    idf = build_idf([], floor=COMMON_NAME_IDF)
    assert idf["khan"] == COMMON_NAME_IDF
    assert "zulqarnain" not in idf          # unknown -> name_block_keys uses 1.0


def test_idf_survives_a_single_document_feed():
    # log(1) == 0 would divide by zero on the guide's raw formula.
    idf = build_idf([("zulqarnain", "haider")], floor=COMMON_NAME_IDF)
    assert idf["zulqarnain"] == COMMON_NAME_IDF
    assert all(COMMON_NAME_IDF <= v <= 1.0 for v in idf.values())


def test_idf_rejects_an_out_of_range_floor():
    with pytest.raises(ValueError):
        build_idf([("ali",)], floor=1.5)


# --------------------------------------------------------------------------
# amount probes
# --------------------------------------------------------------------------

def test_amount_probes_cover_a_lost_and_a_gained_trailing_zero():
    probes = amount_probe_keys(15_000)
    assert 150_000 in probes          # OCR dropped a zero from Rs 1,500
    assert 1_500 in probes            # OCR gained one
    assert 15_000 not in probes       # never probes itself


def test_amount_probes_cover_one_confusable_digit():
    probes = amount_probe_keys(150_000)
    assert 160_000 in probes          # 5 read as 6
    assert 750_000 in probes          # 1 read as 7
    assert len(probes) <= 2 * len(str(150_000)) + 2   # stays small


def test_amount_probes_handle_zero_without_looping():
    assert amount_probe_keys(0) == (8,)


# --------------------------------------------------------------------------
# Reference blocking — the narrowest key, and immune to time/amount conflict
# --------------------------------------------------------------------------

def test_reference_hit_survives_a_wrong_amount_and_a_month_of_time_drift():
    feed = [txn("T1", external_id="EP-1234-5678", minor=999, at=NOW - timedelta(days=30))]
    claim = claim_at(reference_id="TID: EP12345678", amount=Money(150_000))
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert ids(result) == ("T1",)
    # An all-digit id also matches the confusable and suffix tiers; only the
    # narrowest tier that fired is recorded.
    assert result.hits["T1"] == (KEY_REFERENCE_EXACT,)


def test_reference_hit_survives_ocr_letter_digit_confusion():
    feed = [txn("T1", external_id="AB1O23456", at=NOW - timedelta(days=30), minor=1)]
    claim = claim_at(reference_id="AB1023456")          # O read as zero
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert result.hits["T1"] == (KEY_REFERENCE_CONFUSABLE,)


def test_reference_suffix_recovers_a_truncated_id():
    feed = [txn("T1", external_id="EP-2026-778899", at=NOW - timedelta(days=30), minor=1)]
    claim = claim_at(reference_id="778899")             # only the tail was legible
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert result.hits["T1"] == (KEY_REFERENCE_SUFFIX,)


def test_a_short_reference_never_becomes_a_suffix_key():
    # A 4-char "suffix" would be shared by thousands of ids.
    feed = [txn("T1", external_id="EP-2026-778899", at=NOW - timedelta(days=30), minor=1)]
    claim = claim_at(reference_id="8899")
    assert retrieve(claim, feed, Policy(), now=NOW).txns == ()


def test_reference_ranks_ahead_of_the_time_window_in_the_union():
    feed = [
        txn("T_far", external_id="EP-1234-5678", at=NOW - timedelta(days=30), minor=1),
        txn("T_near", at=NOW, minor=1),
    ]
    result = retrieve(claim_at(reference_id="EP12345678"), feed, Policy(), now=NOW)
    assert ids(result) == ("T_far", "T_near")     # narrowest key first


# --------------------------------------------------------------------------
# Time window
# --------------------------------------------------------------------------

def test_time_window_boundary_is_inclusive():
    policy = Policy(time_window_s=1_800)
    feed = [
        txn("T_in", at=NOW + timedelta(seconds=1_800), minor=1),
        txn("T_out", at=NOW + timedelta(seconds=1_801), minor=1),
    ]
    claim = PaymentClaim(
        claim_id="c1",
        merchant_id="m1",
        occurred_at=ClaimedInstant(resolved_utc=NOW),
    )
    assert ids(retrieve(claim, feed, policy, now=NOW)) == ("T_in",)


def test_time_window_spans_day_buckets_in_both_directions():
    policy = Policy(time_window_s=86_400)
    feed = [
        txn("T_prev", at=NOW - timedelta(hours=20), minor=1),
        txn("T_next", at=NOW + timedelta(hours=20), minor=1),
        txn("T_gone", at=NOW + timedelta(hours=30), minor=1),
    ]
    claim = PaymentClaim(
        claim_id="c1", merchant_id="m1", occurred_at=ClaimedInstant(resolved_utc=NOW)
    )
    assert sorted(ids(retrieve(claim, feed, policy, now=NOW))) == ["T_next", "T_prev"]


def test_a_window_wider_than_the_feed_falls_back_to_the_index_day_keys():
    # 10 years of window over a 2-day feed: iterating 3650 empty buckets would
    # be silly, and the answer must be identical either way.
    policy = Policy(time_window_s=10 * 365 * 86_400)
    feed = [txn("T1", at=NOW - timedelta(days=400), minor=1), txn("T2", at=NOW, minor=1)]
    claim = PaymentClaim(
        claim_id="c1", merchant_id="m1", occurred_at=ClaimedInstant(resolved_utc=NOW)
    )
    result = retrieve(claim, feed, policy, now=NOW)
    assert ids(result) == ("T2", "T1")            # nearest to the anchor first


def test_a_claim_with_no_timestamp_anchors_on_now():
    feed = [txn("T_recent", at=NOW - timedelta(hours=2), minor=1)]
    claim = PaymentClaim(claim_id="c1", merchant_id="m1")
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert result.anchored_on_now is True
    assert result.anchor == NOW
    assert ids(result) == ("T_recent",)


# --------------------------------------------------------------------------
# Amount
# --------------------------------------------------------------------------

def test_amount_finds_a_transaction_far_outside_the_time_window():
    feed = [txn("T1", minor=150_000, at=NOW - timedelta(days=10))]
    claim = claim_at(amount=Money(150_000))
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert result.hits["T1"] == (KEY_AMOUNT_EXACT,)


def test_amount_neighbour_recovers_a_dropped_trailing_zero():
    feed = [txn("T1", minor=150_000, at=NOW - timedelta(days=10))]
    claim = claim_at(amount=Money(15_000))          # Rs 1,500 read as Rs 150
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert result.hits["T1"] == (KEY_AMOUNT_NEIGHBOUR,)


def test_exact_amount_precedes_a_neighbour_in_the_union():
    at = NOW - timedelta(days=10)
    feed = [txn("T_near_miss", minor=160_000, at=at), txn("T_exact", minor=150_000, at=at)]
    result = retrieve(claim_at(amount=Money(150_000)), feed, Policy(), now=NOW)
    assert ids(result) == ("T_exact", "T_near_miss")


def test_amount_keys_are_currency_scoped():
    # A PKR claim must never collide with another currency's minor units.
    index = TxnIndex.build([txn("T1", minor=150_000)], idf_floor=COMMON_NAME_IDF)
    assert ("PKR", 150_000) in index.by_amount


# --------------------------------------------------------------------------
# Name phonetics — the recall net
# --------------------------------------------------------------------------

def test_name_phonetics_recovers_a_claim_with_no_time_and_no_amount():
    feed = [txn("T1", sender="Zulqarnain Haider", at=NOW - timedelta(days=40), minor=1)]
    claim = PaymentClaim(claim_id="c1", merchant_id="m1", sender_name="zulqarnain haider")
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert result.hits["T1"] == (KEY_NAME_PHONETIC,)


def test_name_phonetics_tolerates_a_transliteration_variant():
    feed = [txn("T1", sender="Zulqarnain Hyder", at=NOW - timedelta(days=40), minor=1)]
    claim = PaymentClaim(claim_id="c1", merchant_id="m1", sender_name="Zulqarnain Haider")
    assert ids(retrieve(claim, feed, Policy(), now=NOW)) == ("T1",)


def test_an_unreadable_name_is_simply_no_key_not_a_crash():
    feed = [txn("T1", sender="Zulqarnain Haider", at=NOW - timedelta(days=40), minor=1)]
    claim = PaymentClaim(claim_id="c1", merchant_id="m1", sender_name="محمد")
    assert retrieve(claim, feed, Policy(), now=NOW).txns == ()


# --------------------------------------------------------------------------
# Degradation and isolation
# --------------------------------------------------------------------------

def test_a_claim_with_nothing_but_an_id_still_returns_recent_transactions():
    feed = [txn("T1", at=NOW - timedelta(hours=1)), txn("T2", at=NOW - timedelta(days=9))]
    result = retrieve(PaymentClaim(claim_id="c1"), feed, Policy(), now=NOW)
    assert ids(result) == ("T1",)
    assert result.hits["T1"] == (KEY_TIME_WINDOW,)


def test_a_reference_that_normalises_to_nothing_is_simply_no_key():
    # OCR read the label but not the id. That is a missing field, not a query
    # for every transaction whose reference is the empty string.
    feed = [txn("T1", external_id="EP12345678", at=NOW - timedelta(days=30), minor=1)]
    assert retrieve(claim_at(reference_id="TID:"), feed, Policy(), now=NOW).txns == ()


def test_another_merchants_transaction_is_never_returned():
    feed = [txn("T_theirs", external_id="EP12345678", merchant_id="m2")]
    claim = claim_at(reference_id="EP12345678")
    assert retrieve(claim, feed, Policy(), now=NOW).txns == ()


def test_an_unattributed_transaction_is_returned_because_the_feed_is_scoped():
    feed = [txn("T1", external_id="EP12345678", merchant_id=None)]
    claim = claim_at(reference_id="EP12345678")
    assert ids(retrieve(claim, feed, Policy(), now=NOW)) == ("T1",)


def test_a_provider_mismatch_does_not_hide_the_transaction():
    # A misread wallet logo must not cost the true match.
    feed = [txn("T1", external_id="EP12345678")]
    claim = PaymentClaim(
        claim_id="c1", merchant_id="m1", provider="jazzcash", reference_id="EP12345678"
    )
    assert ids(retrieve(claim, feed, Policy(), now=NOW)) == ("T1",)


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------

def test_max_candidates_keeps_the_transactions_nearest_the_anchor():
    feed = [txn(f"T{i:02d}", at=NOW + timedelta(minutes=i), minor=1) for i in range(20)]
    claim = PaymentClaim(
        claim_id="c1", merchant_id="m1", occurred_at=ClaimedInstant(resolved_utc=NOW)
    )
    result = retrieve(claim, feed, Policy(max_candidates=5), now=NOW)
    assert ids(result) == ("T00", "T01", "T02", "T03", "T04")
    assert result.truncated is True


def test_retrieval_examines_a_handful_not_the_feed():
    feed = [
        txn(f"T{i:05d}", at=NOW - timedelta(hours=i), minor=100 + i, external_id=f"EP{i:06d}")
        for i in range(5_000)
    ]
    # Anchored a year before the feed begins, so the time window contributes
    # nothing and the reference key is provably the only thing that fired.
    claim = claim_at(offset_s=-400 * 86_400, reference_id="EP004242")
    result = retrieve(claim, feed, Policy(), now=NOW)
    assert ids(result) == ("T04242",)
    # The whole point of blocking: finding one transaction must not touch 5 000.
    assert result.examined == 1


def test_policy_bounds_are_validated():
    with pytest.raises(ValueError):
        retrieve(PaymentClaim(claim_id="c1"), [], Policy(max_candidates=0), now=NOW)
    with pytest.raises(ValueError):
        retrieve(PaymentClaim(claim_id="c1"), [], Policy(time_window_s=-1), now=NOW)


def test_a_naive_now_is_refused():
    with pytest.raises(ValueError):
        retrieve(PaymentClaim(claim_id="c1"), [], Policy(), now=datetime(2026, 5, 1, 12, 0))


def test_a_repeated_txn_id_is_a_feed_bug_not_a_silent_overwrite():
    with pytest.raises(ValueError, match="duplicate txn_id"):
        TxnIndex.build([txn("T1"), txn("T1", minor=1)], idf_floor=COMMON_NAME_IDF)


def test_a_prebuilt_index_is_accepted_and_gives_the_same_answer():
    feed = [txn("T1", external_id="EP12345678"), txn("T2", at=NOW - timedelta(days=9))]
    claim = claim_at(reference_id="EP12345678")
    index = TxnIndex.build(feed, idf_floor=COMMON_NAME_IDF)
    assert len(index) == 2
    assert ids(retrieve(claim, index, Policy(), now=NOW)) == ids(
        retrieve(claim, feed, Policy(), now=NOW)
    )


def test_candidates_returns_plain_transactions():
    feed = [txn("T1", external_id="EP12345678")]
    got = candidates(claim_at(reference_id="EP12345678"), feed, Policy(), now=NOW)
    assert [t.txn_id for t in got] == ["T1"]
    assert isinstance(got[0], LedgerTxn)


def test_a_transaction_found_by_several_keys_records_all_of_them():
    feed = [txn("T1", external_id="EP12345678", minor=150_000, at=NOW)]
    claim = claim_at(reference_id="EP12345678", amount=Money(150_000))
    hits = retrieve(claim, feed, Policy(), now=NOW).hits["T1"]
    assert hits == (KEY_REFERENCE_EXACT, KEY_TIME_WINDOW, KEY_AMOUNT_EXACT)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

def _mixed_feed() -> list[LedgerTxn]:
    """A feed engineered so every tiebreak matters: identical timestamps,
    identical amounts, shared name tokens."""
    names = ["Ali Raza", "Muhammad Ali", "Fatima Noor", "Zulqarnain Haider"]
    feed: list[LedgerTxn] = []
    for i in range(40):
        feed.append(
            txn(
                f"T{i:02d}",
                minor=150_000 if i % 3 else 15_000,
                at=NOW - timedelta(minutes=(i % 5) * 30),   # deliberate ties
                external_id=f"EP{i % 7:06d}",               # deliberate collisions
                sender=names[i % len(names)],
            )
        )
    return feed


def test_shuffling_the_feed_never_changes_the_ranking():
    claim = claim_at(
        reference_id="EP000003",
        amount=Money(150_000),
        sender_name="Muhammad Ali",
    )
    policy = Policy(max_candidates=10)
    baseline = retrieve(claim, _mixed_feed(), policy, now=NOW)

    rng = random.Random(20260501)
    for _ in range(25):
        shuffled = _mixed_feed()
        rng.shuffle(shuffled)
        result = retrieve(claim, shuffled, policy, now=NOW)
        assert ids(result) == ids(baseline)
        assert dict(result.hits) == dict(baseline.hits)
        assert result.examined == baseline.examined

    assert len(baseline.txns) == 10       # the shuffle actually had room to matter


# --------------------------------------------------------------------------
# CandidateRanking
# --------------------------------------------------------------------------

def scored(txn_id: str, score: float, *, ref_level: str | None = None) -> ScoredCandidate:
    outcomes = {}
    if ref_level is not None:
        outcomes["reference"] = FieldOutcome(
            field="reference",
            level_code=ref_level,
            label="ref",
            score=1.0,
            # Dominance keys off the level *code*; the declared meaning is
            # irrelevant to it, and AGREE is the honest value for a rung these
            # tests only ever populate with a reference that matched.
            agreement=Agreement.AGREE,
        )
    return ScoredCandidate(txn=txn(txn_id), score=score, outcomes=outcomes)


def test_ranking_sorts_by_score_then_id():
    ranking = CandidateRanking.of([scored("b", 0.90), scored("a", 0.90), scored("c", 0.95)])
    assert ranking.txn_ids() == ("c", "a", "b")
    assert ranking.best.txn_id == "c"
    assert ranking.runner_up.txn_id == "a"


def test_ranking_is_immune_to_input_order():
    cands = [scored("d", 0.5), scored("a", 0.9), scored("c", 0.9), scored("b", 0.7)]
    rng = random.Random(7)
    expected = CandidateRanking.of(cands).txn_ids()
    for _ in range(20):
        rng.shuffle(cands)
        assert CandidateRanking.of(cands).txn_ids() == expected
    assert expected == ("a", "c", "b", "d")


def test_margin_measures_the_gap_to_the_runner_up():
    ranking = CandidateRanking.of([scored("a", 0.95), scored("b", 0.90), scored("c", 0.10)])
    assert ranking.margin == pytest.approx(0.05)


def test_a_lone_candidate_has_the_maximum_margin():
    assert CandidateRanking.of([scored("a", 0.83)]).margin == 1.0


def test_an_empty_ranking_is_falsy_and_has_no_best():
    empty = CandidateRanking()
    assert empty.best is None
    assert empty.runner_up is None
    assert empty.margin == 1.0
    assert len(empty) == 0
    assert not empty


def test_the_constructor_refuses_an_unsorted_tuple():
    with pytest.raises(ValueError, match="must be sorted"):
        CandidateRanking(scored=(scored("a", 0.10), scored("b", 0.90)))


def test_the_constructor_refuses_a_repeated_candidate():
    with pytest.raises(ValueError, match="duplicate candidate"):
        CandidateRanking.of([scored("a", 0.90), scored("a", 0.80)])


def test_dominance_needs_exactly_one_exact_reference_match():
    ranking = CandidateRanking.of(
        [scored("a", 0.90, ref_level="REF_EXACT"), scored("b", 0.89, ref_level="REF_MISSING")]
    )
    assert is_dominant(ranking) is True
    assert ranking.is_dominant is True
    assert ranking.margin < 0.10            # dominance is what overrides this


def test_dominance_requires_the_exact_reference_match_to_be_the_winner():
    """A bystander holding the printed id does not make the ranking decidable.

    Dominance is the escape hatch that lets a unique exact transaction id win
    regardless of margin, and it is only ever true of the candidate that *has*
    the id. Counting `REF_EXACT` candidates anywhere in the ranking let an
    obviously unrelated row - wrong amount, hours away, a different name, and a
    score to match - switch the margin rule off for two interchangeable
    payments above it, which the engine would then name one of.
    """
    ranking = CandidateRanking.of(
        [
            scored("a", 0.90, ref_level="REF_PARTIAL"),
            scored("b", 0.90, ref_level="REF_PARTIAL"),
            scored("z", 0.35, ref_level="REF_EXACT"),
        ]
    )
    assert ranking.best.txn_id == "a"
    assert ranking.margin == 0.0
    assert is_dominant(ranking) is False
    assert ranking.is_dominant is False


def test_dominance_holds_when_the_winner_is_the_exact_reference_match():
    """The other side of the same rule: the escape hatch must still open."""
    ranking = CandidateRanking.of(
        [
            scored("a", 0.90, ref_level="REF_EXACT"),
            scored("b", 0.90, ref_level="REF_PARTIAL"),
        ]
    )
    assert ranking.best.txn_id == "a"
    assert ranking.margin == 0.0
    assert is_dominant(ranking) is True


def test_two_exact_reference_matches_are_not_dominant():
    ranking = CandidateRanking.of(
        [scored("a", 0.90, ref_level="REF_EXACT"), scored("b", 0.89, ref_level="REF_EXACT")]
    )
    assert is_dominant(ranking) is False


def test_no_exact_reference_match_is_not_dominant():
    ranking = CandidateRanking.of([scored("a", 0.90, ref_level="REF_CONFUSABLE")])
    assert is_dominant(ranking) is False


def test_a_candidate_scored_before_the_reference_comparison_ran_does_not_raise():
    ranking = CandidateRanking.of([scored("a", 0.90), scored("b", 0.80)])
    assert is_dominant(ranking) is False


def test_an_empty_ranking_is_not_dominant():
    assert is_dominant(CandidateRanking()) is False
