"""The hand-labelled scenario table, executed.

`scenarios.yaml` is the labelled dataset this engine's thresholds were fitted
to (guide section 8). This module is the harness that runs it: one parametrised
test per scenario, named after the scenario, so a failure line reads

    FAILED test_scenarios.py::test_scenario[demo-2-edited-screenshot-claims-5000]

and names the situation rather than an index.

Three things are asserted, in decreasing order of how much they pin down:

* **the fired rule id**, which is what catches "right answer, wrong reason" -
  R070 and R999 both say NEEDS_REVIEW, and a reordering that swaps one for the
  other is a regression even while the status column stays green;
* **the status**, the merchant-visible verdict;
* **reason and observation codes, as subsets** - adding a code to an existing
  outcome enriches an explanation, dropping one that a merchant was shown is a
  breaking change, and only the second should fail a build.

The YAML is data, not code: it holds no thresholds, no scores and no expected
confidences. Scores move when a level is re-tuned; the *verdict* is the thing a
merchant acts on, and the thing that must not move quietly.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from proofpay.core.decide.engine import decide
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.decide.rules_v1 import RULES
from proofpay.core.models import (
    Allocation,
    Decision,
    LedgerTxn,
    Order,
    PaymentClaim,
    ProofFingerprint,
)
from proofpay.core.money import Money
from proofpay.core.reasons import ObservationCode, ReasonCode, Source, Status
from proofpay.core.timex import PKT, ClaimedInstant

SCENARIO_FILE: Final[Path] = Path(__file__).with_name("scenarios.yaml")

POLICY: Final[DecisionPolicy] = DecisionPolicy()

#: Distinguishes "the scenario asserts this transaction id" from "the scenario
#: asserts *no* transaction id is named", which `null` in YAML means and which
#: is a real assertion for the ambiguous and unmatched cases.
_UNSET: Final[object] = object()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _money(raw: str | None) -> Money | None:
    """Major-unit decimal string to integer minor units.

    A string in the YAML, never a YAML float: `2000.10` parsed as a float and
    multiplied by 100 is 200009.99999999997, and this layer's entire money
    contract is that such a number can never exist.
    """
    return None if raw is None else Money.from_major(raw)


def _instant(spec: Mapping[str, Any] | None) -> ClaimedInstant | None:
    """The receipt's own reading of the clock, plus what had to be assumed.

    `local` is a wall-clock time with no offset because that is what a receipt
    prints. Resolving it against Asia/Karachi is an assumption the engine
    records (`tz_stated` stays false) rather than a fact it was given.
    """
    if spec is None:
        return None
    return ClaimedInstant.from_local(
        datetime.fromisoformat(spec["local"]),
        tz=PKT,
        granularity_s=int(spec.get("granularity_s", 1)),
        tz_stated=bool(spec.get("tz_stated", False)),
        date_inferred=bool(spec.get("date_inferred", False)),
    )


def _txn(spec: Mapping[str, Any], merchant_id: str) -> LedgerTxn:
    amount = _money(spec["amount"])
    assert amount is not None, "a ledger transaction always has an amount"
    return LedgerTxn(
        txn_id=spec["txn_id"],
        amount=amount,
        occurred_at=datetime.fromisoformat(spec["occurred_at"]),
        merchant_id=spec.get("merchant_id", merchant_id),
        provider=spec.get("provider"),
        external_id=spec.get("external_id"),
        sender_name=spec.get("sender_name"),
        receiver_name=spec.get("receiver_name"),
        source=Source(spec.get("source", Source.MERCHANT_LEDGER)),
    )


def _claim(spec: Mapping[str, Any], *, name: str, merchant_id: str) -> PaymentClaim:
    return PaymentClaim(
        claim_id=spec.get("claim_id", f"CLAIM-{name}"),
        merchant_id=spec.get("merchant_id", merchant_id),
        provider=spec.get("provider"),
        amount=_money(spec.get("amount")),
        sender_name=spec.get("sender_name"),
        receiver_name=spec.get("receiver_name"),
        reference_id=spec.get("reference_id"),
        occurred_at=_instant(spec.get("occurred_at")),
        notes=tuple(spec.get("notes", ())),
        # The content hash of the proof image. A scenario writes any stable
        # string it likes -- core compares it for equality and never interprets
        # it -- so a row can say `proof_sha256: sha-of-the-first-receipt` and
        # be read by a human. Absent means the caller never hashed the image,
        # which is exactly the state in which no reuse finding may be produced.
        proof_sha256=spec.get("proof_sha256"),
        # What the READER said about its own reading. A scenario writes the
        # extractor's own key names (`reference_id`, not `reference`) because
        # that is what a real claim carries -- `engine.CONFIDENCE_KEYS` is what
        # closes the gap, and a row that spelled the field core's way would
        # exercise the map's identity arm and prove nothing.
        field_confidences=dict(spec.get("field_confidences") or {}),
    )


def _order(spec: Mapping[str, Any] | None, merchant_id: str) -> Order | None:
    if spec is None:
        return None
    return Order(
        order_id=spec["order_id"],
        expected=_money(spec.get("expected")),
        merchant_id=spec.get("merchant_id", merchant_id),
    )


@dataclass(frozen=True, slots=True)
class Scenario:
    """One row of the table: a complete situation and its hand-written label."""

    name: str
    about: str
    now: datetime
    order: Order | None
    ledger: tuple[LedgerTxn, ...]
    allocations: tuple[Allocation, ...]
    prior_proofs: tuple[ProofFingerprint, ...]
    claim: PaymentClaim
    observations: tuple[str, ...]

    expected_status: Status | None
    expected_rule: str | None
    expected_reasons: tuple[ReasonCode, ...]
    expected_observations: tuple[str, ...]
    expected_matched_txn_id: Any  # str | None | _UNSET
    expect_invariant_violation: bool

    def run(
        self,
        policy: DecisionPolicy = POLICY,
        ledger: Sequence[LedgerTxn] | None = None,
    ) -> Decision:
        return decide(
            self.claim,
            self.order,
            self.ledger if ledger is None else ledger,
            self.allocations,
            now=self.now,
            policy=policy,
            observations=self.observations,
            prior_proofs=self.prior_proofs,
        )


def _scenario(spec: Mapping[str, Any], *, merchant_id: str, now: datetime) -> Scenario:
    name = spec["name"]
    status = spec.get("expected_status")
    return Scenario(
        name=name,
        about=str(spec.get("about", "")).strip(),
        now=datetime.fromisoformat(spec["now"]) if "now" in spec else now,
        order=_order(spec.get("order"), merchant_id),
        ledger=tuple(_txn(t, merchant_id) for t in spec.get("ledger") or ()),
        allocations=tuple(
            Allocation(txn_id=a["txn_id"], order_id=a["order_id"])
            for a in spec.get("allocations") or ()
        ),
        prior_proofs=tuple(
            ProofFingerprint(sha256=p["sha256"], order_id=p.get("order_id"))
            for p in spec.get("prior_proofs") or ()
        ),
        claim=_claim(spec["claim"], name=name, merchant_id=merchant_id),
        observations=tuple(str(ObservationCode(o)) for o in spec.get("observations") or ()),
        expected_status=None if status is None else Status(status),
        expected_rule=spec.get("expected_rule"),
        expected_reasons=tuple(ReasonCode(r) for r in spec.get("expected_reasons") or ()),
        expected_observations=tuple(
            str(ObservationCode(o)) for o in spec.get("expected_observations") or ()
        ),
        expected_matched_txn_id=spec.get("expected_matched_txn_id", _UNSET),
        expect_invariant_violation=bool(spec.get("expect_invariant_violation", False)),
    )


def load_scenarios(path: Path = SCENARIO_FILE) -> tuple[Scenario, ...]:
    """Parse the table once, at import, so a malformed row fails collection.

    `safe_load` rather than `load`: the file is data and must never be able to
    construct a Python object.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    merchant_id = raw["merchant_id"]
    now = datetime.fromisoformat(raw["now"])
    return tuple(
        _scenario(spec, merchant_id=merchant_id, now=now) for spec in raw["scenarios"]
    )


