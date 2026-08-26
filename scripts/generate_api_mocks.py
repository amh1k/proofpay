"""Generate frontend mock data by running the REAL pipeline over the REAL receipts.

Track D builds its UI against mocks. If those mocks are hand-written they drift
from what the API actually returns, and the mismatch surfaces on the day the two
are connected — which is the worst possible day to find it.

So nothing here is authored. Each mock verification is produced by handing one
committed receipt image to the same three calls `POST /verifications` makes —
`_extract_claim`, `decide`, `verification_result_from_decision` — for the same
demo order the merchant would have picked. Whatever the UI renders correctly
here, it will render correctly against the live API, because it IS the live
response.

Three files come out of here:

    verifications.json  the five demo orders, each checked against its own
                        committed receipt, decided for real
    dashboard.json      the counts of those five
    orders.json         the five orders the merchant picks between, PROJECTED
                        out of `proofpay.api.engine_demo` — the same module the
                        live API projects `GET /orders` from

WHY THE VERIFICATIONS ARE TIED TO THE ORDERS, AND NOT MERELY TO THE VERDICTS:

    engine_demo._CASES ──> stub_data.STUB_ORDERS ──┬──> GET /orders
            │                                      └──> orders.json  (the picker)
            │
            └──> decide(receipt, case) ───────────────> verifications.json

    Mock mode has nothing to read a screenshot WITH, so `submitClaim` replays a
    stored verification. It finds the one whose `order_id` is the order the
    merchant chose — so the answer on screen is that order's own answer.

    These fixtures used to be five unrelated scenarios (ORD-1041, ORD-1042, …)
    matched to the picker by VERDICT alone, and the money did not survive the
    join: choosing "ORD-G01 · Rs 1,500" replayed a Rs 2,000 VERIFIED check and
    told the merchant, in projector type, that an order expecting Rs 1,500 had
    been paid in full. In the one product whose whole thesis is that the
    merchant's expected amount is the trusted record, that is not a cosmetic
    mismatch. Deriving both sides from `engine_demo` makes it unrepresentable.

Run from the backend directory, so the backend's own environment is on the path:

    cd backend && uv run python ../scripts/generate_api_mocks.py
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

from proofpay.api.engine_demo import demo_case_for
from proofpay.api.v1.stub_data import STUB_ORDERS
from proofpay.api.verification_service import _extract_claim
from proofpay.api.verification_mapper import verification_result_from_decision
from proofpay.core.decide import DecisionPolicy, decide
from proofpay.demo.clock import PINNED_ANCHOR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "src" / "mocks"
RECEIPTS = ROOT / "fixtures" / "demo" / "images"

# The merchant every demo principal belongs to (`api/v1/auth.py`). The claim and
# the ledger have to be scoped to the same one or the engine sees a proof from a
# stranger.
MERCHANT_ID = "merchant_demo_001"

POLICY = DecisionPolicy()

# Time is pinned, exactly as the endpoint pins it: mock data that moves with the
# wall clock goes stale overnight and makes "but it worked yesterday" a sentence
# someone has to say on stage.
EVALUATED_AT = PINNED_ANCHOR.astimezone(UTC)


# ── the five demo receipts ─────────────────────────────────────────────────────
#
# Which committed screenshot the customer sent for which order, and the verdict
# the engine reaches for that pair.
#
# The verdict is NOT decided here. `build` below runs the real engine and stops
# the generation if the engine disagrees with this table, which makes the table a
# CHECK rather than a claim — the same check, on the same five pairs, that
# `backend/tests/api/test_engine_integration.py` pins. It is written down at all
# for one reason: the verification id has to be stable across regenerations
# (`ver_suspicious` is what the demo rail replays), and a name is only stable if
# it does not depend on what the engine happened to answer this time.
DEMO_RECEIPTS: list[dict[str, str]] = [
    {
        "order_id": "order_demo_1001",
        "image": "G01.jpg",
        "status": "VERIFIED",
        "note": "Genuine payment. Every field agrees and the money is in the feed.",
    },
    {
        "order_id": "order_demo_1002",
        "image": "S01.jpg",
        "status": "SUSPICIOUS",
        "note": "The screenshot claims Rs 5,000; Rs 500 arrived. The flagship demo.",
    },
    {
        "order_id": "order_demo_1003",
        "image": "D01.jpg",
        "status": "DUPLICATE",
        "note": "A real transaction, already spent on an earlier order.",
    },
    {
        "order_id": "order_demo_1004",
        "image": "N01.jpg",
        "status": "NEEDS_REVIEW",
        "note": "Rs 1,200 arrived against a Rs 1,500 order. A person decides this one.",
    },
    {
        "order_id": "order_demo_1005",
        "image": "U01.jpg",
        "status": "UNMATCHED",
        "note": "Nothing corresponds to this claim. NOT fraud - it may still be settling.",
    },
]


def build(receipt: dict[str, str]) -> dict:
    """Run one receipt against its order, the way the endpoint does, and dump it.

    The three calls below are the body of `POST /verifications` with the HTTP
    peeled off. Nothing is re-implemented, so there is no second copy of the
    mapping to keep in step — a field renamed in `verification_mapper` changes
    the mocks the next time this runs, instead of silently leaving them behind.
    """
    verification_id = f"ver_{receipt['status'].lower()}"
    image = RECEIPTS / receipt["image"]
    if not image.is_file():
        raise SystemExit(f"no committed receipt at {image} — cannot check {receipt['order_id']}")

    claim = _extract_claim(
        image.read_bytes(),
        verification_id=verification_id,
        merchant_id=MERCHANT_ID,
    )
    case = demo_case_for(receipt["order_id"], MERCHANT_ID)
    decision = decide(
        claim,
        case.order,
        case.ledger,
        case.allocations,
        now=EVALUATED_AT,
        policy=POLICY,
        # Explicitly empty, and it matters. Mock generation is five INDEPENDENT
        # decisions, not one merchant's session, so no proof accumulates from
        # one receipt to the next. G01.jpg and D01.jpg are byte-identical, so a
        # generator that carried a proof store between them would write a
        # DUPLICATE mock for order_demo_1001 -- the frontend would then ship a
        # verdict the live API never produces.
        prior_proofs=(),
    )
    result = verification_result_from_decision(
        decision,
        claim=claim,
        order=case.order,
        ledger=case.ledger,
        verification_id=verification_id,
        created_at=EVALUATED_AT,
    )

    if str(result.status) != receipt["status"]:
        raise SystemExit(
            f"{receipt['image']} on {receipt['order_id']} now decides "
            f"{result.status}, not {receipt['status']}: either the pairing is "
            "wrong or the engine changed. Fix DEMO_RECEIPTS before shipping a "
            "mock whose verdict no longer matches the live one."
        )

    payload = result.model_dump(mode="json")
    # Not part of the wire shape, and deliberately prefixed: a reader opening
    # the mock needs to know which story each fixture tells, and the adapter
    # ignores anything it was not told to read.
    payload["_note"] = receipt["note"]
    return payload


def orders_payload() -> dict:
    """`GET /orders` as the live API returns it, and nothing more.

    The rows are dumped from `STUB_ORDERS` itself rather than rebuilt here, so
    the mock and the live response come out of ONE projection. Rebuilding the
    same fields in this script would restore exactly the drift that deriving
    `STUB_ORDERS` was meant to remove, one file further downstream.

    There is no replay table beside them any more. The mock replay is found by
    matching the chosen order against each fixture's own `order_id`, which is a
    fact the engine put there — a hand-kept table saying which order produces
    which verdict was the last place the picker and the answer could disagree.
    """
    return {
        "items": [order.model_dump(mode="json") for order in STUB_ORDERS],
        "total": len(STUB_ORDERS),
    }


def check_every_order_is_answerable(results: list[dict]) -> None:
    """Fail if any order in the picker has no fixture behind it, or two do.

    Mock mode replays by `order_id`. An order with no fixture is a button that
    can be chosen and then cannot be answered; two fixtures for one order is a
    coin toss over which verdict the room sees.
    """
    answered = [result["order_id"] for result in results]
    duplicates = sorted({o for o in answered if answered.count(o) > 1})
    if duplicates:
        raise SystemExit(f"more than one fixture answers for {duplicates}")

    missing = sorted({order.id for order in STUB_ORDERS} - set(answered))
    if missing:
        raise SystemExit(
            f"no fixture to replay for {missing} — those orders would sit in the "
            "picker with nothing honest to show in mock mode"
        )


def verifications_payload(results: list[dict]) -> dict:
    """`GET /verifications` as the list endpoint envelopes it."""
    return {"items": results, "total": len(results)}


def dashboard_payload(results: list[dict]) -> dict:
    """The dashboard tiles, COUNTED from the five decisions rather than typed.

    Six numbers is few enough to write out by hand, which is exactly why they
    would drift: nothing goes red when a fixture's verdict moves and the tile
    above it still reads what last year's verdict was.
    """
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1

    return {
        "checked_today": len(results),
        "verified": counts.get("VERIFIED", 0),
        "unmatched": counts.get("UNMATCHED", 0),
        "suspicious": counts.get("SUSPICIOUS", 0),
        "duplicate": counts.get("DUPLICATE", 0),
        "needs_review": counts.get("NEEDS_REVIEW", 0),
    }


def rendered(payload: dict) -> str:
    """The exact text `write` puts on disk.

    Split out from `write` so a test can rebuild a mock and compare it to the
    committed bytes without reaching for a temporary directory — and so the
    indent and the trailing newline have one definition rather than two.
    """
    return json.dumps(payload, indent=2) + "\n"


def write(name: str, payload: dict) -> None:
    # The mocks live in the frontend tree, which is LF throughout. Without an
    # explicit newline, `write_text` on Windows rewrites every line of all three
    # files to CRLF and buries a real regeneration inside a whole-file diff.
    (OUT / name).write_text(rendered(payload), encoding="utf-8", newline="\n")


def main() -> None:
    results = [build(receipt) for receipt in DEMO_RECEIPTS]
    check_every_order_is_answerable(results)

    OUT.mkdir(parents=True, exist_ok=True)
    write("verifications.json", verifications_payload(results))
    write("orders.json", orders_payload())
    write("dashboard.json", dashboard_payload(results))

    by_id = {order.id: order for order in STUB_ORDERS}
    for result in results:
        order = by_id[result["order_id"]]
        print(
            f"  {result['status']:<13} rule={result['fired_rule_id']:<5} "
            f"{order.external_order_ref:<8} {order.expected_amount_minor:>8}  {result['id']}"
        )

    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
