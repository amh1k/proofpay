"""The 30 fixture cases as a labelled dataset for threshold tuning (issue #1).

WHY THIS EXISTS
    Issue #1 (thresholds) has been blocked on a question nobody could answer
    without editing `DecisionPolicy` by hand and re-running: *if we moved a
    threshold, how many of the 30 cases would change verdict, and in which
    direction?* This script answers it by actually moving each threshold and
    re-deciding all 30 cases, then writes the answer to a committed markdown
    report. It is a measuring instrument, not a tuner: it never changes a
    threshold in `policy.py`, and choosing new values remains a human's call.

WHAT IT PRODUCES
    `fixtures/demo/threshold_dataset.md`, in four sections:
      1. Every threshold in `DecisionPolicy`, its current value, and one line on
         what it controls.
      2. The labelled dataset -- per case, the manifest's expected verdict, the
         engine's actual verdict, the rule that fired, the reported confidence,
         the winning candidate's score and its distance from `tau_accept`.
      3. Sensitivity -- per threshold, the nearest value in each direction that
         changes any case's verdict, and exactly which cases flip and how.
      4. Coverage -- which thresholds this dataset can actually tune and which
         it cannot, derived from section 3 rather than asserted.

    Section 4 is the point of the whole exercise. A threshold no fixture sits
    near cannot be tuned with these 30 cases, and a report that quietly implies
    otherwise costs the next person an afternoon.

WHY IT IMPORTS FROM A TEST MODULE
    `backend/tests/test_manifest_end_to_end.py` owns the manifest -> engine
    adapter: which ledger rows are withheld as unsettled, how a fixture's minute
    offset resolves against `PINNED_ANCHOR`, how allocations are built. Copying
    those thirty lines into `tools/` would create a second, silently diverging
    definition of what a fixture case *means* -- which is the exact drift that
    harness was written to stop. So this imports them instead, and a change to
    the adapter moves the test suite and this report together or neither.

    The consequence, worth knowing: this script needs pytest importable, because
    the harness imports it. Run it through the backend's environment.

HOW TO RUN

    cd backend && uv run python ../tools/threshold_dataset.py

    Deterministic: `decide()` reads no clock and no randomness, so re-running
    with an unchanged engine and unchanged fixtures reproduces the report byte
    for byte and leaves the working tree clean. A diff means something moved.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Final

# Add backend to path so `proofpay` and `tests` import when run from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from proofpay.core.decide.engine import build_context, decide
from proofpay.core.decide.policy import DecisionPolicy
from proofpay.core.decide.rules_v1 import RULES
from proofpay.core.models import Allocation, LedgerTxn, Order, PaymentClaim
from tests.test_manifest_end_to_end import (
    CASES,
    NOW,
    _allocations_for,
    _claim_for,
    _ledger_for,
    _order_for,
)

REPORT_PATH: Final[Path] = REPO_ROOT / "fixtures" / "demo" / "threshold_dataset.md"

BASELINE: Final[DecisionPolicy] = DecisionPolicy()

#: `policy_id` is a label, not a number, and moving it changes no verdict. It is
#: named here rather than filtered by type so that adding a second non-threshold
#: field is a deliberate edit and not a silent exclusion.
NON_THRESHOLD_FIELDS: Final[frozenset[str]] = frozenset({"policy_id"})


# ---------------------------------------------------------------------------
# What each threshold controls
# ---------------------------------------------------------------------------

#: One line per threshold, in the engine's own terms. Condensed from the
#: comments in `core/decide/policy.py`, which remain the authority; this table
#: exists so the report is readable without opening the source.
THRESHOLD_DOC: Final[dict[str, str]] = {
    # -- retrieval (blocking, not deciding) --
    "time_window_s": "Half-width of the candidate time window. Bounds which rows are retrievable at all.",
    "max_candidates": "Hard cap on the candidate union, bounding work per verification.",
    "blocking_idf_floor": "Floor on a name token's IDF *for blocking* -- which token a name is looked up on.",
    # -- timestamp decay --
    "ts_offset_s": "Free window before a time difference costs anything.",
    "ts_scale_s": "Gaussian scale beyond the free window; similarity is ~0.5 one scale out.",
    "ts_offset_s_date_inferred": "The free window for a receipt that printed a date but no clock time.",
    "ts_scale_s_date_inferred": "The Gaussian scale for that same date-only receipt.",
    "hour_artifact_tol_s": "How near a whole hour a difference must be to read as a timezone artefact.",
    "ts_sim_tight_t": "Decay similarity at or above which a precise reading reads `TS_TIGHT`.",
    "ts_sim_close_t": "Cut-point for `TS_CLOSE`, and also the bar a date-only reading must clear for `TS_DATE_ONLY`.",
    "ts_sim_loose_t": "Below this a timestamp stops counting as loose agreement at all.",
    # -- name matching --
    "name_strong_t": "Token similarity at which a difference is spelling, not identity.",
    "name_initials_t": "Token similarity at which an expanded initial counts as agreement.",
    "name_pair_min_t": "Below this two tokens are unrelated and must not be paired at all.",
    "name_common_idf_t": "IDF-weighted score below which a name match is worthless evidence (`NAME_COMMON_ONLY`).",
    "name_idf_floor": "Floor applied to a token's IDF when scoring.",
    # -- reference ids --
    "ref_min_partial_len": "Shortest shared reference tail that counts as evidence at all.",
    # -- acceptance --
    "tau_accept": "Aggregate score at or above which a candidate may be accepted (`VERIFIED`).",
    "tau_reject": "Below this no candidate is credible and the claim is `UNMATCHED`.",
    "tau_margin": "Minimum separation between best and runner-up before the two count as interchangeable.",
    "tau_ambiguous": "Plausibility floor above which indistinguishable candidates are reported `AMBIGUOUS_CANDIDATES`.",
    "missing_evidence_penalty": "Weight an unreadable field keeps in the aggregate's denominator (0.25 = quarter-weight absence).",
    # -- field weights --
    "w_reference": "Weight of the reference-id comparison in the aggregate score.",
    "w_amount": "Weight of the amount comparison in the aggregate score.",
    "w_timestamp": "Weight of the timestamp comparison in the aggregate score.",
    "w_sender_name": "Weight of the sender-name comparison in the aggregate score.",
    # -- amounts --
    "amount_tolerance_minor": "Permitted shortfall against the order total, in paisa.",
    "inflation_material_minor": "Absolute over-claim below which an inflated claim is OCR noise, in paisa.",
    "inflation_material_pct": "...and the fraction of what actually arrived that the over-claim must also exceed.",
    # -- tamper --
    "tamper_signal_limit": "Image observations tolerated before a weak field match becomes `SUSPICIOUS`.",
}


# ---------------------------------------------------------------------------
# The sweep grids
# ---------------------------------------------------------------------------

#: Every value in 0.00..1.00, for the thresholds `__post_init__` already
#: constrains to that interval. One-hundredth resolution is stated in the report
#: because it bounds what "nearest flip" means: a flip strictly between two grid
#: points is reported at the grid point, never more precisely than that.
_UNIT_GRID: Final[tuple[float, ...]] = tuple(round(v / 100, 2) for v in range(101))

#: Field weights are only bounded below (>= 0). Three is well past the point
#: where one field outvotes the other three combined, which is the whole
#: interesting range.
_WEIGHT_GRID: Final[tuple[float, ...]] = tuple(round(v / 10, 1) for v in range(31))

#: Per-threshold sweep ranges for the quantities that are not fractions. Each is
#: chosen to span from "obviously too tight to work" to "obviously too loose to
#: mean anything", so that a threshold reported as unexercised has been given a
#: fair chance to matter rather than a narrow one.
SWEEP_GRID: Final[dict[str, tuple[float, ...]]] = {
    # seconds: one minute out to ten days, bracketing the 1-day default
    "time_window_s": (
        0,
        60,
        300,
        900,
        3600,
        10_800,
        21_600,
        43_200,
        86_400,
        172_800,
        432_000,
        864_000,
    ),
    "max_candidates": tuple(range(1, 31)),
    "blocking_idf_floor": _UNIT_GRID,
    "ts_offset_s": (0, 30, 60, 120, 300, 600, 1_800, 3_600, 7_200, 21_600, 86_400),
    "ts_scale_s": (30, 60, 300, 900, 1_800, 3_600, 7_200, 21_600, 86_400),
    "ts_offset_s_date_inferred": (0, 900, 3_600, 10_800, 21_600, 43_200, 86_400),
    "ts_scale_s_date_inferred": (900, 3_600, 10_800, 21_600, 43_200, 86_400, 172_800),
    "hour_artifact_tol_s": (0, 30, 60, 90, 120, 300, 600, 1_800, 3_600),
    "ts_sim_tight_t": _UNIT_GRID,
    "ts_sim_close_t": _UNIT_GRID,
    "ts_sim_loose_t": _UNIT_GRID,
    "name_strong_t": _UNIT_GRID,
    "name_initials_t": _UNIT_GRID,
    "name_pair_min_t": _UNIT_GRID,
    "name_common_idf_t": _UNIT_GRID,
    "name_idf_floor": _UNIT_GRID,
    "ref_min_partial_len": tuple(range(1, 21)),
    "tau_accept": _UNIT_GRID,
    "tau_reject": _UNIT_GRID,
    "tau_margin": _UNIT_GRID,
    "tau_ambiguous": _UNIT_GRID,
    "missing_evidence_penalty": _UNIT_GRID,
    "w_reference": _WEIGHT_GRID,
    "w_amount": _WEIGHT_GRID,
    "w_timestamp": _WEIGHT_GRID,
    "w_sender_name": _WEIGHT_GRID,
    # paisa: zero tolerance out to Rs. 5,000, which exceeds every order in the set
    "amount_tolerance_minor": (0, 1, 100, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000),
    "inflation_material_minor": (0, 100, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000),
    "inflation_material_pct": _UNIT_GRID,
    "tamper_signal_limit": tuple(range(6)),
}


def _check_grids_are_total() -> None:
    """Fail loudly if `policy.py` grew a threshold this script does not sweep.

    The failure mode being prevented: someone adds a threshold, this report keeps
    generating without it, and section 4 goes on claiming to describe "every
    threshold" while quietly omitting the new one. An unswept threshold reported
    as absent is worse than no report, so this raises instead.
    """
    declared = {f.name for f in fields(DecisionPolicy)} - NON_THRESHOLD_FIELDS
    for label, table in (("THRESHOLD_DOC", set(THRESHOLD_DOC)), ("SWEEP_GRID", set(SWEEP_GRID))):
        missing = declared - table
        extra = table - declared
        if missing or extra:
            raise SystemExit(
                f"{label} is out of step with DecisionPolicy.\n"
                f"  in policy but not in {label}: {sorted(missing) or 'none'}\n"
                f"  in {label} but not in policy: {sorted(extra) or 'none'}\n"
                "Add the threshold to both tables in tools/threshold_dataset.py."
            )


# ---------------------------------------------------------------------------
# Running the 30 cases
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseInputs:
    """One case's engine inputs, built once and re-decided under many policies.

    Extraction is a SHA-256 lookup over committed image bytes and does not read
    the policy, so hoisting it out of the sweep is safe and turns roughly 40,000
    file reads into 30.
    """

    claim: PaymentClaim
    order: Order
    ledger: tuple[LedgerTxn, ...]
    allocations: tuple[Allocation, ...]


def _build_inputs() -> dict[str, CaseInputs]:
    return {
        case["id"]: CaseInputs(
            claim=_claim_for(case),
            order=_order_for(case),
            ledger=_ledger_for(case),
            allocations=_allocations_for(case),
        )
        for case in CASES
    }


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the engine answered for one case: the verdict and its explanation.

    The sweep compares `status` and `(rule, reasons)` separately and on purpose.
    A threshold can leave every verdict alone and still change *why* the engine
    says what it says -- `tau_margin` and `tau_ambiguous` both do, on `N03` --
    and a report that only watched the status would file those as "changes
    nothing", which is exactly the false reassurance section 4 exists to avoid.
    """

    status: str
    rule: str
    reasons: tuple[str, ...]

    @property
    def explanation(self) -> tuple[str, tuple[str, ...]]:
        return (self.rule, self.reasons)

    def describe(self) -> str:
        return f"{self.rule}/[{', '.join(self.reasons) or '--'}]"


