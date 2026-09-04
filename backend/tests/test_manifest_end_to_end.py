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
    per-case scoring reaches the manifest's status on 21 of 30 cases and its
    status *and* reason on 12; a pooled 23-row feed reaches 23 and 17. The
    pooled figure is better only because a wider feed gives `build_name_idf`
    enough documents to stop flooring every name at `name_idf_floor`, and it
    breaks U01 and U02 outright -- both expect UNMATCHED and answer
    NEEDS_REVIEW, U01 through `R050` and U02 through `R075`, because the pool
    hands them candidates their own feed does not contain. That is a scoring
    artefact, not fixture intent.

    Re-measure both numbers whenever this file's answers move, and re-measure
    them rather than adjusting them: the figures above were four counts stale
    at one point, in the same paragraph that argues against switching, so a
    reader re-opening the question would have been comparing today's pooled
    result against a per-case baseline from three changesets ago. The two
    lines that produce them are `_decide_case` over `CASES`, and the same loop
    with a `{txn_id: txn}` union of every `_ledger_for(case)` in place of the
    per-case feed.

NOTHING HERE IS WEAKENED TO REACH GREEN
    A case the engine does not satisfy is either fixed in the fixture data or
    recorded in `KNOWN_DISAGREEMENTS` with both sides named, the engine's
    current answer pinned exactly, and the event that would delete the row. No
    `skip`, no `xfail`, no assertion softened to fit: a row that stops
    disagreeing fails just as loudly as one that starts.