SCENARIOS: Final[tuple[Scenario, ...]] = load_scenarios()

#: Scenarios that end in a decision, as opposed to the one that ends in a
#: deliberate invariant violation.
DECIDED: Final[tuple[Scenario, ...]] = tuple(
    s for s in SCENARIOS if not s.expect_invariant_violation
)


def _ids(s: Scenario) -> str:
    return s.name


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", SCENARIOS, ids=_ids)
def test_scenario(scenario: Scenario) -> None:
    """Each hand-labelled situation produces the verdict it was labelled with."""
    if scenario.expect_invariant_violation:
        # Not a soft failure: verifying a claim against a row derived from that
        # same claim is a bug in this layer, and it must stop the pipeline
        # rather than emit a decision anybody could act on.
        with pytest.raises(AssertionError):
            scenario.run()
        return

    decision = scenario.run()

    assert decision.fired_rule_id == scenario.expected_rule, (
        f"{scenario.name}: expected rule {scenario.expected_rule}, "
        f"got {decision.fired_rule_id} with status {decision.status}"
    )
    assert decision.status is scenario.expected_status

    missing_reasons = set(scenario.expected_reasons) - set(decision.reasons)
    assert not missing_reasons, (
        f"{scenario.name}: reasons {sorted(missing_reasons)} were expected but "
        f"the decision carried {sorted(decision.reasons)}"
    )

    missing_obs = set(scenario.expected_observations) - set(decision.observations)
    assert not missing_obs, (
        f"{scenario.name}: observations {sorted(missing_obs)} were expected but "
        f"the decision carried {sorted(decision.observations)}"
    )

    if scenario.expected_matched_txn_id is not _UNSET:
        assert decision.matched_txn_id == scenario.expected_matched_txn_id


