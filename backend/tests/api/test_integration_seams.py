"""The seams, driven once end to end: bytes in, the frontend's shape out.

Every track in this repo is tested well on its own. `tests/core/` proves the
engine, `tests/api/test_openapi_stub.py` proves the routes, `tests/extraction/`
proves the reader. What nothing tested is the JOINS -- the places where one
track hands a value to the next and the two sides have to agree about what it
means. A join is exactly where a defect survives a green suite: each side is
individually correct and the contract between them was never written down.

    uploaded bytes
        |  multipart, 10 MB cap, media-type allowlist
        v
    ExtractionService ------> PaymentClaim        (seam 3: what could not be read)
        |  Money(minor: int), ClaimedInstant
        v
    decide() ---------------> Decision            (seam 4: reason codes, versions)
        |  Status / Risk / Agreement enums
        v
    verification_result_from_decision -> VerificationResult
        |  pydantic
        v
    JSON ------------------> frontend/src/api/adapt.ts   (seams 1, 2 and 4)

The four things asserted here, and why each is a seam rather than a unit:

* **Money stays an integer in minor units the whole way.** `core.money` proves
  its own arithmetic; nothing proved that the number reaching the browser is
  still paisa. A float that survives to `amount_minor` renders a wrong figure
  next to the word VERIFIED, and rupees-instead-of-paisa renders one a hundred
  times too small. Neither is a crash, and neither shows up in a unit test of
  either side on its own.
* **Timezone-aware UTC survives every hop.** A naive ISO string is valid JSON,
  parses without complaint, and is read by `new Date(...)` as the VIEWER's local
  time -- so a receipt stamped 13:54 in Karachi would read 18:54 to a merchant
  whose laptop is set to Singapore. The offset has to be in the string.
* **A field the extractor could not read arrives as `null`.** Not `""`, not
  "Unknown", and not an absent key. `adapt.ts` renders null as the italic "not
  shown in this screenshot"; a guess would be rendered as evidence, which is the
  one thing this product must not manufacture.
* **The response speaks the vocabularies the frontend closed over.**
  `adapt.ts::status()` THROWS on a status it does not recognise -- deliberately,
  because inventing a verdict is unsurvivable -- so a status added to `core`
  without being added there takes the screen down rather than degrading it.

Deliberately NOT re-asserted here: that the five demo receipts reach their five
verdicts (`test_openapi_stub.py::test_create_verification_runs_real_engine` and
`test_engine_integration.py` both do that), or anything a comparison, a rule or
a level already owns. A seam test that restates the unit tests is a slower copy
of them.

Fast and deterministic by construction: no network (the deterministic extractor
is a manifest lookup over committed bytes), and no clock read anywhere -- the
API pins `evaluated_at` to `PINNED_ANCHOR`, and every instant below is derived
from the fixtures rather than from `now()`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient

from proofpay.api.engine_demo import demo_case_for
from proofpay.api.v1.schemas import VerificationResult
from proofpay.api.verification_mapper import verification_result_from_decision
from proofpay.api.verification_service import _extract_claim
from proofpay.core.compare.levels import Agreement
from proofpay.core.decide import DecisionPolicy, decide
from proofpay.core.decide.engine import COMPARISONS, CONFIDENCE_KEYS, build_context
from proofpay.core.models import LedgerTxn, Order
from proofpay.core.reasons import ObservationCode, ReasonCode, Risk, Status
from proofpay.demo.clock import PINNED_ANCHOR
from proofpay.main import create_app

FIXTURES: Final[Path] = Path(__file__).resolve().parents[3] / "fixtures" / "demo" / "images"
MERCHANT_ID: Final[str] = "merchant_demo_001"
EVALUATED_AT: Final[datetime] = PINNED_ANCHOR.astimezone(UTC)

#: The five orders and the receipts the demo submits against them. The verdicts
#: are asserted elsewhere; this file only needs each pair to produce a REAL
#: response, and it needs all five because they exercise different shapes -- a
#: matched transaction and no matched transaction, four evidence rows and none.
DEMO_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("order_demo_1001", "G01.jpg"),
    ("order_demo_1002", "S01.jpg"),
    ("order_demo_1003", "D01.jpg"),
    ("order_demo_1004", "N01.jpg"),
    ("order_demo_1005", "U01.jpg"),
)

PAIR_IDS: Final[list[str]] = [order_id for order_id, _ in DEMO_PAIRS]


def submit(order_id: str, image: str, *, key: str | None = None) -> dict[str, Any]:
    """One real request, start to finish, and the raw JSON that came back.

    Deliberately the parsed-from-JSON dict rather than the pydantic model: the
    frontend never sees the model, and a seam test that inspects Python objects
    cannot see a field that pydantic serialises differently from how it stores
    it -- which is precisely the class of defect this file is looking for.
    """
    response = TestClient(create_app()).post(
        "/api/v1/verifications",
        data={"order_id": order_id},
        files={"screenshot": (image, (FIXTURES / image).read_bytes(), "image/jpeg")},
        headers={
            "Authorization": "Bearer stub-access-token",
            "Idempotency-Key": key or f"seams-{order_id}-{image}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def walk(value: Any, path: str = "") -> list[tuple[str, Any]]:
    """Every scalar in the payload, with the dotted path that reaches it.

    The seam assertions below are about a PROPERTY of the whole document -- no
    money anywhere is a float, no timestamp anywhere is naive -- and spelling
    each key out by hand would mean the assertion stops covering the field
    somebody adds next week.
    """
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in walk(v, f"{path}.{k}" if path else k)]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in walk(v, f"{path}[{i}]")]
    return [(path, value)]


# ---------------------------------------------------------------------------
# Seam 1: money is an integer count of paisa, everywhere, all the way out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("order_id", "image"), DEMO_PAIRS, ids=PAIR_IDS)
def test_every_money_figure_in_the_response_is_an_integer_minor_amount(
    order_id: str, image: str
) -> None:
    """`_minor` is a promise, and it is kept at every depth of the document.

    The convention runs from `Money.minor` through `amount_minor` on the claim
    and on the matched transaction, and down into `evidence[].detail.claim_minor`
    where the comparison records what it actually compared. One float anywhere in
    that chain means somebody converted to rupees and back, and that round trip
    through binary floating point is exactly how Rs 2,000.10 becomes
    200009.99999999997 -- the number this layer's money contract exists to make
    impossible.

    `bool` is excluded explicitly because it is an `int` subclass in Python, so
    `True` would otherwise sail through as a perfectly valid amount.
    """
    body = submit(order_id, image)

    money = [(p, v) for p, v in walk(body) if p.split(".")[-1].endswith("_minor")]
    assert money, "no money field found at all -- the response shape has changed"
    for path, value in money:
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{path} is {type(value).__name__} {value!r}; every `_minor` figure "
            f"must be an integer count of paisa"
        )


def test_the_paisa_that_arrive_are_the_paisa_the_receipt_printed() -> None:
    """The one figure checked against ground truth rather than against a type.

    G01 prints Rs 1,500 and the transaction is Rs 1,500. A unit-conversion bug at
    any hop is perfectly well typed and off by a factor of a hundred, so the type
    check above would not see it: 1500 is as plausible an integer as 150000.
    """
    body = submit("order_demo_1001", "G01.jpg")

    assert body["claim"]["amount_minor"] == 150_000
    assert body["matched_transaction"]["amount_minor"] == 150_000
    assert body["claim"]["currency"] == "PKR"
    # ...and the comparison recorded the same two numbers it was handed.
    amount_row = next(row for row in body["evidence"] if row["field"] == "amount")
    assert amount_row["detail"]["claim_minor"] == 150_000
    assert amount_row["detail"]["ledger_minor"] == 150_000
    assert amount_row["detail"]["diff_minor"] == 0


# ---------------------------------------------------------------------------
# Seam 2: every instant is an aware UTC instant, and says so in the string
# ---------------------------------------------------------------------------

#: Every key in the response that carries an instant. Named rather than sniffed
#: out of the values, because a naive timestamp is a string like any other.
TIMESTAMP_KEYS: Final[frozenset[str]] = frozenset({"occurred_at", "evaluated_at", "created_at"})


@pytest.mark.parametrize(("order_id", "image"), DEMO_PAIRS, ids=PAIR_IDS)
def test_every_instant_crosses_the_wire_offset_aware_and_in_utc(order_id: str, image: str) -> None:
    """A naive timestamp is the quietest wrong answer this API could give.

    It is valid JSON. It parses. `datetime.fromisoformat` accepts it. And
    `new Date("2026-08-20T08:54:00")` in a browser reads it as the VIEWER's own
    local time, so the same receipt reads 13:54 in Karachi and 18:54 in
    Singapore -- a five-hour discrepancy on the one field a merchant uses to
    decide whether this is the payment they were expecting.

    Both halves are asserted, because the second does not follow from the first:
    the value must resolve to UTC, AND the string must carry the offset that says
    so. `Z` and `+00:00` are the two spellings pydantic emits.
    """
    body = submit(order_id, image)

    stamps = [(p, v) for p, v in walk(body) if p.split(".")[-1] in TIMESTAMP_KEYS and v is not None]
    assert stamps, "no timestamp found at all -- the response shape has changed"
    for path, raw in stamps:
        assert isinstance(raw, str), f"{path} is not a string: {raw!r}"
        assert raw.endswith("Z") or raw[-6] in "+-", (
            f"{path} = {raw!r} carries no UTC offset; a browser would read it as "
            f"the viewer's own local time"
        )
        # `fromisoformat` accepts the `Z` spelling directly on 3.11+.
        parsed = datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None, f"{path} parsed naive"
        assert parsed.utcoffset() == timedelta(0), f"{path} is not UTC: {raw!r}"


def test_the_receipts_wall_clock_survives_the_conversion_to_utc() -> None:
    """The instant is preserved, not the digits.

    G01 prints 13:54 with no offset on it, which the reader resolves against
    Asia/Karachi (UTC+5) because that is where the merchant is -- an assumption
    the engine records as `TIME_TZ_ASSUMED` rather than a fact it was given.
    08:54Z is that same instant. A test asserting the digits `13:54` would pass
    just as happily against a naive timestamp, which is the bug.
    """
    body = submit("order_demo_1001", "G01.jpg")
    occurred = datetime.fromisoformat(body["claim"]["occurred_at"])

    assert occurred == datetime(2026, 8, 20, 8, 54, tzinfo=UTC)
    assert occurred.astimezone(PINNED_ANCHOR.tzinfo).hour == 13
    assert ObservationCode.TIME_TZ_ASSUMED in body["observations"]


def test_the_decision_is_stamped_with_the_pinned_demo_clock_and_not_with_now() -> None:
    """No hop reads the wall clock, which is what makes this file deterministic.

    Asserted rather than assumed: a `datetime.now()` slipped into the handler or
    the mapper would keep every other test in this file green and make this one
    fail on the second run of the day.
    """
    body = submit("order_demo_1001", "G01.jpg")

    assert body["evaluated_at"] == EVALUATED_AT.isoformat().replace("+00:00", "Z")
    assert body["created_at"] == body["evaluated_at"]


# ---------------------------------------------------------------------------
# Seam 3: what could not be read arrives as null, and never as a guess
# ---------------------------------------------------------------------------


def read_against_a_matching_row(image: str) -> tuple[Any, VerificationResult]:
    """Run one fixture receipt against a ledger row built to agree with it.

    The ledger is hand-built rather than taken from `demo_case_for`, on purpose.
    These three fixtures are not part of the five-order demo, and pairing one
    with a demo order would make the VERDICT depend on an arbitrary choice --
    while the thing under test here is not the verdict at all, but whether a
    field the reader could not make out survives four hops as `null`. So the row
    is made to agree on everything the receipt did print, which leaves the unread
    field as the only variable in the whole comparison.
    """
    claim = _extract_claim(
        (FIXTURES / image).read_bytes(),
        verification_id=f"verification_seams_{image}",
        merchant_id=MERCHANT_ID,
    )
    assert claim.amount is not None, f"{image} printed no amount; pick another fixture"
    order = Order(order_id="order_seams_0001", expected=claim.amount, merchant_id=MERCHANT_ID)
    txn = LedgerTxn(
        txn_id="TXN-SEAMS-1",
        amount=claim.amount,
        occurred_at=(
            claim.occurred_at.resolved_utc if claim.occurred_at is not None else EVALUATED_AT
        ),
        merchant_id=MERCHANT_ID,
        provider=claim.provider,
        external_id=claim.reference_id or "EXT-SEAMS-1",
        sender_name=claim.sender_name or "Rukhsana Tabassum",
        receiver_name=claim.receiver_name,
    )
    decision = decide(claim, order, [txn], (), now=EVALUATED_AT, policy=DecisionPolicy())
    result = verification_result_from_decision(
        decision,
        claim=claim,
        order=order,
        ledger=[txn],
        verification_id=f"verification_seams_{image}",
        created_at=EVALUATED_AT,
    )
    return claim, result


@pytest.mark.parametrize(
    ("image", "claim_field", "view_field"),
    [
        # The sender's name cropped off the top of the screenshot.
        ("N06.jpg", "sender_name", "sender_name"),
        # A receipt that printed no transaction id at all, which is ordinary.
        ("N03.jpg", "reference_id", "reference_id"),
        # A receipt whose timestamp line did not survive the photograph.
        ("N05.jpg", "occurred_at", "occurred_at"),
    ],
)
def test_a_field_the_reader_could_not_make_out_stays_null_to_the_wire(
    image: str, claim_field: str, view_field: str
) -> None:
    """Null at every hop, and a KEY that is present and holding null at the end.

    Three separate wrong answers are ruled out, because each is a different lie
    and each renders differently:

      * a GUESS -- "Unknown", "N/A", the merchant's own name -- is rendered by
        the UI as evidence, in the same weight as a field that really was read;
      * an EMPTY STRING is falsy in JavaScript but is not null, and `adapt.ts`
        has to normalise it back (`str()` does, deliberately) -- relying on that
        would make this API's honesty a property of its client;
      * an ABSENT KEY leaves the shape `frontend/src/types.ts` mirrors
        incomplete, and only a schema round trip catches that.
    """
    claim, result = read_against_a_matching_row(image)

    # Hop 1: the extractor reported nothing rather than inventing something.
    assert getattr(claim, claim_field) is None

    # Hop 2: the comparison called it absent, not wrong. `Agreement.MISSING` is
    # its own member precisely so that absence of evidence never renders as
    # evidence of mismatch.
    payload = result.model_dump(mode="json")
    missing = [row for row in payload["evidence"] if row["agreement"] == Agreement.MISSING]
    assert missing, f"{image}: nothing was reported missing at all"
    for row in missing:
        assert row["claimed_value"] is None
        assert row["level_code"].endswith("_MISSING")

    # Hops 3 and 4: the key is there, and it is null, and it survives encoding.
    assert view_field in payload["claim"]
    assert payload["claim"][view_field] is None
    assert json.dumps(payload)


def test_nothing_matched_is_reported_as_nothing_and_not_as_an_empty_transaction() -> None:
    """U01: no candidate at all, so there is no transaction to describe.

    `matched_transaction: {}` would render a row of blanks beside the claim and
    read as "something arrived, we just cannot tell you what". `adapt.ts` guards
    this from its own side by dropping a matched transaction that cannot name an
    amount; this asserts the API never asks it to.
    """
    body = submit("order_demo_1005", "U01.jpg")

    assert body["matched_transaction"] is None
    assert body["matched_txn_id"] is None
    assert body["evidence"] == []
    assert body["summary"]


# ---------------------------------------------------------------------------
# Seam 4: the vocabularies the frontend closed over
# ---------------------------------------------------------------------------

#: Mirrors of the three closed sets in `frontend/src/api/adapt.ts`. Written here
#: as literals rather than parsed out of the TypeScript, because the point is to
#: fail when the two DIVERGE -- and a test that derived one from the other could
#: not tell that they had.
#:
#: `status()` in that file THROWS on anything outside its set: "inventing a
#: verdict is the one failure this product cannot survive". So a `Status` added
#: to `core` and not added there does not degrade the screen, it takes it down.
FRONTEND_STATUSES: Final[frozenset[str]] = frozenset(
    {"VERIFIED", "UNMATCHED", "SUSPICIOUS", "DUPLICATE", "NEEDS_REVIEW"}
)
FRONTEND_AGREEMENTS: Final[frozenset[str]] = frozenset({"AGREE", "WEAK", "CONTRADICT", "MISSING"})
FRONTEND_RISKS: Final[frozenset[str]] = frozenset({"LOW", "MEDIUM", "HIGH"})

#: Every key `adaptVerification` reads off the response. A key that stops being
#: emitted does not raise there -- it silently becomes `''`, `0` or `null`, so a
#: dropped `policy_fingerprint` would show as an empty provenance line rather
#: than as an error anybody could act on.
ADAPTED_KEYS: Final[tuple[str, ...]] = (
    "id",
    "order_id",
    "status",
    "stage",
    "risk",
    "confidence",
    "claim",
    "matched_transaction",
    "matched_txn_id",
    "reasons",
    "summary",
    "fired_rule_id",
    "evidence",
    "observations",
    "recommended_action",
    "ruleset_version",
    "policy_fingerprint",
    "engine_version",
    "evaluated_at",
    "created_at",
    "degraded",
)


def test_the_engines_vocabularies_are_exactly_the_ones_the_frontend_closed_over() -> None:
    """The anti-drift assertion, and the reason the mirrors above are literals.

    `core` owns these three enums and `api/v1/schemas.py` re-exports them
    unchanged, so adding a member is a one-line change in a file nobody would
    think to check against a TypeScript module. This is the line that makes
    somebody check.
    """
    assert {s.value for s in Status} == FRONTEND_STATUSES, (
        "core.reasons.Status and the STATUSES set in frontend/src/api/adapt.ts "
        "have diverged. adapt.ts THROWS on an unknown status, so this is a blank "
        "screen and not a degraded one."
    )
    assert {a.value for a in Agreement} == FRONTEND_AGREEMENTS, (
        "core.compare.levels.Agreement and the AGREEMENTS set in "
        "frontend/src/api/adapt.ts have diverged; an unknown agreement is "
        "silently rendered as MISSING there."
    )
    assert {r.value for r in Risk} == FRONTEND_RISKS, (
        "core.reasons.Risk and the RISKS set in frontend/src/api/adapt.ts have diverged."
    )


@pytest.mark.parametrize(("order_id", "image"), DEMO_PAIRS, ids=PAIR_IDS)
def test_the_response_speaks_only_words_the_frontend_can_read(order_id: str, image: str) -> None:
    body = submit(order_id, image)

    assert body["status"] in FRONTEND_STATUSES
    assert body["risk"] in FRONTEND_RISKS
    for row in body["evidence"]:
        assert row["agreement"] in FRONTEND_AGREEMENTS
    for key in ADAPTED_KEYS:
        assert key in body, f"{key} is read by adapt.ts and is not in the response"


#: Observation heads this API emits that `ObservationCode` does not declare.
#:
#: A pin, not an exemption -- the same shape as `KNOWN_DISAGREEMENTS` in the
#: manifest harness. The set is asserted to be exactly this, so a SECOND undeclared
#: head fails the build rather than joining a growing list nobody is reading.
#:
#: `IMAGE_PHASH` is emitted as a bare string literal by
#: `extraction/tamper.py:61` and appears on EVERY response, in both extractor
#: modes, carrying a 256-bit perceptual hash and a dHash as its detail. It is a
#: genuine observation by the definition in `ObservationCode`'s own docstring --
#: "neutral things noticed while parsing, never a verdict" -- and it is simply
#: not in the enum, so nothing downstream can switch on it and
#: `explain._observation_line` falls through to printing the raw hash.
#:
#: Left alone here deliberately. Declaring it is a one-line change to `core`, but
#: the question it opens is a product one and belongs with whoever owns the
#: observation list: a merchant has no use for a 64-character hash, so declaring
#: the code without deciding what the screen should say about it would only move
#: the wart. What ends this row is that decision -- either the code joins
#: `ObservationCode` with a label in `explain._OBSERVATION_LABELS`, or the note
#: stops being published to the API at all and lives only where the reuse check
#: reads it.
UNDECLARED_OBSERVATION_HEADS: Final[frozenset[str]] = frozenset({"IMAGE_PHASH"})


@pytest.mark.parametrize(("order_id", "image"), DEMO_PAIRS, ids=PAIR_IDS)
def test_every_reason_and_observation_is_a_real_code_and_not_free_text(
    order_id: str, image: str
) -> None:
    """Reason codes are a machine vocabulary; the summary is where prose lives.

    `frontend/src/types.ts` types `reasons` as a bare `string[]` and `copy.ts`
    branches on specific members of it, so a reason that is not a `ReasonCode`
    fails no type check anywhere -- it silently matches no branch and drops the
    wording written for it.

    Observations are checked in the same breath but under a looser rule, because
    `extraction/service` folds a detail onto some of them: `PROOF_PREVIOUSLY_
    SUBMITTED` arrives as `PROOF_PREVIOUSLY_SUBMITTED:<order ref>`. The HEAD
    before the first colon must still be a declared code -- that is what stops
    the observation list from becoming somewhere to put arbitrary strings -- or
    else be a named, pinned exception.
    """
    body = submit(order_id, image)

    reason_codes = {code.value for code in ReasonCode}
    observation_codes = {code.value for code in ObservationCode}
    for raw in body["reasons"]:
        assert raw in reason_codes, f"{raw!r} is not a ReasonCode"
    for raw in body["observations"]:
        head = raw.split(":", 1)[0]
        assert head in observation_codes | UNDECLARED_OBSERVATION_HEADS, (
            f"{raw!r} does not begin with an ObservationCode. Either declare it "
            f"in core.reasons.ObservationCode, or add it to "
            f"UNDECLARED_OBSERVATION_HEADS with a reason and a way out."
        )


def test_the_list_of_undeclared_observation_heads_has_not_grown() -> None:
    """The pin above stays a pin, and does not quietly become a policy.

    Computed over all five demo pairs rather than asserted per-response, because
    the claim is about the API as a whole: exactly one head escapes the enum
    today, and it is a known one. A second escape means either a new bare string
    literal somewhere in extraction, or a code that was renamed out from under
    the enum -- and both should stop a build.
    """
    observation_codes = {code.value for code in ObservationCode}
    seen = {
        raw.split(":", 1)[0]
        for order_id, image in DEMO_PAIRS
        for raw in submit(order_id, image)["observations"]
    }

    assert seen - observation_codes == UNDECLARED_OBSERVATION_HEADS, (
        "the set of observation heads that escape ObservationCode has changed. "
        "Undeclared heads seen: "
        f"{sorted(seen - observation_codes)}"
    )


@pytest.mark.parametrize(("order_id", "image"), DEMO_PAIRS, ids=PAIR_IDS)
def test_the_json_the_browser_receives_re_validates_as_the_contract(
    order_id: str, image: str
) -> None:
    """The round trip: serialise, then parse the bytes back through the schema.

    Not the same as the handler's own `response_model` check, which validates the
    OBJECT the handler returned. This validates the DOCUMENT that came off the
    wire, which is the only artefact the frontend ever sees -- and it is where a
    field that serialises to something the schema would reject (a naive datetime,
    a float where an int is declared) gets caught.
    """
    body = submit(order_id, image)

    revalidated = VerificationResult.model_validate(body)
    assert revalidated.model_dump(mode="json") == body


# ---------------------------------------------------------------------------
# The offline confidence gap, pinned as a fact rather than left as an assumption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("order_id", "image"), DEMO_PAIRS, ids=PAIR_IDS)
def test_the_offline_extractor_reports_no_field_confidence_at_all(
    order_id: str, image: str
) -> None:
    """`R067` cannot fire on this path, and here is the reason spelled out.

    `extraction/stub.py` is a SHA-256 lookup into `fixtures/demo/manifest.json`.
    It never inspects a pixel, so it fills no `ExtractionResult.fields`, so
    `service._normalise` builds an empty `field_confidences`, so
    `PaymentClaim.confidence_for` answers 1.0 for every field. The rule reads a
    signal this half of the product cannot produce, and pretending otherwise
    would mean writing a confidence band into a fixture that nothing measured.

    Pinned positively, in the direction that matters: the day the stub learns to
    report bands THIS test goes red, and it points at the three manifest pins
    (N04/N05/N06) that are waiting on exactly that. An unreachable rule that
    nobody has written down is one that sits unreachable through a release.
    """
    claim = _extract_claim(
        (FIXTURES / image).read_bytes(),
        verification_id="verification_seams_confidence",
        merchant_id=MERCHANT_ID,
    )
    assert claim.field_confidences == {}

    case = demo_case_for(order_id, MERCHANT_ID)
    ctx = build_context(
        claim,
        case.order,
        case.ledger,
        case.allocations,
        now=EVALUATED_AT,
        policy=DecisionPolicy(),
    )
    assert ctx.low_confidence_fields == ()
    assert not ctx.has_low_confidence_field


# Importing the extractor pulls in the DashScope SDK, which deprecation-warns at
# import time about an Assistants API this project never touches. Scoped to this
# one test rather than to the file so a warning from OUR code still shows.
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_core_looks_up_confidence_under_the_names_the_reader_reports_it_by() -> None:
    """The one vocabulary the two sides never agreed on, asserted at the join.

    `core` scores a field it calls `reference`; the only extractor that reports
    confidences calls it `reference_id`. Nothing forced those names to agree, and
    nothing would have failed if they did not -- `R067` would simply never have
    fired on a doubted transaction id, which is the field most likely to be
    misread in the first place: a long digit string in a small font.

    The extractor's names are read out of its own field map rather than copied
    into a list here, so this fails when THAT changes rather than when a copy of
    it goes stale. Built without `__init__` on purpose: the real constructor
    demands a DASHSCOPE_API_KEY and mutates a module-global base URL, and this
    method reads no instance state at all.
    """
    from proofpay.extraction.dashscope_ocr import DashScopeOcrExtractor
    from proofpay.extraction.schema import RawClaim

    extractor = object.__new__(DashScopeOcrExtractor)
    reported = {evidence.field for evidence in extractor._build_field_evidence(RawClaim(), {})}
    scored = {comparison.field for comparison in COMPARISONS}

    # Every scored field has somewhere to look...
    assert set(CONFIDENCE_KEYS) == scored
    # ...and for each one, at least one name it looks under is a name the reader
    # actually reports. A scored field whose keys the extractor never emits is a
    # rule that quietly never fires for that field.
    for field, keys in CONFIDENCE_KEYS.items():
        assert reported & set(keys), (
            f"core looks up confidence for {field!r} under {keys!r}, and the "
            f"extractor reports none of those. It reports {sorted(reported)}."
        )
    # The reverse direction is deliberately NOT asserted: `currency`, `status`,
    # `provider`, `receiver_name` and `receiver_account` are all reported and all
    # ignored, because no comparison scores them -- and a shaky reading of a
    # field the verdict does not rest on is not grounds for stopping an order.
    assert reported - scored - {"reference_id"}


# ==========================================================================
# The cloud reader's confidences, which are an input to the rule table
# ==========================================================================
#
# `R067` reads `claim.field_confidences`, and the ONLY producer of that mapping
# is `DashScopeOcrExtractor._build_field_evidence`. Nothing tested the two
# together, and the gap was not academic: the extractor passed
# `grounded=None` with a "will be set later" comment, nothing ever set it, and
# `compute_confidence_band` treated an unchecked field exactly like a refuted
# one -- so every field the cloud reader could read came back `low`, mapped to
# 0.5, fell under `min_field_confidence` of 0.75, and `R067` took every claim
# that cleared `tau_accept`. Turning on the project's headline AI story meant no
# verification could ever return VERIFIED again.
#
# The one test that touched this seam called `_build_field_evidence(RawClaim(),
# {})` with every field absent, so every band was `none` and the all-`low`
# behaviour never appeared. These run it on a receipt that WAS read.
#
# Importing the extractor pulls in the DashScope SDK, which deprecation-warns at
# import time about an Assistants API this project never touches. Scoped per
# test rather than to the file, so a warning from our own code still shows.

#: G01 as the KIE head would hand it back: the manifest's own `visible` values,
#: in the shape `_map_to_raw_claim` produces. Written from the manifest rather
#: than invented, so a fixture edit shows up here as a failure rather than as a
#: test quietly asserting something about a receipt that no longer exists.
_G01_KIE: Final[dict[str, str]] = {
    "reference_id": "EP0000011",
    "amount_text": "Rs. 1,500.00",
    "currency_text": "PKR",
    "sender_name": "Bilal Ahmed Khan",
    "receiver_name": "Ali Traders",
    "receiver_account": "0300 1234567",
    "timestamp_text": "20 Aug 2026, 01:54 PM",
    "status_text": "Successful",
    "provider_hint": "Easypaisa",
}


def _cloud_fields(kie: dict[str, str], *, ocr_text: str | None):
    """Run the real cloud extractor's evidence builder over a read receipt.

    Built with `object.__new__` on purpose: the real constructor demands a
    DASHSCOPE_API_KEY and mutates a module-global base URL, and this method
    reads no instance state at all. No network, no key, no request.
    """
    from proofpay.extraction.dashscope_ocr import DashScopeOcrExtractor
    from proofpay.extraction.schema import Maybe, RawClaim

    claim = RawClaim(**{k: Maybe(value=v, raw_text=v) for k, v in kie.items()})
    extractor = object.__new__(DashScopeOcrExtractor)
    return extractor._build_field_evidence(claim, {}, ocr_text)


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.parametrize(
    "ocr_text",
    [
        pytest.param(" ".join(_G01_KIE.values()), id="with-detector-text"),
        # The response shape is not guaranteed to carry `words_info`, and
        # `_extract_ocr_text` answers None when it does not. A field that could
        # not be grounded because there was nothing to ground it against must
        # not be reported as a field that failed grounding.
        pytest.param(None, id="no-detector-text"),
    ],
)
def test_a_receipt_the_cloud_reader_read_cleanly_doubts_nothing(ocr_text) -> None:
    """No `low` band on a receipt that was read. This is the blocker, pinned.

    Both halves are asserted, because either one alone would pass while the
    engine still broke: the bands, and the confidences they become. The second
    runs the SAME mapping `_normalise` runs -- `field_confidences_from` exists at
    module level for exactly that reason.
    """
    fields = _cloud_fields(_G01_KIE, ocr_text=ocr_text)
    from proofpay.extraction.service import field_confidences_from

    doubted = [f.field for f in fields if f.confidence_band == "low"]
    assert doubted == [], (
        f"the cloud reader doubts {doubted} on a receipt it read perfectly. "
        f"Every one of those becomes 0.5, which is under min_field_confidence, "
        f"which is R067, which is NEEDS_REVIEW on every claim."
    )
    confidences = field_confidences_from(fields)
    assert confidences and all(value == 1.0 for value in confidences.values())


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_the_headline_demo_verdict_survives_the_cloud_readers_confidences() -> None:
    """order_demo_1001 with `PROOFPAY_RECEIPT_EXTRACTOR=qwen`, in effect.

    The demo cannot be run against DashScope here -- no key, no network -- so
    this does the next-honest thing: it takes the confidences the cloud path
    really builds for G01 and puts them on the claim the offline path produces,
    which is the only difference between the two readers that `decide()` can
    see. Before the fix this assertion read VERIFIED and got NEEDS_REVIEW/R067.

    The measured consequence was two of the five demo verdicts moving on one
    environment variable: 1001 VERIFIED -> NEEDS_REVIEW, and 1004's
    AMOUNT_UNDERPAID -- the thing the merchant actually needs to see -- replaced
    by "we could not read it clearly".
    """
    from dataclasses import replace

    from proofpay.extraction.service import field_confidences_from

    confidences = field_confidences_from(_cloud_fields(_G01_KIE, ocr_text=None))
    case = demo_case_for("order_demo_1001", MERCHANT_ID)
    claim = replace(
        _extract_claim(
            (FIXTURES / "G01.jpg").read_bytes(),
            verification_id="verification_cloud_bands",
            merchant_id=MERCHANT_ID,
        ),
        field_confidences=confidences,
    )

    decision = decide(
        claim,
        case.order,
        case.ledger,
        case.allocations,
        now=EVALUATED_AT,
        policy=DecisionPolicy(),
    )

    assert decision.status is Status.VERIFIED
    assert decision.fired_rule_id == "R090"
    assert ReasonCode.LOW_EXTRACTION_CONFIDENCE not in decision.reasons


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_the_rule_still_fires_on_a_field_the_reader_could_not_make_sense_of() -> None:
    """The other direction, so the fix above is not "switch the rule off".

    `R067` has to stay reachable, and reachable for a REASON: a value the field's
    own parser cannot read is a value this reader did not read well enough to
    carry a verification, and `service._normalise` will hand `PaymentClaim` a
    `None` for it regardless. The doubt and the consequence are the same fact.

    `amount` and `timestamp` are used because they are scored fields --
    `CONFIDENCE_KEYS` looks them up under exactly those names -- so the doubt
    reaches the rule table rather than stopping at the evidence panel.
    """
    from proofpay.core.decide.engine import doubted_fields
    from proofpay.core.models import PaymentClaim
    from proofpay.extraction.service import field_confidences_from

    mangled = {**_G01_KIE, "amount_text": "Rs. ----", "timestamp_text": "20 Augus"}
    fields = _cloud_fields(mangled, ocr_text=None)
    confidences = field_confidences_from(fields)

    assert confidences["amount"] == 0.5
    assert confidences["timestamp"] == 0.5
    assert confidences["reference_id"] == 1.0

    claim = PaymentClaim(claim_id="mangled", field_confidences=confidences)
    assert doubted_fields(claim, DecisionPolicy()) == ("amount", "timestamp")
