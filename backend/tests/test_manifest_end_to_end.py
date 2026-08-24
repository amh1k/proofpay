"""Every fixture case, driven end to end: image bytes -> extractor -> `decide()`.

WHY THIS FILE EXISTS
    Until now nothing joined the two halves of the demo dataset. The manifest's
    30 cases each declare an expected verdict; the engine was wired to five
    hand-written scenarios in `proofpay/api/engine_demo.py`. The manifest's
    `ledger`, `allocations` and `order` blocks were read by no running code at
    all, so a fixture could quietly stop proving its scenario -- or a rule could
    stop reaching it -- and the suite would stay green either way. That is the
    drift this harness exists to stop. It is the first consumer of that data.

WHAT EACH CASE ACTUALLY RUNS
    The committed JPEG's bytes go through `OfflineStubExtractor` (the real
    offline extractor, not a mock) and are resolved by sha256 alone -- see
    `_claim_for` for why the claim id is prefixed to keep the stub's id
    fallback from making the bytes optional. The manifest's own rows become
    `LedgerTxn`, `Order` and `Allocation` values, and `decide()` is asked for a
    verdict. One parametrised test per case, so a failure line names the case:

        FAILED test_manifest_end_to_end.py::test_case_reaches_its_expected_verdict[D01]

    The extraction path deliberately bypasses `api/v1/verifications.py`: that
    entry point is gated on `effective_receipt_extractor()`, raises
    `HTTPException`, and resolves the case id by image hash -- which mis-resolves
    the two byte-identical fixture pairs (see the tripwire further down). Calling
    the extractor directly keeps the harness independent of settings and of which
    case happens to be listed first.

TWO MISTAKES THIS PROJECT HAS ALREADY MADE, WRITTEN DOWN SO THEY STAY MADE ONCE
    1. Inventing an absolute time anchor. Fixture times are integer minute
       OFFSETS from `PINNED_ANCHOR`; a harness that builds its own "now" moves
       every ledger row away from the receipt and then blames the fixtures. Both
       sides here are pinned -- see `_at` and `test_receipt_text_agrees_with_the
       _pinned_offsets`.
    2. Handing `decide()` a PENDING row. See `_ledger_for`.

THE LEDGER SCOPE, DECIDED HERE BECAUSE NOBODY HAD DECIDED IT ANYWHERE
    Each case is evaluated against its OWN rows only, never a merchant-wide pool
    of all 30 cases' rows. This is what the fixtures were authored for:
    U01-U04 expect `NO_CANDIDATES`, which needs a feed with nothing in it to
    find, and D01-D04 deliberately reuse G01-G04's transaction references, which
    could not coexist in one real feed. Measured, for anyone tempted to switch:
    per-case scoring reaches the manifest's status on 18 of 30 cases and its
    status *and* reason on 10; a pooled 23-row feed reaches 20 and 15. The
    pooled figure is better only because a wider feed gives `build_name_idf`
    enough documents to stop flooring every name at `name_idf_floor`, and it
    breaks U01 and U02 outright. That is a scoring artefact, not fixture intent.

NOTHING HERE IS WEAKENED TO REACH GREEN
    A case the engine does not satisfy is either fixed in the fixture data or
    recorded in `KNOWN_DISAGREEMENTS` with both sides named, the engine's
    current answer pinned exactly, and the event that would delete the row. No
    `skip`, no `xfail`, no assertion softened to fit: a row that stops
    disagreeing fails just as loudly as one that starts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from proofpay.core.decide.engine import build_context, decide
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.decide.rules_v1 import RULES
from proofpay.core.explain import explain
from proofpay.core.models import Allocation, Decision, LedgerTxn, Order, PaymentClaim
from proofpay.core.money import Money
from proofpay.core.reasons import Source
from proofpay.demo.clock import PINNED_ANCHOR, PKT
from proofpay.extraction.stub import OfflineStubExtractor

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MANIFEST: Final[Path] = REPO_ROOT / "fixtures" / "demo" / "manifest.json"
IMAGES: Final[Path] = REPO_ROOT / "fixtures" / "demo" / "images"

#: Parsed at import so a malformed manifest fails collection rather than thirty
#: separate tests.
CASES: Final[tuple[dict, ...]] = tuple(json.loads(MANIFEST.read_text("utf-8"))["cases"])

EXTRACTOR: Final[OfflineStubExtractor] = OfflineStubExtractor(MANIFEST)

POLICY: Final[DecisionPolicy] = DecisionPolicy()

MERCHANT_ID: Final[str] = "merchant_demo_001"

#: The instant the decision is taken. `PINNED_ANCHOR` directly, never
#: `clock.anchor()`: `anchor()` honours PROOFPAY_DEMO_ANCHOR, but the claim's own
#: timestamp is printed on a committed JPEG and cannot move with it. Pin both
#: sides or neither -- `api/engine_demo.py` and `api/v1/verifications.py` already
#: make the same choice for the same reason.
NOW: Final[datetime] = PINNED_ANCHOR.astimezone(UTC)

#: Matches `engine_demo.py`: the order was placed half an hour before the anchor,
#: comfortably before every claimed payment in the set.
ORDER_CREATED_OFFSET_MIN: Final[int] = -30


def _at(offset_minutes: int) -> datetime:
    """A fixture offset resolved against the pinned anchor, in UTC."""
    return (PINNED_ANCHOR + timedelta(minutes=offset_minutes)).astimezone(UTC)


def _ids(case: dict) -> str:
    return case["id"]


# ---------------------------------------------------------------------------
# Manifest -> engine inputs
# ---------------------------------------------------------------------------


def _claim_for(case: dict) -> PaymentClaim:
    """The real extractor's reading of the real committed image bytes.

    The claim id is prefixed rather than being the bare case id, and that is
    load-bearing. `OfflineStubExtractor` resolves an image by
    `sha256 match OR case["id"] == claim_id`; hand it "G05" and the id arm
    matches whatever the bytes are, so replacing G05.jpg with junk would leave
    this whole file green -- image drift being the one kind of drift this
    harness exists to catch. "e2e-G05" matches no case id (and is not the
    "eval-" prefix the stub strips), which forces resolution through the hash
    and makes a corrupted or re-rendered JPEG raise instead of pass.

    Resolving purely by hash means D01 and D02 land on G01 and G02, whose
    images they share byte for byte. That is correct and not a workaround:
    `test_cases_sharing_an_image_agree_on_what_it_shows` pins that the twins
    describe the same receipt, so the extracted claim is identical either way.

    `merchant_id` and `proof_id` are stamped on afterwards because the offline
    stub sets neither, and a claim with no `merchant_id` never exercises the
    tenant scoping inside retrieval -- it would pass for the wrong reason.
    They carry this case's own id, not the twin's.
    """
    case_id = case["id"]
    claim = EXTRACTOR.extract((IMAGES / f"{case_id}.jpg").read_bytes(), f"e2e-{case_id}")
    return replace(claim, merchant_id=MERCHANT_ID, proof_id=f"proof_{case_id}")


def _ledger_for(case: dict) -> tuple[LedgerTxn, ...]:
    """This case's own feed rows, minus anything the feed has not settled.

    The `status` filter is the whole of U02. `core.models.LedgerTxn` has no
    `status` field, so an unsettled row cannot even be represented to the engine;
    keeping it out of the feed is therefore this adapter's job, exactly as
    `core/duplicates.py` says filtering RELEASED allocations is. Per
    docs/data-model.md 10.2, "VERIFIED requires a selected POSTED transaction
    with sufficient trust." Hand `decide()` a PENDING row and the engine verifies
    money that has not arrived: U02 is the only PENDING row in the 30 and exists
    to catch precisely that.
    """
    return tuple(
        LedgerTxn(
            txn_id=row["external_transaction_id"],
            external_id=row["external_transaction_id"],
            amount=Money(row["amount_paisa"]),
            occurred_at=_at(row["ledger_offset_min"]),
            merchant_id=MERCHANT_ID,
            provider=row["rail"],
            sender_name=row["sender_name"],
            receiver_name=row["receiver_name"],
            source=Source(row["trust_level"]),
            ingested_at=NOW,
        )
        for row in case["ledger"]
        if row["status"] == "POSTED"
    )


def _dropped_row_count(case: dict) -> int:
    """How many rows `_ledger_for` withheld, for the failure message.

    A verdict that turns on an invisible filter is unreadable without this
    number, and the next person asking "why did U02 find nothing?" should be able
    to answer it from the failure text alone.
    """
    return sum(1 for row in case["ledger"] if row["status"] != "POSTED")


def _order_for(case: dict) -> Order:
    ref = case["order"]["external_order_ref"]
    return Order(
        order_id=ref,
        reference=ref,
        expected=Money(case["order"]["expected_amount_paisa"]),
        merchant_id=MERCHANT_ID,
        created_at=_at(ORDER_CREATED_OFFSET_MIN),
    )


def _allocations_for(case: dict) -> tuple[Allocation, ...]:
    """The earlier claims that already consumed one of this case's transactions.

    Only ACTIVE allocations may be passed to the engine; core `Allocation`
    carries no status, so a released one would have to be filtered here. No
    fixture needs that yet, which is why the manifest has no such key -- when one
    does, it filters in this function.
    """
    return tuple(
        Allocation(
            txn_id=alloc["external_transaction_id"],
            order_id=alloc["allocated_to_order_ref"],
            allocated_at=(
                None
                if alloc.get("allocated_offset_min") is None
                else _at(alloc["allocated_offset_min"])
            ),
        )
        for alloc in case["allocations"]
    )


def _decide_case(case: dict) -> Decision:
    """Run one case exactly as this harness means it to be run.

    `observations` is deliberately not passed. `R040` counts only the strings
    handed in through `decide(observations=...)`; the extractor's tamper signals
    land in `claim.notes` as "CODE:detail" and never reach `tamper_count`.
    Synthesising observations from the manifest's `tamper_type` to light up
    `R040` would be this harness manufacturing forensic findings the product did
    not produce, so it does not. The consequence is worth knowing: the six
    SUSPICIOUS cases' tamper metadata is exercised end to end by nothing.
    """
    return decide(
        _claim_for(case),
        _order_for(case),
        _ledger_for(case),
        _allocations_for(case),
        now=NOW,
        policy=POLICY,
    )


# ---------------------------------------------------------------------------
# The failure message
# ---------------------------------------------------------------------------


def _report(case: dict, decision: Decision) -> str:
    """Everything a reader needs to decide which half is wrong, in one block.

    Rebuilding the context costs a second scoring pass, which is why this runs
    only on the failure path. `build_context` is exposed by the engine for
    exactly this: it returns what the rules saw, so the message can quote the
    scores and the field levels rather than leaving them to be guessed at.
    """
    claim = _claim_for(case)
    order = _order_for(case)
    ledger = _ledger_for(case)
    ctx = build_context(
        claim,
        order,
        ledger,
        _allocations_for(case),
        now=NOW,
        policy=POLICY,
    )
    best = ctx.ranking.best
    txn = next((t for t in ledger if t.txn_id == decision.matched_txn_id), None)
    if txn is None and best is not None:
        txn = best.txn
    # The merchant-facing summary runs to several lines for the money rules, and
    # the extra lines are the interesting part ("that is more than the order
    # total"), so all of them are kept and indented under one label.
    summary = explain(decision, claim=claim, txn=txn, order=order).summary
    summary_lines = summary.splitlines() or ["(no summary)"]
    said = [f"  engine says      : {summary_lines[0]}"]
    said += [f"                     {line}" for line in summary_lines[1:]]

    if best is None:
        candidate_lines = [
            "  best candidate   : none -- retrieval returned no candidate at all",
        ]
    else:
        fields = " | ".join(f"{o.field} {o.level_code} {o.score:.2f}" for o in best.evidence)
        candidate_lines = [
            (
                f"  best candidate   : {best.txn_id}  score {best.score:.4f}"
                f"  (tau_accept {POLICY.tau_accept}, tau_reject {POLICY.tau_reject})"
            ),
            (
                f"                     margin {ctx.ranking.margin:.3f}"
                f" over {len(ctx.ranking.scored)} scored candidate(s)"
            ),
            f"  field outcomes   : {fields}",
        ]

    expected = case["expected"]
    lines = [
        f"{case['id']} ({case['title']}): the manifest and the engine disagree.",
        f"  manifest expects : {expected['outcome']} / {expected['reason_code']}",
        (
            f"  engine returned  : {decision.status.value} via {decision.fired_rule_id},"
            f" reasons [{', '.join(sorted(str(r) for r in decision.reasons))}]"
        ),
        *said,
        *candidate_lines,
        (
            f"  inputs to decide : {len(ledger)} ledger row(s)"
            f" ({_dropped_row_count(case)} dropped as non-POSTED),"
            f" {len(case['allocations'])} allocation(s),"
            f" now={NOW.isoformat()} (PINNED_ANCHOR)"
        ),
        "  Which half is wrong?",
        "    - if the ENGINE is right, the fixture's expectation is wrong: change",
        "      it in tools/build_manifest.py and regenerate. Never hand-edit",
        "      manifest.json -- the next generator run reverts it silently.",
        "    - if the FIXTURE is right, this is a core/ finding. core/ is frozen:",
        "      report it on issue #3, do not edit the rule table.",
        "    - if this disagreement is known and accepted, add a row to",
        "      KNOWN_DISAGREEMENTS with a `why` and a `resolves_when`.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The disagreements, pinned
# ---------------------------------------------------------------------------

#: The fixture names a reason code that no rule in `rules_v1.py` carries, so no
#: arrangement of fixture data can reach it. Resolving one means a new rule in
#: frozen `core/` -- a finding, never an edit made here.
KIND_ENGINE_CANNOT_EMIT_THIS_REASON: Final[str] = "engine cannot emit this reason"

#: Right status, different reason, and the rule table says so on purpose.
KIND_RULE_ORDER_BY_DESIGN: Final[str] = "rule order by design"

#: The reason code exists and a rule carries it, but this case's own data can
#: never put the engine in the state that rule tests for.
KIND_FIXTURE_CANNOT_REACH_ITS_REASON: Final[str] = "fixture cannot reach its reason"

#: The receipt prints no time AND the sender's name scores as common, and the two
#: together land the case just under `tau_accept`.
KIND_WEAK_TIME_AND_WEAK_NAME: Final[str] = "weak timestamp and weak name"

#: The engine and the fixture are each coherent and a human has not chosen
#: between them.
KIND_UNDECIDED_PRODUCT_QUESTION: Final[str] = "undecided product question"


@dataclass(frozen=True, slots=True)
class Disagreement:
    """One case where the engine's answer is not the manifest's, and why.

    This is a pin, not an exemption. The recorded engine answer is asserted in
    full -- status, fired rule and the exact set of reason codes -- so a case
    listed here is still checked as tightly as one that agrees; it is simply
    checked against a different, documented answer. `resolves_when` names the
    concrete event that deletes the row, so nobody has to reconstruct the
    argument from scratch to know whether it still applies.
    """

    kind: str
    engine_status: str
    engine_rule: str
    engine_reasons: tuple[str, ...]
    why: str
    resolves_when: str


_NO_RULE_CARRIES_IT: Final[str] = (
    "a rule carrying this reason code exists in core/decide/rules_v1.py. core/ is "
    "frozen, so that is a decision for its owners, not a fixture edit."
)

_LOW_CONFIDENCE_WHY: Final[str] = (
    "LOW_EXTRACTION_CONFIDENCE is carried by no rule, and decide() never reads "
    "claim.field_confidences at all -- so even a real Qwen-VL run reporting 0.3 "
    "confidence would still return R999 with no reason codes. The offline stub "
    "being a SHA-256 manifest lookup that cannot assess image quality is a second, "
    "independent blocker: it leaves ExtractionResult.fields empty, so "
    "service._normalise() always produces an empty field_confidences and the engine "
    "reads full confidence. Neither blocker is a fixture bug."
)

KNOWN_DISAGREEMENTS: Final[dict[str, Disagreement]] = {
    # -- the reason code has no rule ----------------------------------------
    "U03": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="UNMATCHED",
        engine_rule="R010",
        engine_reasons=("NO_CANDIDATES",),
        why=(
            "TIMESTAMP_MISMATCH is carried by no rule. The status is right and for "
            "a defensible reason -- the receipt is five days old, so nothing in the "
            "feed is retrievable and R010 fires honestly -- but the engine has no "
            "way to say *why* it found nothing."
        ),
        resolves_when=_NO_RULE_CARRIES_IT,
    ),
    "S02": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="NEEDS_REVIEW",
        engine_rule="R075",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT", "FIELD_CONTRADICTS_MATCH"),
        why=(
            "REFERENCE_MISMATCH is carried by no rule. The engine does notice the "
            "contradiction -- the reference scores REF_ELSE 0.00 and R075 routes the "
            "case to a human -- but it reports the generic FIELD_CONTRADICTS_MATCH, "
            "and it routes to NEEDS_REVIEW where the fixture expects SUSPICIOUS."
        ),
        resolves_when=_NO_RULE_CARRIES_IT,
    ),
    "D02": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="VERIFIED",
        engine_rule="R090",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT", "STRONG_FIELD_AGREEMENT"),
        why=(
            "PROOF_REUSED is image provenance, not allocation: core/duplicates.py "
            "says in as many words that it is computed from proof hashes and is not "
            "implemented there. D02 deliberately gets NO allocation, because adding "
            "one would produce DUPLICATE via TXN_ALREADY_ALLOCATED -- the right "
            "status for the wrong reason, a green test papering over a missing "
            "feature."
        ),
        resolves_when=(
            "a proof-hash rule exists and the API passes proof hashes into the "
            "decision. Until then this VERIFIED is the engine's honest answer."
        ),
    ),
    "D03": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="VERIFIED",
        engine_rule="R090",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT", "STRONG_FIELD_AGREEMENT"),
        why=(
            "As D02, plus a second problem specific to this case: D03 claims to be a "
            "cropped variant of G03's proof, but D03.jpg is an independent render "
            "rather than a derivative of G03.jpg. A perceptual-hash rule would have "
            "nothing to find here even once it exists."
        ),
        resolves_when=(
            "a proof-hash rule exists AND D03's image is re-rendered as an actual crop of G03's."
        ),
    ),
    "N04": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="NEEDS_REVIEW",
        engine_rule="R999",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT"),
        why=(
            _LOW_CONFIDENCE_WHY + " N04 is the least reachable of the three: 'blurry' "
            "has no representation in the manifest at all, so nothing about this case "
            "differs from a clean one in any data the engine can see."
        ),
        resolves_when=_NO_RULE_CARRIES_IT,
    ),
    "N05": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="NEEDS_REVIEW",
        engine_rule="R999",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT"),
        why=(
            _LOW_CONFIDENCE_WHY + " N05 is closer than N04: its raw_timestamp_text "
            "really is null and propagates as a real None, so the timestamp scores "
            "TS_MISSING 0.00 and the case does land in NEEDS_REVIEW. Only the reason "
            "is unreachable."
        ),
        resolves_when=_NO_RULE_CARRIES_IT,
    ),
    "N06": Disagreement(
        kind=KIND_ENGINE_CANNOT_EMIT_THIS_REASON,
        engine_status="VERIFIED",
        engine_rule="R090",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT", "STRONG_FIELD_AGREEMENT"),
        why=(
            _LOW_CONFIDENCE_WHY + " N06 fails in the alarming direction, and the "
            "mechanism deserves a human's attention on its own: its sender_name really "
            "is null, which scores NAME_MISSING and is then EXCLUDED from the weighted "
            "average as uncovered evidence rather than counted as disagreement. So "
            "this cropped receipt scores 0.8407 and VERIFIES, while G09 -- same rail, "
            "sender name present and read correctly -- scores 0.7647 on "
            "NAME_COMMON_ONLY and does not. Cropping the sender off a receipt "
            "currently helps it."
        ),
        resolves_when=_NO_RULE_CARRIES_IT,
    ),
    # -- right status, different reason, deliberately ------------------------
    **{
        cid: Disagreement(
            kind=KIND_RULE_ORDER_BY_DESIGN,
            engine_status="SUSPICIOUS",
            engine_rule="R030",
            engine_reasons=("AMOUNT_UNDERPAID", "CLAIM_INFLATED"),
            why=(
                "The fixture expects FIELD_CONTRADICTS_MATCH (R075); the engine "
                "reaches SUSPICIOUS through R030 CLAIM_INFLATED instead. R030 sits "
                "above R075 on purpose -- the rule table's own docstring names that "
                "ordering -- because a receipt showing twice what was received is an "
                "inflation claim first and a field contradiction second. The status "
                "the merchant sees is the one the fixture wants; only the code "
                "differs."
            ),
            resolves_when=(
                "the fixture's expected reason_code is changed to CLAIM_INFLATED in "
                "tools/build_manifest.py. That is a one-word fixture edit and the "
                "likeliest of these rows to be closed, but it changes what the demo "
                "claims these four cases prove, so it is not made here."
            ),
        )
        for cid in ("S03", "S04", "S05", "S06")
    },
    # -- the data cannot put the engine in that state ------------------------
    "U04": Disagreement(
        kind=KIND_FIXTURE_CANNOT_REACH_ITS_REASON,
        engine_status="UNMATCHED",
        engine_rule="R010",
        engine_reasons=("NO_CANDIDATES",),
        why=(
            "NAME_MISMATCH does have a rule -- R060, for a scored candidate that falls "
            "below tau_reject. But U04 carries no ledger row at all, so there is no "
            "candidate whose name could mismatch, and R010 fires first. The scenario "
            "('money sent to the wrong merchant') is coherent; the fixture just never "
            "encodes the wrong merchant's transaction."
        ),
        resolves_when=(
            "U04 gains a ledger row whose sender or receiver differs from the receipt, "
            "or its expectation changes to NO_CANDIDATES. Both are fixture edits and "
            "both change what the case demonstrates, so neither is made here."
        ),
    ),
    # -- date-only receipt plus a name that scores as common -----------------
    **{
        cid: Disagreement(
            kind=KIND_WEAK_TIME_AND_WEAK_NAME,
            engine_status="NEEDS_REVIEW",
            engine_rule="R999",
            engine_reasons=reasons,
            why=(
                "The manifest expects VERIFIED; the engine lands at 0.7647 against "
                "tau_accept 0.82 and falls through to R999. Two weak fields, neither "
                "fatal alone, combine: (1) the receipt prints '20 Aug 2026' with no "
                "time, scoring TS_DATE_ONLY 0.60 -- G01 and G02 print a time and "
                "verify at 0.8588; (2) with a one-row feed build_name_idf sees two "
                "name documents, so every token floors at name_idf_floor 0.15, below "
                "name_common_idf_t 0.30, and even a distinctive name scores "
                "NAME_COMMON_ONLY 0.20. G07 proves either weakness alone is "
                "survivable: it is date-only too, but its receipt reads 'M B Shaikh' "
                "against a ledger 'Muhammad Bilal Shaikh', scores NAME_INITIALS 0.80 "
                "and verifies at 0.8706. This cannot be fixed by editing the manifest "
                "-- render_receipts.py bakes raw_timestamp_text into the JPEG, so "
                "changing the text without re-rendering would make the manifest lie "
                "about what the receipt shows."
            ),
            resolves_when=(
                "a human chooses between re-rendering these receipts with a printed "
                "time (needs Playwright + Chromium, and the new JPEG bytes are not "
                "reproducible across encoder versions) and accepting that a date-only "
                "receipt from an unfamiliar name is not VERIFIED-grade evidence."
            ),
        )
        for cid, reasons in (
            ("G03", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G04", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            # G05 is an overpayment, so its amount evidence reads OVERPAID rather
            # than EXACT. Its reason code already matches the manifest; only the
            # status differs, and it differs for the reason above rather than
            # because of the overpayment. See the N02 row, which is the case where
            # the overpayment itself is the open question.
            ("G05", ("AMOUNT_OVERPAID", "CLAIM_CONSISTENT")),
            ("G06", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G08", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G09", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G10", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
        )
    },
    # -- nobody has answered the question ------------------------------------
    "N02": Disagreement(
        kind=KIND_UNDECIDED_PRODUCT_QUESTION,
        engine_status="VERIFIED",
        engine_rule="R080",
        engine_reasons=("AMOUNT_OVERPAID", "CLAIM_CONSISTENT", "STRONG_FIELD_AGREEMENT"),
        why=(
            "If a customer pays MORE than the order, do we ship or ask a human? Nobody "
            "has decided, and the manifest answers it both ways in the same file. G05 "
            "(Rs 2,000 against a Rs 1,500 order, +33%) expects VERIFIED / "
            "AMOUNT_OVERPAID and agrees with R080. N02 (Rs 5,000 against Rs 1,500, "
            "+233%) expects NEEDS_REVIEW / AMOUNT_OVERPAID and does not. Same rule, "
            "same reason code, opposite verdicts, both authored in "
            "tools/build_manifest.py. So this is not 'the engine is wrong' -- it is "
            "'is there an overpayment magnitude threshold', which nobody has specified "
            "and R080 does not implement. Neither expectation is edited here: "
            "rewriting one to match the engine would be answering the question quietly "
            "and burying it."
        ),
        resolves_when=(
            "a human answers that question on issue #3. Whichever way it goes, one of "
            "G05 or N02 changes, and this row goes with it."
        ),
    ),
}


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_case_reaches_its_expected_verdict(case: dict) -> None:
    """The engine's verdict for one fixture, image bytes to decision.

    A case not in `KNOWN_DISAGREEMENTS` must reach the manifest's outcome and
    carry the manifest's reason code. Reason codes are checked as a SUBSET,
    matching the convention in tests/core/test_scenarios.py: the manifest names
    one reason and the engine emits several, so dropping a code a merchant was
    shown is a regression while adding one is enrichment.

    A case in the table must instead match the answer recorded there EXACTLY --
    status, fired rule and the full set of reason codes. An exception here still
    asserts a complete verdict; it just asserts a different, documented one.
    """
    decision = _decide_case(case)
    known = KNOWN_DISAGREEMENTS.get(case["id"])

    if known is None:
        assert decision.status.value == case["expected"]["outcome"], _report(case, decision)
        assert case["expected"]["reason_code"] in {str(r) for r in decision.reasons}, _report(
            case, decision
        )
        return

    detail = (
        f"{case['id']} is a KNOWN DISAGREEMENT ({known.kind}) and the engine's answer "
        f"has MOVED.\n"
        f"  recorded : {known.engine_status} via {known.engine_rule},"
        f" reasons {sorted(known.engine_reasons)}\n"
        f"  now      : {decision.status.value} via {decision.fired_rule_id},"
        f" reasons {sorted(str(r) for r in decision.reasons)}\n"
        f"  why the row exists: {known.why}\n"
        f"  Something changed in core/ or in the fixture. Re-read the row above, then "
        f"either update it or delete it -- do not simply re-record the new answer "
        f"without deciding whether it is the right one."
    )
    assert decision.status.value == known.engine_status, detail
    assert decision.fired_rule_id == known.engine_rule, detail
    assert {str(r) for r in decision.reasons} == set(known.engine_reasons), detail


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_receipt_text_agrees_with_the_pinned_offsets(case: dict) -> None:
    """The time printed on the JPEG is the time `claimed_offset_min` describes.

    This is the guard for mistake (1) in the module docstring. `raw_timestamp_text`
    is rendered into the committed image and therefore cannot move; every other
    fixture time is an offset from `PINNED_ANCHOR`. If the two ever drift apart,
    every case flips to UNMATCHED and the fixtures get blamed for it. Currently
    true on all 30, which is why it is pinned rather than merely believed.
    """
    visible = case["visible"]
    raw = visible["raw_timestamp_text"]
    if raw is None:
        # N05's receipt genuinely has no timestamp; that is its whole scenario.
        assert case["id"] == "N05", f"{case['id']} has no raw_timestamp_text and is not N05"
        return

    expected = PINNED_ANCHOR + timedelta(minutes=visible["claimed_offset_min"])
    try:
        # Naive on purpose, as in extraction/stub.py: a receipt prints a
        # wall-clock reading with no zone, and pretending otherwise would be
        # inventing information the image does not carry. PKT is applied below,
        # which is the same assumption the extractor records.
        printed = datetime.strptime(raw, "%d %b %Y, %I:%M %p")  # noqa: DTZ007
    except ValueError:
        # A date-only receipt can only be held to the day it prints.
        printed = datetime.strptime(raw, "%d %b %Y")  # noqa: DTZ007
        assert printed.date() == expected.date(), (
            f"{case['id']}: receipt reads {raw!r} but claimed_offset_min "
            f"{visible['claimed_offset_min']} resolves to {expected.date()}"
        )
        return

    assert printed.replace(tzinfo=PKT) == expected, (
        f"{case['id']}: receipt reads {raw!r} but claimed_offset_min "
        f"{visible['claimed_offset_min']} resolves to {expected:%d %b %Y, %I:%M %p}"
    )


def test_cases_sharing_an_image_agree_on_what_it_shows() -> None:
    """Byte-identical fixtures must not disagree about their own contents.

    G01/D01 and G02/D02 are the same JPEG twice -- deliberate for D02, whose
    scenario IS exact screenshot reuse. `OfflineStubExtractor` takes the FIRST
    case whose sha256 matches, so D01's bytes always extract as G01. That is
    harmless only while the two `visible` blocks agree. This is the tripwire for
    the day someone adds a duplicate-type case whose visible data differs from its
    twin's and gets silently extracted as the wrong case.
    """
    by_hash: dict[str, list[dict]] = {}
    for case in CASES:
        by_hash.setdefault(case["images"]["sha256"], []).append(case)

    for sha, twins in by_hash.items():
        if len(twins) < 2:
            continue
        first, *rest = twins
        for other in rest:
            assert other["visible"] == first["visible"], (
                f"{first['id']} and {other['id']} are the same image ({sha[:12]}) but "
                f"describe different receipts. The extractor resolves both to "
                f"{first['id']}, so {other['id']} is being verified against data it "
                f"does not carry."
            )


# ---------------------------------------------------------------------------
# Properties of the disagreement table itself
# ---------------------------------------------------------------------------


def test_every_disagreement_names_a_real_case() -> None:
    """A row for a case that no longer exists is a claim nobody is checking."""
    unknown = set(KNOWN_DISAGREEMENTS) - {c["id"] for c in CASES}
    assert not unknown, f"KNOWN_DISAGREEMENTS names cases not in the manifest: {unknown}"


def test_every_disagreement_says_why_and_how_it_ends() -> None:
    """An exception nobody can read is worse than a failing test.

    `why` and `resolves_when` are what stop this table turning into a list of
    cases somebody once decided to ignore.
    """
    for case_id, row in KNOWN_DISAGREEMENTS.items():
        assert row.why.strip(), f"KNOWN_DISAGREEMENTS[{case_id!r}] states no `why`"
        assert row.resolves_when.strip(), (
            f"KNOWN_DISAGREEMENTS[{case_id!r}] states no `resolves_when`: a row with no "
            f"exit condition never gets deleted"
        )
        assert row.engine_reasons, (
            f"KNOWN_DISAGREEMENTS[{case_id!r}] records no reason codes; pin the "
            f"engine's actual answer or the row asserts nothing"
        )


@pytest.mark.parametrize("case_id", sorted(KNOWN_DISAGREEMENTS), ids=lambda c: c)
def test_known_disagreement_still_disagrees(case_id: str) -> None:
    """Drift fails in both directions, which is the point of this whole file.

    A row that has stopped disagreeing -- because the fixture was fixed, or a rule
    changed -- must be deleted, not left behind quietly passing. Otherwise a case
    would keep asserting a documented exception long after the exception stopped
    being true, and the file would go back to hiding things.
    """
    row = KNOWN_DISAGREEMENTS[case_id]
    expected = next(c for c in CASES if c["id"] == case_id)["expected"]
    agrees = (
        row.engine_status == expected["outcome"] and expected["reason_code"] in row.engine_reasons
    )
    assert not agrees, (
        f"KNOWN_DISAGREEMENTS[{case_id!r}] is stale: the recorded engine answer "
        f"({row.engine_status} / {sorted(row.engine_reasons)}) now satisfies the manifest "
        f"({expected['outcome']} / {expected['reason_code']}). Delete this row."
    )


def test_unreachable_reason_codes_are_carried_by_no_rule() -> None:
    """The KIND_ENGINE_CANNOT_EMIT_THIS_REASON rows say something checkable.

    Each of those rows claims the manifest's reason code appears in no rule's
    `reasons` tuple. That claim is asserted here rather than trusted, so the day
    somebody adds the missing rule this test fails and forces the row to be
    revisited instead of leaving it to sit as folklore.

    This is one half of "unreachable": AMOUNT_EXACT and CLAIM_CONSISTENT are also
    carried by no rule yet are emitted on every run, because amount evidence
    appends its own codes. The other half -- that these codes never appear in a
    real decision -- is pinned by the exact reason-set assertions above.
    """
    carried = {str(code) for rule in RULES for code in rule.reasons}
    for case_id, row in KNOWN_DISAGREEMENTS.items():
        if row.kind != KIND_ENGINE_CANNOT_EMIT_THIS_REASON:
            continue
        wanted = next(c for c in CASES if c["id"] == case_id)["expected"]["reason_code"]
        assert wanted not in carried, (
            f"{case_id}: {wanted} is now carried by a rule, so it is no longer "
            f"unreachable. Re-run the case and either delete "
            f"KNOWN_DISAGREEMENTS[{case_id!r}] or re-classify it."
        )


def test_the_harness_covers_every_case() -> None:
    """Thirty cases in the manifest, thirty cases driven end to end.

    Asserted rather than assumed: a case dropped from the parametrisation is a
    scenario nobody is checking, and it would show up only as a smaller test count
    that nobody reads.
    """
    assert len(CASES) == 30
    assert len({c["id"] for c in CASES}) == 30