@pytest.mark.parametrize("scenario", DECIDED, ids=_ids)
def test_scenario_decision_is_well_formed(scenario: Scenario) -> None:
    """Properties every decision must hold, whatever the scenario says.

    These are cheap to assert on 29 real situations and would otherwise only be
    covered by hand-built unit cases: a verdict is always explainable, always
    stamped with the inputs that produced it, and never invents a clock.
    """
    decision = scenario.run()

    assert 0.0 <= decision.confidence <= 1.0
    assert decision.evaluated_at == scenario.now
    assert decision.policy_fingerprint == POLICY.fingerprint()
    # An outcome the merchant is asked to act on has to say why. R999 is the
    # deliberate exception: "insufficient evidence" is itself the explanation,
    # and inventing a reason code for it would be worse than the silence.
    if decision.fired_rule_id != "R999":
        assert decision.reasons, "a decision with a specific rule must carry a reason"
    if decision.status is Status.VERIFIED:
        assert decision.matched_txn_id is not None
        assert decision.evidence, "a verification must show the evidence it rests on"


@pytest.mark.parametrize("scenario", DECIDED, ids=_ids)
def test_scenario_is_stable_under_ledger_order(scenario: Scenario) -> None:
    """The feed arrives in whatever order the provider happened to page it in.

    Ranking, evidence order and reason order are all functions of the data, so
    shuffling the ledger must not move a single field of the result. This is
    the property most likely to break silently when a `sorted` key changes.
    """
    baseline = scenario.run()
    for seed in range(5):
        shuffled = random.Random(seed).sample(scenario.ledger, len(scenario.ledger))
        assert scenario.run(ledger=shuffled) == baseline


# ---------------------------------------------------------------------------
# Properties of the table itself
# ---------------------------------------------------------------------------

def test_scenario_names_are_unique() -> None:
    """Duplicate names would silently collapse two pytest ids into one."""
    names = [s.name for s in SCENARIOS]
    assert len(set(names)) == len(names)

def test_every_scenario_states_a_label() -> None:
    """A row with no expectation is a fixture nobody is checking."""
    for s in SCENARIOS:
        if s.expect_invariant_violation:
            continue
        assert s.expected_status is not None, f"{s.name} declares no expected_status"
        assert s.expected_rule is not None, f"{s.name} declares no expected_rule"
        assert s.about, f"{s.name} has no `about`: a fixture nobody can read is a liability"


def test_the_table_is_large_enough_to_fit_thresholds_against() -> None:
    """Guide section 8: roughly 25 hand-labelled scenarios, not five.

    Five scenarios can be satisfied by five special cases. The number is the
    point, so it is asserted rather than left to drift downward.
    """
    assert len(SCENARIOS) >= 25