def _outcomes(inputs: dict[str, CaseInputs], policy: DecisionPolicy) -> dict[str, Outcome]:
    """Every case's answer under one policy. The unit the sweep compares."""
    out: dict[str, Outcome] = {}
    for case_id, ci in inputs.items():
        decision = decide(ci.claim, ci.order, ci.ledger, ci.allocations, now=NOW, policy=policy)
        out[case_id] = Outcome(
            status=decision.status.value,
            rule=decision.fired_rule_id,
            reasons=tuple(sorted(str(r) for r in decision.reasons)),
        )
    return out


@dataclass(frozen=True, slots=True)
class BaselineRow:
    """One case as the shipped policy decides it -- the labelled datapoint."""

    case_id: str
    category: str
    expected_outcome: str
    expected_reason: str
    status: str
    rule: str
    reasons: tuple[str, ...]
    confidence: float
    best_score: float | None
    margin: float
    lone_candidate: bool
    n_candidates: int
    dominant: bool
    field_levels: tuple[str, ...]


def _baseline_rows(inputs: dict[str, CaseInputs]) -> list[BaselineRow]:
    rows: list[BaselineRow] = []
    for case in CASES:
        ci = inputs[case["id"]]
        args = (ci.claim, ci.order, ci.ledger, ci.allocations)
        decision = decide(*args, now=NOW, policy=BASELINE)
        ctx = build_context(*args, now=NOW, policy=BASELINE)
        best = ctx.ranking.best
        rows.append(
            BaselineRow(
                case_id=case["id"],
                category=case["category"],
                expected_outcome=case["expected"]["outcome"],
                expected_reason=case["expected"]["reason_code"],
                status=decision.status.value,
                rule=decision.fired_rule_id,
                reasons=tuple(sorted(str(r) for r in decision.reasons)),
                confidence=decision.confidence,
                best_score=None if best is None else best.score,
                margin=ctx.ranking.margin,
                # `CandidateRanking.margin` returns 1.0 when there is no
                # runner-up. Reporting that as a separation of 1.0 would read as
                # "maximally separated" when it means "nothing to separate from",
                # so the report labels it rather than printing the number bare.
                lone_candidate=len(ctx.ranking.scored) < 2,
                n_candidates=len(ctx.ranking.scored),
                dominant=ctx.ranking.is_dominant,
                field_levels=(
                    ()
                    if best is None
                    else tuple(f"{o.field}={o.level_code}" for o in best.evidence)
                ),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Flip:
    """The nearest swept value on one side of the default that changes something."""

    value: float
    changes: tuple[tuple[str, str, str], ...]  # (case_id, before, after)


@dataclass(frozen=True, slots=True)
class Sensitivity:
    """What the 30 cases do as one threshold moves, with the rest held fixed.

    Two grades of effect, kept apart because they mean different things to
    someone tuning: `lower`/`upper` are verdict changes, and `expl_lower`/
    `expl_upper` are changes to the fired rule or reason codes with the verdict
    left standing. A threshold with only the second kind still matters -- it
    steers what the merchant is told -- but this dataset cannot be used to argue
    it accepts or rejects the wrong things.
    """

    name: str
    default: float
    lower: Flip | None
    upper: Flip | None
    expl_lower: Flip | None
    expl_upper: Flip | None
    tried: int
    rejected: int
    explored_min: float | None
    explored_max: float | None

    @property
    def exercised(self) -> bool:
        """Moves at least one verdict."""
        return self.lower is not None or self.upper is not None

    @property
    def explanation_only(self) -> bool:
        """Moves no verdict, but does change what the engine says and why."""
        return not self.exercised and (self.expl_lower is not None or self.expl_upper is not None)

    @property
    def inert(self) -> bool:
        """Changes nothing at all, anywhere in the swept range."""
        return not self.exercised and not self.explanation_only

    def cases_moved(self) -> list[str]:
        moved: set[str] = set()
        for flip in (self.lower, self.upper):
            if flip:
                moved.update(c[0] for c in flip.changes)
        return sorted(moved)

    def cases_reexplained(self) -> list[str]:
        moved: set[str] = set()
        for flip in (self.expl_lower, self.expl_upper):
            if flip:
                moved.update(c[0] for c in flip.changes)
        return sorted(moved)


def _sweep_one(
    inputs: dict[str, CaseInputs],
    baseline: dict[str, Outcome],
    name: str,
) -> Sensitivity:
    """Move one threshold across its grid; report the nearest flip either side.

    Only `name` moves -- every other threshold stays at its shipped value. This
    is a one-at-a-time sensitivity analysis and reports itself as one: it finds
    a threshold that moves a verdict on its own, and cannot find two thresholds
    that only matter jointly. Section 4 of the report says so.

    A value the engine refuses is counted and skipped rather than swallowed: the
    report prints the range actually explored, so a threshold that looks
    unexercised because most of its grid was invalid cannot be mistaken for one
    that was genuinely tested and did nothing.

    Rejection is caught in two places because the engine validates in two
    places, which is worth knowing when reading the `refused` column.
    `DecisionPolicy.__post_init__` refuses some combinations at construction
    (`tau_reject` above `tau_accept`, the timestamp ladder out of order), but the
    *name* ladder's ordering is not checked there -- `NameThresholds` enforces
    `strong >= initials >= pair_min` only when `policy.name_thresholds()` is
    called during scoring. So a policy with `name_strong_t` below
    `name_initials_t` constructs happily and raises mid-verification instead.
    """
    default = getattr(BASELINE, name)
    below: list[Flip] = []
    above: list[Flip] = []
    expl_below: list[Flip] = []
    expl_above: list[Flip] = []
    rejected = 0
    explored: list[float] = []

    for value in SWEEP_GRID[name]:
        if value == default:
            continue
        try:
            policy = replace(BASELINE, **{name: value})
            moved = _outcomes(inputs, policy)
        except ValueError:
            # Not a reachable policy: refused either by DecisionPolicy's own
            # validation or, for the name ladder, by NameThresholds at scoring.
            rejected += 1
            continue
        explored.append(value)

        status_changes = tuple(
            (cid, baseline[cid].status, moved[cid].status)
            for cid in baseline
            if baseline[cid].status != moved[cid].status
        )
        # Explanation changes are reported only for cases whose verdict held. A
        # case that flipped status obviously also changed its reasons, and
        # listing it in both places would double-count the same event.
        expl_changes = tuple(
            (cid, baseline[cid].describe(), moved[cid].describe())
            for cid in baseline
            if baseline[cid].status == moved[cid].status
            and baseline[cid].explanation != moved[cid].explanation
        )
        if status_changes:
            (below if value < default else above).append(Flip(value=value, changes=status_changes))
        if expl_changes:
            (expl_below if value < default else expl_above).append(
                Flip(value=value, changes=expl_changes)
            )

    return Sensitivity(
        name=name,
        default=default,
        # Nearest to the default on each side: the last flip found below it, the
        # first found above it, the grid being walked in ascending order.
        lower=below[-1] if below else None,
        upper=above[0] if above else None,
        expl_lower=expl_below[-1] if expl_below else None,
        expl_upper=expl_above[0] if expl_above else None,
        tried=len(explored),
        rejected=rejected,
        explored_min=min(explored) if explored else None,
        explored_max=max(explored) if explored else None,
    )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _num(value: float) -> str:
    """Render a threshold value without turning 0.82 into 0.8200000000000001."""
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:g}"


def _changes_text(changes: tuple[tuple[str, str, str], ...]) -> str:
    return "; ".join(f"`{cid}` {old} -> {new}" for cid, old, new in changes)


def _section_thresholds() -> list[str]:
    lines = [
        "## 1. Every threshold in `DecisionPolicy`",
        "",
        "Source of truth is `backend/proofpay/core/decide/policy.py`, the only module in",
        "`proofpay.core` permitted to hold float literal thresholds. This table is generated",
        "from that dataclass, so a threshold cannot be added there and silently omitted here.",
        "",
        "| Threshold | Value | What it controls |",
        "|---|---|---|",
    ]
    for f in fields(DecisionPolicy):
        if f.name in NON_THRESHOLD_FIELDS:
            continue
        lines.append(
            f"| `{f.name}` | `{_num(getattr(BASELINE, f.name))}` | {THRESHOLD_DOC[f.name]} |"
        )
    lines.append("")
    return lines


def _section_dataset(rows: list[BaselineRow]) -> list[str]:
    agree_status = sum(1 for r in rows if r.status == r.expected_outcome)
    agree_both = sum(
        1 for r in rows if r.status == r.expected_outcome and r.expected_reason in r.reasons
    )
    lines = [
        "## 2. The labelled dataset",
        "",
        f"All {len(rows)} manifest cases driven end to end -- committed JPEG bytes through",
        "`OfflineStubExtractor` into `decide()` -- using the same manifest->engine adapter as",
        "`backend/tests/test_manifest_end_to_end.py`, imported rather than reimplemented.",
        "",
        f"The engine reaches the manifest's **status on {agree_status} of {len(rows)}** cases,",
        f"and its status *and* stated reason on **{agree_both} of {len(rows)}**. Those gaps are",
        "diagnosed case by case in the harness's `KNOWN_DISAGREEMENTS`; they are not threshold",
        "problems, and section 4 explains why moving a threshold will not close most of them.",
        "",
        "### 2a. Labels",
        "",
        "| Case | Category | Manifest expects | Engine returns | Rule | Reasons | Status agrees? |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        agrees = "yes" if r.status == r.expected_outcome else "**no**"
        lines.append(
            f"| `{r.case_id}` | {r.category} | {r.expected_outcome} / {r.expected_reason} "
            f"| {r.status} | {r.rule} | {', '.join(r.reasons) or '--'} | {agrees} |"
        )

    lines += [
        "",
        "### 2b. Scores -- the numbers a threshold would move",
        "",
        (
            "`delta tau_accept` is the winning candidate's aggregate score minus "
            f"`tau_accept` (`{_num(BASELINE.tau_accept)}`): negative means the case fell short of"
            " acceptance, and its"
        ),
        "magnitude is how far `tau_accept` would have to travel to change that one case.",
        "",
        "`margin` is the winner's separation from the runner-up. **`lone` means there was no",
        "runner-up at all** -- `CandidateRanking.margin` returns `1.0` in that case, which is a",
        'sentinel meaning "nothing to be confused with", not a measured separation of 1.0.',
        "Reading those as real margins is the single easiest way to misread this table.",
        "",
        "| Case | Confidence | Best score | delta tau_accept | Margin | Cands | Dominant | Field levels |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.best_score is None:
            score_txt = "--"
            delta_txt = "--"
        else:
            score_txt = f"{r.best_score:.4f}"
            delta_txt = f"{r.best_score - BASELINE.tau_accept:+.4f}"
        margin_txt = "lone" if r.lone_candidate else f"{r.margin:.4f}"
        lines.append(
            f"| `{r.case_id}` | {r.confidence:.3f} | {score_txt} | {delta_txt} | {margin_txt} "
            f"| {r.n_candidates} | {'yes' if r.dominant else 'no'} "
            f"| {', '.join(r.field_levels) or '--'} |"
        )
    lines.append("")
    return lines


def _section_sensitivity(sens: list[Sensitivity]) -> list[str]:
    lines = [
        "## 3. Sensitivity: what actually moves a verdict",
        "",
        "Each threshold is swept across its grid **with every other threshold held at its",
        "shipped value**, and all 30 cases are re-decided at each step. Reported below is the",
        "nearest swept value on each side of the default that changes at least one case's",
        "status, and exactly which cases change.",
        "",
        "Two limits on how precisely this can be read, both structural:",
        "",
        "- Fractional thresholds are swept at a resolution of `0.01`. A flip that truly happens",
        "  at 0.7648 is reported at the grid point that first shows it, never more finely.",
        "- This is **one-at-a-time** analysis. It finds thresholds that move a verdict alone. It",
        "  cannot find a pair that only matters jointly, and several cases below sit behind two",
        "  weak fields at once, so joint effects here are real rather than hypothetical.",
        "",
        "A threshold that moves no verdict is checked a second time for whether it changes the",
        "fired rule or the reason codes with the verdict left standing. That is a weaker but",
        "real effect -- it changes what the merchant is told -- and it is tracked separately so",
        "that neither kind gets filed as the other.",
        "",
        "| Threshold | Default | Verdict flip below | Verdict flip above | Cases moved | Explanation-only |",
        "|---|---|---|---|---|---|",
    ]
    for s in sens:
        lo = f"`{_num(s.lower.value)}`" if s.lower else "none"
        hi = f"`{_num(s.upper.value)}`" if s.upper else "none"
        reexplained = s.cases_reexplained()
        lines.append(
            f"| `{s.name}` | `{_num(s.default)}` | {lo} | {hi} "
            f"| {', '.join(f'`{m}`' for m in s.cases_moved()) or '--'} "
            f"| {', '.join(f'`{m}`' for m in reexplained) or '--'} |"
        )

    lines += ["", "### 3a. Verdict changes, in detail", ""]
    any_detail = False
    for s in sens:
        if not s.exercised:
            continue
        any_detail = True
        lines.append(f"**`{s.name}`** (default `{_num(s.default)}`)")
        lines.append("")
        if s.lower:
            lines.append(f"- lower it to `{_num(s.lower.value)}`: {_changes_text(s.lower.changes)}")
        if s.upper:
            lines.append(f"- raise it to `{_num(s.upper.value)}`: {_changes_text(s.upper.changes)}")
        lines.append("")
    if not any_detail:
        lines += ["No threshold in the swept ranges changes any case's verdict.", ""]

    explain_only = [s for s in sens if s.explanation_only]
    lines += [
        "### 3b. Explanation-only changes",
        "",
        "These thresholds move no verdict anywhere in their swept range, but do change which",
        "rule fires or which reason codes come back. The status column in section 2 would not",
        "notice; a merchant reading the result would.",
        "",
    ]
    if explain_only:
        for s in explain_only:
            lines.append(f"**`{s.name}`** (default `{_num(s.default)}`)")
            lines.append("")
            if s.expl_lower:
                lines.append(
                    f"- lower it to `{_num(s.expl_lower.value)}`:"
                    f" {_changes_text(s.expl_lower.changes)}"
                )
            if s.expl_upper:
                lines.append(
                    f"- raise it to `{_num(s.expl_upper.value)}`:"
                    f" {_changes_text(s.expl_upper.changes)}"
                )
            lines.append("")
    else:
        lines += ["None.", ""]
    return lines


def _effective_sample_size(rows: list[BaselineRow]) -> list[str]:
    """How many genuinely distinct datapoints the scored cases amount to.

    Thirty cases is not thirty observations. Cases that produce byte-identical
    field outcomes produce an identical aggregate score, move across every
    cut-point together, and therefore constrain a threshold exactly as much as
    one case would. Counting the distinct evidence patterns rather than the rows
    is the difference between "we have 30 labelled examples" and the truth, so
    this is computed rather than asserted -- and it re-counts itself if the
    fixtures change.
    """
    scored = [r for r in rows if r.best_score is not None]
    clusters: dict[tuple[str, ...], list[BaselineRow]] = {}
    for row in scored:
        clusters.setdefault(row.field_levels, []).append(row)
    ranked = sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[1][0].case_id))
    duplicated = [(levels, members) for levels, members in ranked if len(members) > 1]

    lines = [
        (
            f"- **The {len(scored)} scored cases carry only {len(clusters)} distinct evidence"
            " patterns between them.** Cases whose four field comparisons land on the same"
        ),
        "  levels get the same aggregate score, cross every cut-point together, and constrain a",
        "  threshold exactly as much as a single case would. For scoring thresholds the honest",
        f"  sample size is **{len(clusters)}, not {len(rows)}**. The repeated patterns:",
        "",
        "  | Score | Cases | Field levels |",
        "  |---|---|---|",
    ]
    for levels, members in duplicated:
        ids = ", ".join(f"`{m.case_id}`" for m in members)
        lines.append(
            f"  | `{members[0].best_score:.4f}` | {len(members)} ({ids}) | {', '.join(levels)} |"
        )
    lines.append("")
    return lines


def _unreachable_reasons(rows: list[BaselineRow]) -> list[str]:
    """Cases whose expected reason code no rule in `rules_v1.py` can emit.

    Checked against `RULES` rather than against a list written down here, so the
    day someone adds the missing rule this bullet shrinks by itself instead of
    going on describing a limitation that has been fixed.

    These matter to a threshold-tuning reader for one reason: no value of any
    threshold will ever close these gaps, so they must not be read as evidence
    that the thresholds are mis-set.
    """
    carried = {str(code) for rule in RULES for code in (getattr(rule, "reasons", ()) or ())}
    blocked = [r for r in rows if r.expected_reason not in carried]
    if not blocked:
        return []
    codes = sorted({r.expected_reason for r in blocked})
    return [
        (
            f"- **{len(blocked)} of the disagreements in section 2 are unreachable by any"
            " threshold.** These cases expect a reason code that no rule in `rules_v1.py`"
        ),
        f"  carries ({', '.join(f'`{c}`' for c in codes)}):",
        f"  {', '.join(f'`{r.case_id}`' for r in blocked)}. No policy value causes the engine to",
        "  emit a reason the rule table does not contain, so these are `core/` findings rather",
        "  than tuning targets, and they cap how well any threshold choice can ever score here.",
    ]


def _section_coverage(sens: list[Sensitivity], rows: list[BaselineRow]) -> list[str]:
    """The honest coverage statement, derived from the sweep rather than asserted."""
    exercised = [s for s in sens if s.exercised]
    explain_only = [s for s in sens if s.explanation_only]
    inert = [s for s in sens if s.inert]
    multi = [r for r in rows if r.n_candidates > 1]
    no_cand = [r for r in rows if r.n_candidates == 0]

    lines = [
        "## 4. Coverage: what these 30 cases can and cannot tune",
        "",
        "**Read this section before using the dataset above.** A threshold no fixture sits near",
        "cannot be tuned with this data, and treating the table in section 2 as though it",
        f"constrains all {len(sens)} thresholds equally will waste an afternoon.",
        "",
        f"Of {len(sens)} thresholds, **{len(exercised)} can change a verdict**,",
        f"**{len(explain_only)} change only the explanation**, and **{len(inert)} change nothing",
        "at all** anywhere in the swept ranges.",
        "",
        "### 4a. Tunable with this dataset",
        "",
        "These move at least one of the 30 verdicts, so this data constrains them.",
        "",
    ]
    if exercised:
        lines += [
            "| Threshold | Flip below | Flip above | Cases it can move |",
            "|---|---|---|---|",
        ]
        for s in exercised:
            moved = s.cases_moved()
            lines.append(
                f"| `{s.name}` | {f'`{_num(s.lower.value)}`' if s.lower else 'none'} "
                f"| {f'`{_num(s.upper.value)}`' if s.upper else 'none'} "
                f"| {len(moved)} ({', '.join(f'`{m}`' for m in moved)}) |"
            )
    else:
        lines.append("None.")

    lines += [
        "",
        "### 4b. Changes the explanation only",
        "",
        "No verdict moves, but the fired rule or the reason codes do. This dataset can tell you",
        "these thresholds are live; it cannot tell you they accept or reject the wrong things.",
        "",
    ]
    if explain_only:
        lines += ["| Threshold | Cases re-explained |", "|---|---|"]
        for s in explain_only:
            lines.append(f"| `{s.name}` | {', '.join(f'`{m}`' for m in s.cases_reexplained())} |")
    else:
        lines.append("None.")

    lines += [
        "",
        "### 4c. Not exercised -- this dataset is silent",
        "",
        "Moving any of these across its whole swept range changes nothing about any of the 30",
        "cases: not a verdict, not a rule, not a reason code. That is **not** evidence that the",
        "current value is right. It means these 30 cases contain no example that discriminates,",
        "so tuning one of these needs **new fixtures, not new analysis of these**.",
        "",
        "`refused` counts grid values the engine rejects as an invalid policy, so a threshold",
        "that looks silent because most of its range was unreachable cannot be mistaken for one",
        "that was fully tested and did nothing.",
        "",
    ]
    if inert:
        lines += [
            "| Threshold | Swept range | Values tried | Refused |",
            "|---|---|---|---|",
        ]
        for s in inert:
            rng = (
                f"`{_num(s.explored_min)}` .. `{_num(s.explored_max)}`"
                if s.explored_min is not None
                else "--"
            )
            lines.append(f"| `{s.name}` | {rng} | {s.tried} | {s.rejected} |")
    else:
        lines.append("None -- every threshold moves something.")

    lines += [
        "",
        "### 4d. The structural reasons, which no amount of tuning changes",
        "",
        (
            f"- **Only {len(multi)} of {len(rows)} cases"
            f" {'produces' if len(multi) == 1 else 'produce'} more than one scored candidate"
            f"{' (' + ', '.join(f'`{r.case_id}`' for r in multi) + ')' if multi else ''}.**"
        ),
        "  Every threshold about *telling two candidates apart* -- `tau_margin`, `tau_ambiguous`",
        "  -- is therefore evidenced by that one case and nothing else, which is why both land in",
        "  4b rather than 4a: they visibly change how that case is explained, but one datapoint",
        "  cannot locate a cut-point. It can only tell you which side of it you are currently on.",
        (
            f"- **The {len(no_cand)} cases that retrieve nothing"
            f"{' (' + ', '.join(f'`{r.case_id}`' for r in no_cand) + ')' if no_cand else ''}"
            " are handed an empty feed, so they test no threshold whatsoever.**"
        ),
        "  Three carry no ledger row in the manifest at all and `U02`'s only row is withheld as",
        "  unsettled before `decide()` sees it. `R010` fires because there is nothing there, not",
        "  because a cut-point was missed. They are the reason retrieval looks well-behaved, and",
        "  they are evidence about none of it.",
        "- **Every retrieval threshold is masked, which is why `time_window_s` is inert even at",
        "  zero.** Blocking is a *union* of four strategies -- reference id, time window, amount,",
        "  name phonetics -- and reference hits ignore the window entirely. In all 30 cases the",
        "  true row is also found by reference or amount, so narrowing the time window to zero",
        "  seconds removes no candidate and changes no verdict. This dataset cannot tell you",
        "  anything about the time window; it never depends on it.",
        *_effective_sample_size(rows),
        "- **`NAME_COMMON_ONLY` here is an artefact of feed size, not of the names.** Each case is",
        "  scored against its own ledger rows only, so `build_name_idf` sees one or two documents",
        "  and floors nearly every token at `name_idf_floor`. Tuning `name_common_idf_t` or",
        "  `name_idf_floor` against this dataset would be fitting to the fixtures' shape rather",
        "  than to anything about Pakistani names. This is the trap most likely to be walked into.",
        *_unreachable_reasons(rows),
        "- **`tamper_signal_limit` is measured against nothing.** `R040` counts only observations",
        "  passed into `decide(observations=...)`, and the harness deliberately passes none",
        "  (the extractor's tamper signals land in `claim.notes` and never reach the rule). The",
        "  six `SUSPICIOUS` fixtures carry tamper metadata that no running code consumes, so this",
        "  threshold's `not exercised` result above is a property of the wiring, not of the data.",
        "",
        "### 4e. One thing this dataset is genuinely good for",
        "",
        "The accept/review boundary. `tau_accept` is the one threshold with a real cluster of",
        "cases sitting just under it, all in the `VERIFIED`-expected category, and section 3",
        "gives the exact value at which each moves. That is a decision a human can now take with",
        "numbers in front of them -- and it is a *product* decision (is a date-only receipt from",
        "an unfamiliar name good enough to auto-verify?), not an arithmetic one.",
        "",
    ]
    return lines


def build_report() -> str:
    _check_grids_are_total()
    inputs = _build_inputs()
    rows = _baseline_rows(inputs)
    baseline = _outcomes(inputs, BASELINE)

    names = [f.name for f in fields(DecisionPolicy) if f.name not in NON_THRESHOLD_FIELDS]
    sens = [_sweep_one(inputs, baseline, name) for name in names]

    lines = [
        "# ProofPay threshold-tuning dataset",
        "",
        "> **Generated file -- do not hand-edit.**",
        "> Produced by `tools/threshold_dataset.py`. Regenerate with:",
        "> `cd backend && uv run python ../tools/threshold_dataset.py`",
        "",
        f"Policy `{BASELINE.policy_id}`, fingerprint `{BASELINE.fingerprint()}`. Every number below",
        "was measured against that policy; if the fingerprint above is not the one on the",
        "decision you are looking at, this report describes different thresholds.",
        "",
        "This is the labelled dataset issue #1 (threshold tuning) has been blocked on. It answers",
        "one question: *if we moved a threshold, how many of the 30 cases would change verdict,",
        "and in which direction?* It changes no threshold and recommends none.",
        "",
    ]
    lines += _section_thresholds()
    lines += _section_dataset(rows)
    lines += _section_sensitivity(sens)
    lines += _section_coverage(sens, rows)
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> None:
    report = build_report()
    # newline="\n": `write_text` uses the platform default, which on Windows
    # rewrites every line ending to CRLF and reports the committed report as
    # modified even when not one number has changed.
    REPORT_PATH.write_text(report, encoding="utf-8", newline="\n")
    # ASCII only. A default Windows console is cp1252 and a tick mark here would
    # raise UnicodeEncodeError *after* the file was written, exiting non-zero on
    # a run that actually succeeded.
    print(f"OK  wrote {REPORT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
