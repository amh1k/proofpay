"""`PROOF_REUSED` through the whole stack: upload -> store -> engine -> JSON.

The engine half of screenshot reuse is covered by `tests/core/test_proofs.py`
and by the `R025` rows in `scenarios.yaml`. This file covers the half those
cannot see: that the API actually hashes the upload, actually reads the
merchant's proof history, actually hands it to `decide()`, and actually carries
the finding out to the shape the frontend consumes. A rule nothing can reach is
not a feature, and every one of those four steps is a place the wiring could be
missing while `core` stayed perfectly green.

It also pins the three behaviours the live demo depends on, which are properties
of the RECORDING RULE rather than of the rule table: that a refused submission is
never remembered, that a receipt nobody approved is never remembered either, and
that re-sending a receipt to the same order is not an accusation.
`fixtures/demo/images/G01.jpg` and `D01.jpg` are byte-identical, so without the
first of those the five-order demo would change verdicts depending on the order
the presenter clicked in.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from proofpay.adapters import proof_store
from proofpay.main import create_app

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "demo" / "images"

MERCHANT_ID = "merchant_demo_001"


def client() -> TestClient:
    return TestClient(create_app())


def auth(token: str = "stub-access-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def submit(app_client: TestClient, order_id: str, image: str, key: str):
    path = FIXTURES / image
    return app_client.post(
        "/api/v1/verifications",
        headers={**auth(), "Idempotency-Key": key},
        data={"order_id": order_id},
        files={"screenshot": (image, path.read_bytes(), "image/jpeg")},
    )


def approve(app_client: TestClient, verification_id: str):
    """The merchant releases the goods. Through the real route, never the store.

    Checking is not accepting, so every test that wants a proof in the history
    has to say so here -- which is the point. Reaching into `record_accepted`
    instead would be testing a store nothing calls.
    """
    return app_client.post(f"/api/v1/verifications/{verification_id}/approve", headers=auth())


def submit_and_approve(app_client: TestClient, order_id: str, image: str, key: str):
    body = submit(app_client, order_id, image, key).json()
    approve(app_client, body["id"])
    return body


# ==========================================================================
# The wiring
# ==========================================================================


def test_what_the_endpoint_remembers_is_the_bytes_and_nothing_else() -> None:
    """The first link in the chain: content, not filename and not id.

    `proof_id` names the submission -- a fresh uuid per upload -- and changes
    every time; the reuse signal is entirely the content hash, which does not.
    Uploading the identical bytes under a different filename must therefore
    produce the identical record, or the whole feature is keyed on something a
    customer can change by renaming a file.

    Asserted against the store rather than against the response body on purpose:
    the digest is plumbing, not something a merchant is owed on screen, so it is
    deliberately not on the API contract.
    """
    payload = (FIXTURES / "G01.jpg").read_bytes()
    digest = proof_store.content_sha256(payload)
    app_client = client()

    response = app_client.post(
        "/api/v1/verifications",
        headers={**auth(), "Idempotency-Key": "hash-1"},
        data={"order_id": "order_demo_1001"},
        files={"screenshot": ("renamed-by-the-customer.jpg", payload, "image/jpeg")},
    )

    assert response.status_code == 201
    approve(app_client, response.json()["id"])
    assert [p.sha256 for p in proof_store.prior_proofs(MERCHANT_ID)] == [digest]
    assert digest != proof_store.content_sha256((FIXTURES / "S01.jpg").read_bytes())


def test_a_verified_proof_is_remembered_and_a_refused_one_is_not() -> None:
    """The recording rule, asserted directly rather than inferred from a verdict.

    Only a VERIFIED decision consumed anything, so only a VERIFIED decision may
    make the next submission of those bytes a duplicate. `adapters/proof_store.py`
    explains why relaxing this breaks the demo.
    """
    app_client = client()

    submit_and_approve(app_client, "order_demo_1001", "G01.jpg", "record-verified")
    submit_and_approve(app_client, "order_demo_1002", "S01.jpg", "record-suspicious")
    submit_and_approve(app_client, "order_demo_1005", "U01.jpg", "record-unmatched")

    remembered = {p.sha256: p.order_id for p in proof_store.prior_proofs(MERCHANT_ID)}

    assert remembered == {
        proof_store.content_sha256((FIXTURES / "G01.jpg").read_bytes()): "order_demo_1001"
    }


def test_a_receipt_nobody_approved_is_never_held_against_the_next_order() -> None:
    """The mis-pick, which used to end in an accusation against an honest customer.

    A shop with two open orders of the same value -- the ordinary case for a
    single-product seller -- picks the wrong one, sees VERIFIED, backs out
    without approving, and re-checks the same receipt against the right order.
    When the proof was written four lines after `decide()`, that second check
    came back DUPLICATE / PROOF_REUSED and told the merchant to ask the customer
    for a fresh payment. Nothing had been counted, allocated or approved: the
    accusation was manufactured entirely by the merchant's own mis-click.

    The two submissions here carry different idempotency keys, so this is
    genuinely two decisions rather than one replayed response.
    """
    app_client = client()

    first = submit(app_client, "order_demo_1001", "G01.jpg", "mispick-1").json()
    assert first["status"] == "VERIFIED"
    assert proof_store.prior_proofs(MERCHANT_ID) == ()

    second = submit(app_client, "order_demo_1001", "G01.jpg", "mispick-2").json()

    assert second["status"] == "VERIFIED"
    assert "PROOF_REUSED" not in second["reasons"]


def test_approving_is_what_spends_the_screenshot() -> None:
    """The other half of the rule: once approved, the image really is spent.

    Without this the test above could be satisfied by never recording anything
    at all, and screenshot reuse would be a feature the live path cannot reach.

    It also pins WHICH NAME is stored. `order_ref` is the merchant's own label
    for the order, and it is the only half of the record they can look up: the
    reuse note publishes it, and a row reading "already used for
    order_demo_1001" points at an id that appears nowhere in their order list.
    """
    app_client = client()

    body = submit(app_client, "order_demo_1001", "G01.jpg", "spend-1").json()
    assert proof_store.prior_proofs(MERCHANT_ID) == ()

    assert approve(app_client, body["id"]).status_code == 204

    remembered = {p.sha256: p.order_ref for p in proof_store.prior_proofs(MERCHANT_ID)}
    assert remembered == {
        proof_store.content_sha256((FIXTURES / "G01.jpg").read_bytes()): "ORD-G01"
    }


def test_approving_twice_and_approving_nothing_are_both_quiet() -> None:
    """A double tap on approve is not an error, and neither is an unknown id.

    Answering 404 would also hand any caller a way to probe which verification
    ids exist.
    """
    app_client = client()
    body = submit(app_client, "order_demo_1001", "G01.jpg", "idem-1").json()

    assert approve(app_client, body["id"]).status_code == 204
    assert approve(app_client, body["id"]).status_code == 204
    assert approve(app_client, "verification_never_existed").status_code == 204

    assert len(proof_store.prior_proofs(MERCHANT_ID)) == 1


def test_the_same_screenshot_sent_to_a_second_order_comes_back_duplicate() -> None:
    """The feature, end to end, in the shape the frontend reads.

    The history is seeded through the store's own front door rather than by
    submitting to a second demo order, because the five demo orders cannot
    express this between themselves: the only other order whose feed holds
    EP0000011 is order_demo_1003, and that one carries an allocation, so `R020`
    would answer first and this rule would never be exercised. Seeding is the
    honest way to say "an earlier order already used this picture" -- it is
    exactly what the endpoint itself writes on a VERIFIED decision, and the
    engine is reached through the real route either way.
    """
    app_client = client()
    digest = proof_store.content_sha256((FIXTURES / "G01.jpg").read_bytes())
    proof_store.record_accepted(MERCHANT_ID, sha256=digest, order_id="order_demo_0999")

    body = submit(app_client, "order_demo_1001", "G01.jpg", "reuse-1").json()

    assert body["status"] == "DUPLICATE"
    assert body["fired_rule_id"] == "R025"
    assert "PROOF_REUSED" in body["reasons"]
    # The merchant is told WHICH order to go and look at. Without the earlier
    # reference the verdict is an assertion they cannot check.
    assert "order_demo_0999" in body["summary"]
    assert any("order_demo_0999" in note for note in body["observations"])


def test_a_reuse_verdict_names_no_transaction_because_it_looked_at_none() -> None:
    """`R025` decides on the bytes. It must not point at a ranked candidate.

    The predicate is `c.proof_reused` and nothing else -- deliberately, so that
    reuse is caught whether or not the payment behind the picture is anywhere in
    this order's feed. But `_matched_txn_id` used to hand the decision
    `ctx.best.txn_id` for any non-UNMATCHED status, so the verdict named the
    transaction that happened to rank best for THIS order, which on a reused
    screenshot is simply somebody else's payment.

    Measured before the fix, through this exact route: G01 approved for
    order_demo_1001, then re-sent against order_demo_1002, came back naming
    EP0000303 -- Rs 500 from Shoaib Malik -- and `DuplicateRecord` renders its
    figure, its transaction id and its sender under the caption "This payment
    arrived once". A stranger's payment, presented as the payment behind the
    receipt, with `agreementMeaning` printing the forgery sentence over the top
    of it because all three fields disagreed.

    The order matters: 1002's own ledger genuinely holds EP0000303, so this is
    not a contrived arrangement. It is what the second-cheapest fraud looks like
    against a shop that has other customers.
    """
    app_client = client()
    submit_and_approve(app_client, "order_demo_1001", "G01.jpg", "names-1")

    body = submit(app_client, "order_demo_1002", "G01.jpg", "names-2").json()

    assert body["fired_rule_id"] == "R025"
    assert body["matched_txn_id"] is None
    assert body["matched_transaction"] is None
    # And the summary talks about the picture and the earlier ORDER, never about
    # a transaction it declined to name.
    assert "ORD-G01" in body["summary"]
    assert "EP0000303" not in body["summary"]


def test_the_earlier_order_is_named_the_way_the_merchant_names_it() -> None:
    """`ORD-G01`, not `order_demo_1001`.

    The point of naming the earlier order at all is that the merchant can go and
    check it (`core/explain._earlier_proof_order`). An internal id defeats that
    exactly: it appears in no order list, and the picker the presenter clicked a
    moment earlier calls the same order ORD-G01. The engine sees only what the
    store recorded, so the fix is a field on `ProofFingerprint` rather than a
    translation at the far end -- there is nothing at the far end that could do
    it.
    """
    app_client = client()
    submit_and_approve(app_client, "order_demo_1001", "G01.jpg", "ref-1")

    body = submit(app_client, "order_demo_1002", "G01.jpg", "ref-2").json()

    assert "PROOF_PREVIOUSLY_SUBMITTED:ORD-G01" in body["observations"]
    assert not any("order_demo_1001" in note for note in body["observations"])
    assert "order_demo_1001" not in body["summary"]


def test_a_reused_screenshot_says_screenshot_and_not_transaction() -> None:
    """Two different accusations wear the word DUPLICATE. The prose must not blur them.

    A reused transaction means the money arrived once and is being spent twice.
    A reused screenshot means the picture is a re-run and the payment behind it
    may be perfectly good. Telling a merchant the transaction was already used,
    when it was not, is a claim they can check and find false.
    """
    app_client = client()
    digest = proof_store.content_sha256((FIXTURES / "G01.jpg").read_bytes())
    proof_store.record_accepted(MERCHANT_ID, sha256=digest, order_id="order_demo_0999")

    body = submit(app_client, "order_demo_1001", "G01.jpg", "wording-1").json()

    assert "screenshot" in body["summary"].lower()
    assert "transaction was already used" not in body["summary"].lower()
    assert "fresh receipt" in body["recommended_action"].lower()


def test_resubmitting_to_the_same_order_stays_verified() -> None:
    """A merchant who uploads the same receipt twice is not committing fraud.

    Different idempotency keys, so this is genuinely two decisions rather than a
    replayed response -- which is what makes it a test of the exemption in
    `check_proof` rather than of the idempotency registry.
    """
    app_client = client()

    first = submit(app_client, "order_demo_1001", "G01.jpg", "same-order-1").json()
    second = submit(app_client, "order_demo_1001", "G01.jpg", "same-order-2").json()

    assert first["status"] == "VERIFIED"
    assert second["status"] == "VERIFIED"
    assert second["fired_rule_id"] == "R090"


# ==========================================================================
# The demo, which must not move
# ==========================================================================


def test_the_five_demo_verdicts_survive_every_submission_order() -> None:
    """G01.jpg and D01.jpg are the same bytes, and the demo submits both.

    If proof reuse could reach either of them the demo would answer differently
    depending on which order the presenter clicked first -- order_demo_1001
    flipping from VERIFIED to DUPLICATE on stage. Two things prevent it: only a
    VERIFIED proof is recorded, and `R025` sits below `R020`. Both orderings are
    run here because the argument only holds if it holds in both.
    """
    expected = [
        ("order_demo_1001", "G01.jpg", "VERIFIED", "R090"),
        ("order_demo_1002", "S01.jpg", "SUSPICIOUS", "R030"),
        ("order_demo_1003", "D01.jpg", "DUPLICATE", "R020"),
        ("order_demo_1004", "N01.jpg", "NEEDS_REVIEW", "R070"),
        ("order_demo_1005", "U01.jpg", "UNMATCHED", "R010"),
    ]

    for label, sequence in (("fwd", expected), ("rev", list(reversed(expected)))):
        proof_store.reset()
        app_client = client()
        for index, (order_id, image, status, rule) in enumerate(sequence):
            body = submit(app_client, order_id, image, f"{label}-{index}").json()
            assert body["status"] == status, f"{label}: {order_id} moved to {body['status']}"
            assert body["fired_rule_id"] == rule, (
                f"{label}: {order_id} fired {body['fired_rule_id']}"
            )


def test_the_allocated_duplicate_keeps_its_more_specific_reason() -> None:
    """`R020` outranks `R025`, and order_demo_1003 is where that is visible.

    Run 1001 first and its image is remembered, so by the time 1003 submits the
    identical bytes BOTH duplicate signals are true. The verdict must stay
    TXN_ALREADY_ALLOCATED: it names the order that spent the money, which is
    strictly more actionable than "we have seen this picture". The reuse note
    still rides along in the observations, because the merchant is owed both
    facts.
    """
    app_client = client()

    submit_and_approve(app_client, "order_demo_1001", "G01.jpg", "precedence-1")
    body = submit(app_client, "order_demo_1003", "D01.jpg", "precedence-2").json()

    assert body["status"] == "DUPLICATE"
    assert body["fired_rule_id"] == "R020"
    assert "TXN_ALREADY_ALLOCATED" in body["reasons"]
    assert "PROOF_REUSED" not in body["reasons"]
    # By the merchant's own reference, never `order_demo_1001`. The frontend
    # declines to RENDER this note under an `R020` heading -- it is a fact about
    # the picture, and `R020` is a claim about the transaction -- but the engine
    # records it either way, and what it records has to be a name somebody could
    # look up if it were shown.
    assert any("ORD-G01" in note for note in body["observations"])


def test_demo_reset_forgets_the_proof_history() -> None:
    """Otherwise a second run of the demo accuses the presenter of their first."""
    app_client = client()
    submit_and_approve(app_client, "order_demo_1001", "G01.jpg", "reset-1")
    assert proof_store.prior_proofs(MERCHANT_ID)

    response = app_client.post("/api/v1/demo/reset", headers=auth())

    assert response.status_code == 200
    assert proof_store.prior_proofs(MERCHANT_ID) == ()


def test_one_merchants_proof_never_reaches_another_merchant() -> None:
    """The tenant boundary the unique index draws, drawn here too."""
    digest = proof_store.content_sha256((FIXTURES / "G01.jpg").read_bytes())
    proof_store.record_accepted("merchant_other", sha256=digest, order_id="ORD-THEIRS")

    body = submit(client(), "order_demo_1001", "G01.jpg", "tenant-1").json()

    assert body["status"] == "VERIFIED"