def test_every_status_appears_in_the_table() -> None:
    """All five merchant-visible verdicts are exercised by a real situation."""
    seen = {s.expected_status for s in DECIDED}
    assert seen == set(Status)


def test_every_rule_fires_for_some_scenario() -> None:
    """The table covers the rule table.

    A rule that no scenario reaches is a rule nobody has ever seen fire, and
    the first time it does will be on a merchant's order.
    """
    fired = {s.run().fired_rule_id for s in DECIDED}
    uncovered = {r.id for r in RULES} - fired
    assert not uncovered, f"no scenario reaches {sorted(uncovered)}"


def test_the_four_demo_cases_are_present_and_correct() -> None:
    """overview.md section 8 is a contract with the demo script.

    Spelled out here rather than left implicit in the YAML: these four are what
    gets shown on stage, and a change to any of them is a change to the pitch.
    """
    by_name = {s.name: s for s in SCENARIOS}
    expected = {
        "demo-1-genuine-payment": Status.VERIFIED,
        "demo-2-edited-screenshot-claims-5000": Status.SUSPICIOUS,
        "demo-3-transaction-already-used": Status.DUPLICATE,
        "demo-4-two-equal-candidates": Status.NEEDS_REVIEW,
    }
    for name, status in expected.items():
        assert name in by_name, f"the demo case {name!r} has been removed from the table"
        assert by_name[name].run().status is status


def _sweep(field: str, grid: Sequence[float]) -> dict[float, int]:
    """Failures against the table for each value of one policy threshold.

    An invariant violation counts as a failure: a threshold that lets a claim
    verify against a customer-supplied row is not a threshold with one
    mislabelled fixture, it is a threshold that breaks the product.
    """
    out: dict[float, int] = {}
    for value in grid:
        policy = replace(POLICY, **{field: value})
        failures = 0
        for scenario in DECIDED:
            try:
                if scenario.run(policy=policy).status is not scenario.expected_status:
                    failures += 1
            except AssertionError:
                failures += 1
        out[value] = failures
    return out


def _widest_minimal_interval(sweep: Mapping[float, int]) -> tuple[float, float]:
    """The widest run of consecutive values achieving the minimum failure count."""
    best = min(sweep.values())
    widest: tuple[float, float] = (0.0, 0.0)
    run: list[float] = []
    for value in sorted(sweep):
        if sweep[value] == best:
            run.append(value)
        else:
            run = []
        if run and run[-1] - run[0] >= widest[1] - widest[0]:
            widest = (run[0], run[-1])
    return widest


def test_tau_accept_sits_inside_its_plateau() -> None:
    """Guide 8.3: fit the acceptance threshold to the table, and pick a plateau.

    The number itself is not asserted - that is `policy.py`'s to choose. What
    is asserted is the *method*: sweep `tau_accept` across its useful range,
    find the widest run of values that misclassifies the fewest fixtures, and
    require the shipped value to lie inside it. A threshold sitting on a cliff
    edge is a threshold that will move under you, and this test is what notices
    when a new fixture pushes the cliff onto the shipped value.
    """
    grid = [round(x / 100, 2) for x in range(60, 96)]
    sweep = _sweep("tau_accept", grid)
    low, high = _widest_minimal_interval(sweep)

    assert min(sweep.values()) == 0, (
        "no value of tau_accept classifies the whole table; the disagreement is "
        "between a fixture and some *other* part of the engine, not a threshold"
    )
    assert low <= POLICY.tau_accept <= high, (
        f"tau_accept={POLICY.tau_accept} is outside the plateau [{low}, {high}] "
        f"this table supports"
    )


def test_no_scenario_verifies_against_an_empty_ledger() -> None:
    """The one invariant the product rests on, swept across every scenario.

    Every claim in the table is re-run against a feed with nothing in it. No
    receipt, however internally consistent, may verify on its own evidence.
    """
    for s in SCENARIOS:
        decision = decide(
            s.claim,
            s.order,
            (),
            s.allocations,
            now=s.now,
            policy=POLICY,
            observations=s.observations,
        )
        assert decision.status is Status.UNMATCHED, f"{s.name} verified against nothing"
        assert decision.matched_txn_id is None
