"""Generate frontend mock data from the REAL verification engine.

Track D builds its UI against mocks. If those mocks are hand-written they drift
from what the API actually returns, and the mismatch surfaces on the day the two
are connected — which is the worst possible day to find it.

So these are produced by running `proofpay.core.decide()` for real. Whatever the
UI renders correctly here, it will render correctly against the live API.

Run from the backend directory:

    cd backend && uv run python ../scripts/generate_api_mocks.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from proofpay.core.decide import DecisionPolicy, decide
from proofpay.core.explain import explain
from proofpay.core.models import Allocation, LedgerTxn, Order, PaymentClaim
from proofpay.core.money import Money
from proofpay.core.timex import PKT, ClaimedInstant

OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "mocks"

# A fixed anchor. Mock data that moves with the wall clock goes stale overnight,
# and makes "but it worked yesterday" a sentence someone actually has to say.
NOW = datetime(2026, 8, 20, 16, 0, tzinfo=PKT)
POLICY = DecisionPolicy()


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 20, hour, minute, tzinfo=PKT).astimezone(timezone.utc)


def claimed(hour: int, minute: int) -> ClaimedInstant:
    return ClaimedInstant.from_local(
        datetime(2026, 8, 20, hour, minute, tzinfo=PKT), granularity_s=60
    )


def scenarios() -> list[dict]:
    """One scenario per verification state, mirroring docs/overview.md section 8."""
    return [
        {
            "key": "verified",
            "note": "Genuine payment. Every field agrees.",
            "claim": PaymentClaim(
                claim_id="clm_verified",
                amount=Money.from_major("2000"),
                sender_name="Bilal Ahmed Khan",
                reference_id="EP2481009",
                occurred_at=claimed(10, 22),
            ),
            "order": Order(order_id="ORD-1041", expected=Money.from_major("2000")),
            "ledger": [
                LedgerTxn(
                    txn_id="EP2481009",
                    amount=Money.from_major("2000"),
                    occurred_at=at(10, 22),
                    sender_name="Bilal Ahmed Khan",
                    provider="easypaisa",
                ),
            ],
            "allocations": [],
        },
        {
            "key": "suspicious",
            "note": "The screenshot claims Rs 5,000; Rs 500 arrived. The flagship demo.",
            "claim": PaymentClaim(
                claim_id="clm_suspicious",
                amount=Money.from_major("5000"),
                sender_name="Muhammad Ali",
                reference_id="JC7730114",
                occurred_at=claimed(15, 42),
            ),
            "order": Order(order_id="ORD-1042", expected=Money.from_major("5000")),
            "ledger": [
                LedgerTxn(
                    txn_id="JC7730114",
                    amount=Money.from_major("500"),
                    occurred_at=at(15, 42),
                    sender_name="M. Ali",
                    provider="jazzcash",
                ),
            ],
            "allocations": [],
        },
        {
            "key": "duplicate",
            "note": "A real transaction, already used to pay for a different order.",
            "claim": PaymentClaim(
                claim_id="clm_duplicate",
                amount=Money.from_major("3000"),
                sender_name="Sara Khan",
                reference_id="EP2481103",
                occurred_at=claimed(10, 43),
            ),
            "order": Order(order_id="ORD-1145", expected=Money.from_major("3000")),
            "ledger": [
                LedgerTxn(
                    txn_id="EP2481103",
                    amount=Money.from_major("3000"),
                    occurred_at=at(10, 43),
                    sender_name="Sara Khan",
                    provider="easypaisa",
                ),
            ],
            "allocations": [Allocation(txn_id="EP2481103", order_id="ORD-0041")],
        },
        {
            "key": "needs_review",
            "note": "Two transactions match equally well; the receipt's ID is unreadable.",
            "claim": PaymentClaim(
                claim_id="clm_needs_review",
                amount=Money.from_major("250"),
                sender_name="Muhammad Ali",
                occurred_at=claimed(14, 0),
            ),
            "order": Order(order_id="ORD-1150", expected=Money.from_major("250")),
            "ledger": [
                LedgerTxn(
                    txn_id="EP2481200",
                    amount=Money.from_major("250"),
                    occurred_at=at(14, 0),
                    sender_name="Muhammad Ali",
                    provider="easypaisa",
                ),
                LedgerTxn(
                    txn_id="EP2481201",
                    amount=Money.from_major("250"),
                    occurred_at=at(14, 0),
                    sender_name="Muhammad Ali",
                    provider="easypaisa",
                ),
            ],
            "allocations": [],
        },
        {
            "key": "unmatched",
            "note": "Nothing corresponds to this claim. NOT fraud - it may still be settling.",
            "claim": PaymentClaim(
                claim_id="clm_unmatched",
                amount=Money.from_major("1750"),
                sender_name="Ayesha Siddiqui",
                reference_id="RA9910044",
                occurred_at=claimed(9, 5),
            ),
            "order": Order(order_id="ORD-1151", expected=Money.from_major("1750")),
            "ledger": [],
            "allocations": [],
        },
    ]


def _claimed_value(field: str, claim: PaymentClaim) -> str | None:
    if field == "amount":
        return f"Rs {claim.amount.as_major_str}" if claim.amount else None
    if field == "sender_name":
        return claim.sender_name
    if field == "reference":
        return claim.reference_id
    if field == "timestamp":
        return claim.occurred_at.resolved_utc.isoformat() if claim.occurred_at else None
    return None


def _recorded_value(field: str, txn: LedgerTxn | None) -> str | None:
    if txn is None:
        return None
    if field == "amount":
        return f"Rs {txn.amount.as_major_str}"
    if field == "sender_name":
        return txn.sender_name
    if field == "reference":
        return txn.reference_id
    if field == "timestamp":
        return txn.occurred_at.isoformat()
    return None


def to_api_shape(index: int, sc: dict) -> dict:
    decision = decide(
        sc["claim"], sc["order"], sc["ledger"], sc["allocations"], now=NOW, policy=POLICY
    )
    view = explain(decision, claim=sc["claim"], order=sc["order"])
    txn = next((t for t in sc["ledger"] if t.txn_id == decision.matched_txn_id), None)
    created = (NOW - timedelta(minutes=index * 7 + 3)).astimezone(timezone.utc)

    return {
        "id": f"ver_{sc['key']}",
        "order_id": sc["order"].order_id,
        "status": str(decision.status),
        "stage": "COMPLETE",
        "risk": str(decision.risk),
        "confidence": decision.confidence,
        "claim": {
            "id": sc["claim"].claim_id,
            "provider": sc["claim"].provider,
            "amount_minor": sc["claim"].amount.minor if sc["claim"].amount else None,
            "currency": "PKR",
            "sender_name": sc["claim"].sender_name,
            "reference_id": sc["claim"].reference_id,
            "occurred_at": (
                sc["claim"].occurred_at.resolved_utc.isoformat()
                if sc["claim"].occurred_at
                else None
            ),
        },
        "matched_transaction": (
            {
                "id": txn.txn_id,
                "provider": txn.provider,
                "amount_minor": txn.amount.minor,
                "currency": "PKR",
                "sender_name": txn.sender_name,
                "occurred_at": txn.occurred_at.isoformat(),
            }
            if txn
            else None
        ),
        "matched_txn_id": decision.matched_txn_id,
        "reasons": [str(r) for r in decision.reasons],
        "summary": view.summary,
        "fired_rule_id": decision.fired_rule_id,
        "evidence": [
            {
                "field": e.field,
                "level_code": e.level_code,
                "label": e.label,
                "score": round(e.score, 4),
                "agreement": str(e.agreement),
                "claimed_value": _claimed_value(e.field, sc["claim"]),
                "recorded_value": _recorded_value(e.field, txn),
            }
            for e in decision.evidence
        ],
        "observations": list(decision.observations),
        "recommended_action": view.recommended_action,
        "ruleset_version": decision.ruleset_version,
        "policy_fingerprint": decision.policy_fingerprint,
        "engine_version": decision.engine_version,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "created_at": created.isoformat(),
        "degraded": False,
        "_note": sc["note"],
    }


def main() -> None:
    results = [to_api_shape(i, sc) for i, sc in enumerate(scenarios())]
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "verifications.json").write_text(
        json.dumps({"items": results, "total": len(results)}, indent=2) + "\n",
        encoding="utf-8",
    )

    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1

    (OUT / "dashboard.json").write_text(
        json.dumps(
            {
                "checked_today": len(results),
                "verified": counts.get("VERIFIED", 0),
                "unmatched": counts.get("UNMATCHED", 0),
                "suspicious": counts.get("SUSPICIOUS", 0),
                "duplicate": counts.get("DUPLICATE", 0),
                "needs_review": counts.get("NEEDS_REVIEW", 0),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    for result in results:
        print(f"  {result['status']:<13} rule={result['fired_rule_id']:<5} {result['id']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