"""

from __future__ import annotations

import hashlib
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
from proofpay.core.models import (
    Allocation,
    Decision,
    LedgerTxn,
    Order,
    PaymentClaim,
    ProofFingerprint,
)
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
    payload = (IMAGES / f"{case_id}.jpg").read_bytes()
    claim = EXTRACTOR.extract(payload, f"e2e-{case_id}")
    return replace(
        claim,
        merchant_id=MERCHANT_ID,
        proof_id=f"proof_{case_id}",
        # Hashing the bytes is the ADAPTER's job -- core is handed the digest
        # and never computes one -- so this harness does here what
        # `api/v1/verifications.py` does in the live path. Note the contrast
        # this makes visible: `proof_id` is per-case, so D02's and G02's differ,
        # while `proof_sha256` is per-image, so D02's and G02's are equal. That
        # equality is the entire content of the PROOF_REUSED signal.
        proof_sha256=hashlib.sha256(payload).hexdigest(),
    )


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


def _prior_proofs_for(case: dict) -> tuple[ProofFingerprint, ...]:
    """The earlier submissions of THIS case's image, as the engine sees them.

    The image sibling of `_allocations_for`, and it filters the same way that
    one does not have to: only ACCEPTED proofs may be passed, because a
    submission that was itself refused consumed nothing and re-sending it is not
    reuse. No fixture needs a refused prior proof yet, which is why the manifest
    has no status key on this list -- when one does, it filters here.

    `submitted_at` is left None rather than invented. The manifest records no
    time for a prior proof, core orders a contested history by
    `(submitted_at or _EPOCH, order_id, verification_id)` and so stays
    deterministic without one, and manufacturing a plausible-looking timestamp
    would put a number in the audit trail that nothing measured.
    """
    return tuple(
        ProofFingerprint(
            sha256=proof["sha256"],
            order_id=proof["submitted_for_order_ref"],
        )
        for proof in case.get("prior_proofs", ())
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
        prior_proofs=_prior_proofs_for(case),
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
        prior_proofs=_prior_proofs_for(case),
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
        "    - if the FIXTURE is right, this is a core/ finding. Changing the",
        "      rule table is a product decision, not a fixture repair: take it",
        "      deliberately, in core/, with the reasoning written down there.",
        "    - if this disagreement is known and accepted, add a row to",
        "      KNOWN_DISAGREEMENTS with a `why` and a `resolves_when`.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The disagreements, pinned
# ---------------------------------------------------------------------------

#: The fixture names a reason code that no rule in `rules_v1.py` carries, so no
#: arrangement of fixture data can reach it. Resolving one means a new RULE, in
#: `core/decide/rules_v1.py` -- never an edit made here.
#:
#: This used to say "a new rule in frozen `core/` -- a finding, never an edit",
#: and the second half is still true while the first is not: `R025`, `R067` and
#: `R072` were all added to that table, and the D02/N02/N06 rows that sat beside
#: this constant were closed by adding them. A pin whose stated exit condition
#: asks for somebody else's permission, when the neighbouring rows were closed
#: without it, sends the next reader looking for an owner who is them.
#: The guard is the mechanism, not the ownership: no rule carries the code
#: today, and `test_unreachable_reason_codes_are_carried_by_no_rule` is what
#: keeps that honest.
KIND_ENGINE_CANNOT_EMIT_THIS_REASON: Final[str] = "engine cannot emit this reason"

#: Right status, different reason, and the rule table says so on purpose.
KIND_RULE_ORDER_BY_DESIGN: Final[str] = "rule order by design"

#: The reason code exists and a rule carries it, but this case's own data can
#: never put the engine in the state that rule tests for.
KIND_FIXTURE_CANNOT_REACH_ITS_REASON: Final[str] = "fixture cannot reach its reason"

#: The receipt prints no time AND the sender's name scores as common, and the two
#: together land the case just under `tau_accept`.
KIND_WEAK_TIME_AND_WEAK_NAME: Final[str] = "weak timestamp and weak name"


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
    "a rule carrying this reason code exists in core/decide/rules_v1.py. Adding "
    "one is a product decision about what the merchant should be told, taken in "
    "core/ with the reasoning written down there -- it is not a fixture edit, "
    "and it is not blocked on anybody's permission either."
)

_LOW_CONFIDENCE_WHY: Final[str] = (
    "the ENGINE half of this is done and the EXTRACTOR half cannot be, which is "
    "why these three rows changed kind rather than being deleted. R067 now "
    "carries LOW_EXTRACTION_CONFIDENCE, decide() reads claim.field_confidences "
    "through engine.CONFIDENCE_KEYS, and a claim carrying a low band really does "
    "land in NEEDS_REVIEW naming that code -- asserted directly in "
    "tests/core/test_engine.py and in three labelled rows of "
    "tests/core/scenarios.yaml. What no arrangement of THIS manifest can do is "
    "produce the confidence in the first place. The offline extractor is a "
    "SHA-256 manifest lookup: it never inspects a pixel, so it leaves "
    "ExtractionResult.fields empty, so service._normalise() builds an empty "
    "field_confidences, so confidence_for() returns the fully-confident default "
    "for every field. Only extraction/dashscope_ocr.py ever populates fields, and "
    "only against the live Qwen-VL endpoint. The rule is out of reach here for "
    "want of an input, not for want of a rule."
)

#: What ends the three rows above. Deliberately not "somebody implements the
#: rule" any more -- that was true once and is now false, and a pin whose stated
#: exit condition has already happened is worse than no pin at all.
_LOW_CONFIDENCE_RESOLVES_WHEN: Final[str] = (
    "the offline path can report per-field confidence bands: either the manifest "
    "carries them per case and the stub passes them through, or these cases are "
    "run against the cloud extractor. Until one of those exists there is no "
    "confidence for R067 to read. Writing a band into manifest.json by hand is "
    "specifically NOT the resolution -- the manifest records what the pipeline "
    "found, and nothing in the pipeline found this."
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
    # D02 had a row here and no longer needs one. `R025` carries PROOF_REUSED,
    # the manifest gained a `prior_proofs` key, and D02 now reaches
    # DUPLICATE / R025 / PROOF_REUSED from its own data -- naming ORD-G02, the
    # order whose byte-identical image it re-sends. Its sibling D03 is a
    # different problem entirely and keeps its row, below.
    "D03": Disagreement(
        kind=KIND_FIXTURE_CANNOT_REACH_ITS_REASON,
        engine_status="VERIFIED",
        engine_rule="R090",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT", "STRONG_FIELD_AGREEMENT"),
        why=(
            "PROOF_REUSED is reachable now -- D02 reaches it -- but only from an "
            "exact sha256 match, and D03 is the perceptual case. The old row here "
            "claimed 'D03.jpg is an independent render, a perceptual-hash rule would "
            "have nothing to find'. Half of that is measurably wrong and the "
            "conclusion is right for a better reason, so both are recorded rather "
            "than left as folklore. MEASURED over all 30 committed receipts, using "
            "the same imagehash.phash(hash_size=16) that extraction/tamper.py "
            "already computes on every upload: G03 <-> D03 is 14 bits of 256, so "
            "there IS a signal. But 45 unrelated pairs sit strictly closer, and "
            "S01 <-> S06 -- different senders, different amounts, different "
            "reference ids, different sha256 -- have an IDENTICAL 256-bit pHash. No "
            "cut-point separates reuse from coincidence here, not even 'identical "
            "hash', so a perceptual rule would answer DUPLICATE on S06 before it "
            "ever answered it on D03. That is not a fixture artefact: all 30 "
            "receipts are one template with the numbers changed, which is exactly "
            "what real receipts from one payment app are. See the measurement "
            "written down in backend/proofpay/core/proofs.py."
        ),
        resolves_when=(
            "a near-duplicate signal exists that actually separates on this corpus "
            "-- a crop-invariant hash over the receipt's text region, or a match on "
            "the extracted field set rather than on pixels -- AND D03's image is "
            "re-rendered as an actual crop of G03's so the fixture tests that "
            "signal instead of an independent render. Raising a pHash threshold "
            "until D03 goes green is specifically NOT the resolution; measure "
            "S01 <-> S06 first."
        ),
    ),
    "N04": Disagreement(
        kind=KIND_FIXTURE_CANNOT_REACH_ITS_REASON,
        engine_status="NEEDS_REVIEW",
        engine_rule="R999",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT"),
        why=(
            _LOW_CONFIDENCE_WHY + " N04 is the least reachable of the three: 'blurry' "
            "has no representation in the manifest at all, so nothing about this case "
            "differs from a clean one in any data the engine can see."
        ),
        resolves_when=_LOW_CONFIDENCE_RESOLVES_WHEN,
    ),
    "N05": Disagreement(
        kind=KIND_FIXTURE_CANNOT_REACH_ITS_REASON,
        engine_status="NEEDS_REVIEW",
        engine_rule="R999",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT"),
        why=(
            _LOW_CONFIDENCE_WHY + " N05 is closer than N04: its raw_timestamp_text "
            "really is null and propagates as a real None, so the timestamp scores "
            "TS_MISSING 0.00 and the case does land in NEEDS_REVIEW. Only the reason "
            "is unreachable."
        ),
        resolves_when=_LOW_CONFIDENCE_RESOLVES_WHEN,
    ),
    "N06": Disagreement(
        kind=KIND_FIXTURE_CANNOT_REACH_ITS_REASON,
        engine_status="NEEDS_REVIEW",
        engine_rule="R999",
        engine_reasons=("AMOUNT_EXACT", "CLAIM_CONSISTENT"),
        why=(
            _LOW_CONFIDENCE_WHY + " N06 reaches the manifest's STATUS by a different "
            "route, and the route is worth recording because it used to be a hole. Its "
            "sender_name really is null, which scores NAME_MISSING and is EXCLUDED "
            "from the weighted average as uncovered evidence rather than counted as "
            "disagreement. At missing_evidence_penalty 0.25 that made absence cheaper "
            "than weakness: this cropped receipt scored 0.8407 and VERIFIED, while G09 "
            "-- same rail, sender name present and read correctly -- scored 0.7647 on "
            "NAME_COMMON_ONLY and did not. Cropping the sender off a receipt helped "
            "it. The penalty is now 0.50, N06 scores 0.8000, falls short of tau_accept "
            "and lands in NEEDS_REVIEW, which is what the manifest asks for; only the "
            "reason code is still out of reach. N06 does still out-score G09, because "
            "removing the gap entirely needs a penalty of 0.7561 and two labelled "
            "scenarios in tests/core/scenarios.yaml put the ceiling at 0.527. What is "
            "left of the hole is named rung by rung in "
            "tests/core/test_properties.py::KNOWN_ABSENCE_EXPOSURES, which fails if it "
            "ever widens."
        ),
        resolves_when=_LOW_CONFIDENCE_RESOLVES_WHEN,
    ),
    # S03-S06 had a row here and no longer need one. They expected
    # FIELD_CONTRADICTS_MATCH while the engine reached SUSPICIOUS through R030
    # CLAIM_INFLATED, and the row proposed closing the gap by editing the
    # fixture's expectation down to CLAIM_INFLATED. It closed the other way
    # instead, and better: the contradiction is now DERIVED in
    # `core/decide/engine.py::_reasons_for` rather than being R075's private
    # property, so a claim that both over-states the amount and contradicts the
    # transaction it matched now reports both. The status was never in dispute;
    # the merchant simply gets the more serious of the two facts back.
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
            # because of the overpayment. The magnitude question that N02 used to
            # be pinned for is settled -- R072 and overpayment_material_pct -- and
            # it settles in G05's favour: +33% on a Rs 1,500 order is not a
            # material overpayment, so the new rule leaves this case exactly where
            # the date-only clock and the common-scoring name put it.
            ("G05", ("AMOUNT_OVERPAID", "CLAIM_CONSISTENT")),
            ("G06", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G08", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G09", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
            ("G10", ("AMOUNT_EXACT", "CLAIM_CONSISTENT")),
        )
    },
    # N02 used to sit here under a sixth kind, "undecided product question": the
    # manifest answered "is a big overpayment VERIFIED or NEEDS_REVIEW?" both
    # ways in one file -- G05 at +33% expecting VERIFIED, N02 at +233% expecting
    # review -- and R080 verified both. The question has since been answered
    # where a magnitude question belongs, as a threshold in DecisionPolicy:
    # `overpayment_material_minor` and `overpayment_material_pct`, read by R072.
    # N02 now reaches NEEDS_REVIEW / AMOUNT_OVERPAID on its own and needs no pin,
    # and G05's row above records why the same threshold leaves it untouched.
    # The kind went with the row: it had exactly one member, and a category
    # nothing is filed under reads as a promise that something is still open.
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
