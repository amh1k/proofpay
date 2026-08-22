"""The frozen contracts: keyword-only, immutable, and honest about absence."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from proofpay.core.compare.levels import FieldOutcome
from proofpay.core.models import (
    Allocation,
    Decision,
    LedgerTxn,
    Order,
    PaymentClaim,
    ScoredCandidate,
)
from proofpay.core.money import Money
from proofpay.core.reasons import ReasonCode, Risk, Source, Status
from proofpay.core.timex import UTC, ClaimedInstant

FIXED_NOW = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)


def _txn(txn_id: str = "T1", minor: int = 150_000, **kw) -> LedgerTxn:
    return LedgerTxn(txn_id=txn_id, amount=Money(minor), occurred_at=FIXED_NOW, **kw)


class TestPaymentClaim:
    def test_unread_fields_are_none_not_defaults(self):
        claim = PaymentClaim(claim_id="C1")
        assert claim.amount is None
        assert claim.sender_name is None
        assert claim.occurred_at is None
        assert claim.reference_id is None

    def test_is_keyword_only(self):
        with pytest.raises(TypeError):
            PaymentClaim("C1")  # type: ignore[misc]

    def test_is_frozen_and_slotted(self):
        claim = PaymentClaim(claim_id="C1")
        with pytest.raises(FrozenInstanceError):
            claim.claim_id = "C2"  # type: ignore[misc]
        # slots: no instance __dict__, so a typo cannot invent a field.
        assert not hasattr(claim, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            claim.typo_field = 1  # type: ignore[attr-defined]

    def test_confidence_defaults_to_certain_when_unreported(self):
        # An extractor that reports nothing must not be penalised.
        claim = PaymentClaim(claim_id="C1", field_confidences={"amount": 0.4})
        assert claim.confidence_for("amount") == 0.4
        assert claim.confidence_for("sender_name") == 1.0

    def test_carries_parse_notes(self):
        claim = PaymentClaim(claim_id="C1", notes=("AMOUNT_SEPARATOR_AMBIGUOUS",))
        assert "AMOUNT_SEPARATOR_AMBIGUOUS" in claim.notes

    def test_holds_a_claimed_instant_not_a_datetime(self):
        claim = PaymentClaim(
            claim_id="C1", occurred_at=ClaimedInstant(resolved_utc=FIXED_NOW, date_inferred=True)
        )
        assert claim.occurred_at.date_inferred is True


class TestLedgerTxn:
    def test_defaults_to_merchant_ledger_provenance(self):
        assert _txn().source is Source.MERCHANT_LEDGER

    def test_reference_id_prefers_the_provider_id(self):
        assert _txn(external_id="EP9001").reference_id == "EP9001"
        assert _txn().reference_id == "T1"

    def test_amount_is_required(self):
        with pytest.raises(TypeError):
            LedgerTxn(txn_id="T1", occurred_at=FIXED_NOW)  # type: ignore[call-arg]


class TestOrder:
    def test_expected_amount_may_be_absent(self):
        # No order attached: claim and ledger can still be compared, but the
        # engine cannot assert the order is fully paid.
        assert Order(order_id="O1").expected is None

    def test_expected_is_money(self):
        assert Order(order_id="O1", expected=Money(150_000)).expected.minor == 150_000


class TestAllocation:
    def test_links_a_txn_to_an_order(self):
        allocation = Allocation(txn_id="T1", order_id="O9")
        assert (allocation.txn_id, allocation.order_id) == ("T1", "O9")


class TestScoredCandidate:
    def test_sort_key_ranks_by_score_then_id(self):
        low = ScoredCandidate(txn=_txn("T2"), score=0.5)
        high = ScoredCandidate(txn=_txn("T1"), score=0.9)
        assert sorted([low, high], key=ScoredCandidate.sort_key) == [high, low]

    def test_ties_break_on_txn_id_for_determinism(self):
        b = ScoredCandidate(txn=_txn("T2"), score=0.9)
        a = ScoredCandidate(txn=_txn("T1"), score=0.9)
        assert [c.txn_id for c in sorted([b, a], key=ScoredCandidate.sort_key)] == ["T1", "T2"]

    def test_evidence_is_ordered_deterministically(self):
        outcomes = {
            "timestamp": FieldOutcome(field="timestamp", level_code="TS_TIGHT", label="x", score=1.0),
            "amount": FieldOutcome(field="amount", level_code="AMT_EXACT", label="y", score=1.0),
        }
        candidate = ScoredCandidate(txn=_txn(), score=1.0, outcomes=outcomes)
        assert [e.field for e in candidate.evidence] == ["amount", "timestamp"]


class TestDecision:
    def _decision(self, **kw) -> Decision:
        base: dict[str, object] = {
            "status": Status.VERIFIED,
            "risk": Risk.LOW,
            "confidence": 0.91,
            "reasons": (ReasonCode.STRONG_FIELD_AGREEMENT,),
            "matched_txn_id": "T1",
            "fired_rule_id": "R090",
            "evidence": (),
            "observations": (),
            "ruleset_version": "rules-v1.3.0",
            "policy_fingerprint": "deadbeefdeadbeef",
            "engine_version": "engine-1.0.0",
            "evaluated_at": FIXED_NOW,
        }
        base.update(kw)
        return Decision(**base)  # type: ignore[arg-type]

    def test_carries_everything_needed_to_replay_it(self):
        decision = self._decision()
        assert decision.ruleset_version == "rules-v1.3.0"
        assert decision.policy_fingerprint == "deadbeefdeadbeef"
        assert decision.evaluated_at == FIXED_NOW

    def test_verified_without_a_matched_txn_is_impossible(self):
        # No screenshot-derived signal alone establishes that payment occurred.
        with pytest.raises(ValueError, match="VERIFIED requires"):
            self._decision(matched_txn_id=None)

    def test_unmatched_without_a_txn_is_fine(self):
        decision = self._decision(
            status=Status.UNMATCHED,
            risk=Risk.MEDIUM,
            matched_txn_id=None,
            reasons=(ReasonCode.NO_CANDIDATES,),
            fired_rule_id="R010",
        )
        assert decision.status is Status.UNMATCHED

    @pytest.mark.parametrize("confidence", [-0.01, 1.01])
    def test_confidence_must_be_a_unit_interval(self, confidence):
        with pytest.raises(ValueError):
            self._decision(confidence=confidence)

    def test_evidence_by_field(self):
        outcome = FieldOutcome(field="amount", level_code="AMT_EXACT", label="Exact", score=1.0)
        decision = self._decision(evidence=(outcome,))
        assert decision.evidence_by_field()["amount"] is outcome

    def test_reason_codes_serialise_as_plain_strings(self):
        assert self._decision().reasons[0] == "STRONG_FIELD_AGREEMENT"
