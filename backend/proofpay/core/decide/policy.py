"""Every threshold in the engine, in one versioned, hashable place.

This is the **only** module in `proofpay.core` permitted to contain float
literal thresholds. Everywhere else, a number that steers a decision arrives
through this object — `if score > 0.8:` buried in a comparison is a threshold
nobody can find, tune, or reproduce, and grepping `decide/` for float literals
should turn up nothing outside this file.

Two properties matter more than the values themselves:

* **Frozen and total.** A policy is a value. There is no partially-configured
  policy, no runtime mutation, and no threshold that lives outside it.
* **Fingerprinted.** `fingerprint()` is a sha256 over the sorted-key JSON of
  every field, truncated to 16 characters, and it is stamped onto every
  `Decision`. That is what makes an old decision reconstructable: *these*
  inputs, *this* ruleset version, *this* policy hash. Change any threshold and
  every subsequent decision carries a visibly different fingerprint.

Loading a policy from JSON/YAML is a Phase 2 adapter concern; `core` accepts a
`DecisionPolicy` and never reads a file.

**Threshold provenance.** There is no labelled dataset, and there will not be
one by demo day, so the defaults come from cost asymmetry rather than from
data (guide section 8). For a merchant a false `VERIFIED` costs the order
value; a false `NEEDS_REVIEW` costs thirty seconds. That asymmetry is roughly
100:1, so `tau_accept` sits high and `NEEDS_REVIEW` absorbs the uncertainty —
the classic three-band accept / clerical-review / reject design from
record-linkage practice.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType

from proofpay.core.compare.name import NameThresholds
from proofpay.core.compare.timestamp import TimestampParams

__all__ = ["DecisionPolicy"]


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """Every tunable number the verification engine reads."""

    policy_id: str = "proofpay-policy-1.2.0"

    # -- retrieval (blocking, not deciding) --------------------------------
    #: Half-width of the candidate time window, in seconds. A full day either
    #: side: receipts routinely carry a wrong date, and a candidate costs one
    #: comparison while a missed true match costs a wrong verdict.
    time_window_s: int = 86_400
    #: Hard cap on the candidate union. Bounds the work per verification.
    max_candidates: int = 25
    #: Floor on a name token's inverse document frequency *for blocking*, i.e.
    #: which token a name is looked up on. Deliberately a separate number from
    #: `name_idf_floor`, which floors the same quantity for scoring: one bounds
    #: recall, the other bounds evidence. Both live here so that changing
    #: either one changes the fingerprint.
    blocking_idf_floor: float = 0.15

    # -- timestamp decay ---------------------------------------------------
    #: Free window before a time difference costs anything: clocks disagree,
    #: and a provider stamps settlement while a receipt stamps initiation.
    ts_offset_s: float = 120.0
    #: Gaussian scale beyond the offset. Similarity is ~0.5 at one scale out.
    ts_scale_s: float = 900.0
    #: The same pair for a receipt that never pinned down a clock time. Six
    #: hours free, twelve hours of scale: a date-only reading is consistent
    #: with most of its day, and pretending otherwise manufactures precision.
    ts_offset_s_date_inferred: float = 21_600.0
    ts_scale_s_date_inferred: float = 43_200.0
    #: How near a whole hour a difference must be to read as a timezone
    #: artefact rather than a different transaction.
    hour_artifact_tol_s: float = 90.0
    #: Where the decay curve is cut into the rungs of the timestamp ladder.
    #: These name the rungs, but they also steer decisions - a claim that
    #: lands on `TS_CLOSE` instead of `TS_LOOSE` scores 0.85 instead of 0.50 -
    #: so they are policy, and they are fingerprinted.
    ts_sim_tight_t: float = 0.98
    ts_sim_close_t: float = 0.80
    ts_sim_loose_t: float = 0.40

    # -- name matching -----------------------------------------------------
    #: Token similarity at which a difference is spelling, not identity.
    name_strong_t: float = 0.92
    #: Token similarity at which an expanded initial counts as agreement.
    name_initials_t: float = 0.80
    #: Below this, two tokens are unrelated and must not be paired at all.
    name_pair_min_t: float = 0.70
    #: IDF-weighted score below which a name match is worthless evidence —
    #: two different customers both called "Muhammad Ali" agree exactly.
    name_common_idf_t: float = 0.30
    #: Floor applied to a token's inverse document frequency.
    name_idf_floor: float = 0.15

    # -- reference ids -----------------------------------------------------
    #: Shortest shared tail that counts as evidence at all. Four characters is
    #: roughly where a coincidental collision stops being likely in one
    #: merchant's day; three is noise, and scoring noise as a partial match is
    #: how a matcher starts matching the wrong transaction.
    ref_min_partial_len: int = 4

    # -- acceptance --------------------------------------------------------
    #: Aggregate score at or above which a candidate may be accepted.
    tau_accept: float = 0.82
    #: Below this, no candidate is credible and the claim is UNMATCHED.
    tau_reject: float = 0.45
    #: Minimum separation between the best and second-best candidate. Below
    #: it the two are interchangeable and guessing allocates the wrong money.
    tau_margin: float = 0.10
    #: How good the best of two indistinguishable candidates must be before the
    #: engine reports AMBIGUOUS_CANDIDATES rather than staying silent.
    #: Ambiguity is about *indistinguishability*, not strength: two plausible
    #: candidates nobody can tell apart are ambiguous whether or not either
    #: clears `tau_accept`. So the floor is plausibility, not acceptance, and
    #: it is constrained to `tau_reject <= tau_ambiguous <= tau_accept` - below
    #: `tau_reject` there is no credible candidate to be confused about, and
    #: above `tau_accept` a verification could slip past the ambiguity check.
    tau_ambiguous: float = 0.45
    #: How much an unreadable field costs. A field OCR could not read is not
    #: evidence *against* a candidate, so it is excluded from the aggregate's
    #: numerator — but it is not free either, or a claim carrying nothing but a
    #: name would score 1.0 on that name alone. It therefore keeps this
    #: fraction of its weight in the denominator. See `engine.aggregate_score`.
    #:
    #: **Why 0.50 and not 0.25.** At 0.25 an *absent* field was cheaper than a
    #: *weak* one, so cropping the sender's name off a receipt made it more
    #: likely to verify than printing a common name — fixture N06 (name cropped
    #: away) scored 0.8408 and VERIFIED while G09 (same rail, name read
    #: correctly but common) scored 0.7647 and did not. On a fraud product that
    #: is backwards. Removing evidence can no longer raise a claim's aggregate
    #: for any level scoring at or above `1 - missing_evidence_penalty`, which
    #: at 0.50 is every rung of every ladder except `NAME_COMMON_ONLY` (0.20)
    #: and `TS_HOUR_ART` (0.25); `test_properties.KNOWN_ABSENCE_EXPOSURES`
    #: names those two and fails the day a third appears.
    #:
    #: **Why not 1.0**, which would close the AGREE/WEAK hole outright: two
    #: labelled scenarios in `tests/core/scenarios.yaml` —
    #: `no-transaction-id-printed` and `amount-unreadable-on-receipt` — assert
    #: that a receipt which simply never printed a field still verifies, and
    #: both fall below `tau_accept` once the penalty passes 0.527. Closing the
    #: last of that hole means deleting two written-down product decisions,
    #: which is a product call and not a tuning one.
    #:
    #: **What this knob cannot fix at any setting, stated so nobody reads the
    #: paragraph above as "solved".** A CONTRADICTED field scores 0, so the
    #: bound `1 - penalty` would need a penalty of 1.0 — and 1.0 is exactly
    #: "an unreadable field argues against the candidate", which
    #: `test_an_unreadable_field_never_argues_against_a_candidate` forbids. No
    #: value satisfies both properties. So blanking a contradicted field still
    #: helps a claim, and helps it twice: the score rises AND the `R075` block
    #: disappears with the field. Measured: the same claim with a contradicting
    #: sender name answers NEEDS_REVIEW/`R075` at 0.8235, and with that name
    #: blanked answers VERIFIED/`R090` at 0.9032. Pinned and walked through the
    #: real engine by `test_properties.KNOWN_VERDICT_EXPOSURES`; closing it
    #: needs a RULE, not a number.
    missing_evidence_penalty: float = 0.50

    # -- field weights -----------------------------------------------------
    #
    # How much each field contributes to the aggregate. These are not
    # cut-points, but they steer every decision the aggregate feeds - halving
    # the name weight moves scores across `tau_accept` - so they are policy,
    # and a decision taken under different weights carries a different
    # fingerprint. A transliterated Pakistani name is the weakest of the four
    # signals (real customers share `Muhammad Ali`, receipts mask it, OCR
    # mangles it), so it weighs less than a transaction id or an amount.
    w_reference: float = 1.0
    w_amount: float = 1.0
    w_timestamp: float = 0.8
    w_sender_name: float = 0.6

    # -- amounts -----------------------------------------------------------
    #: Permitted shortfall against the order total, in minor units. Zero: the
    #: MVP requires exact equality in integer PKR paisa, and any future
    #: tolerance must be provider-specific, justified and rule-versioned.
    amount_tolerance_minor: int = 0
    #: An over-claim smaller than this is OCR noise, not an accusation.
    inflation_material_minor: int = 5_000  # Rs. 50
    #: ...and it must also be this fraction of what actually arrived, so a
    #: fixed floor does not flag rounding noise on a six-figure transfer.
    inflation_material_pct: float = 0.01
    #: An overpayment smaller than this is a customer rounding up or covering
    #: delivery, not a mistake anyone will ask for back.
    overpayment_material_minor: int = 20_000  # Rs. 200
    #: ...and it must ALSO be this multiple of what the order asked for, so a
    #: fixed floor does not send every large order to a human. Unlike
    #: `inflation_material_pct` this is a ratio to the ORDER TOTAL, and it may
    #: legitimately exceed 1.0: 1.0 means "at least as much again as the order
    #: asked for", i.e. the customer paid double. It is therefore deliberately
    #: NOT in the 0.0..1.0 validation loop below, only bounded at zero.
    #:
    #: **How much evidence is behind the specific number: only the two fixtures
    #: it reconciles.** G05 (+33%) expects VERIFIED and N02 (+233%) expects
    #: review, which pins the admissible band to `(0.3333, 2.3333]` and says
    #: nothing about where inside it the line belongs. The prose here and in
    #: `compare/amount.is_material_overpayment` motivates the rule with N02's
    #: figure — three times the order total — while the constant cuts at
    #: double, and `overpayment_material_minor` binds on neither fixture (G05's
    #: overpayment is Rs 500) and only does any work on orders under Rs 200.
    #: The fixture pair is evidence that a cut-point EXISTS; it is not evidence
    #: for 1.0. Retune against real overpayments when there are any, and do not
    #: read the two green fixtures as a validation of this value.
    overpayment_material_pct: float = 1.0

    # -- extraction quality ------------------------------------------------
    #: Extraction confidence below which a field was not read well enough to
    #: carry a verification on its own. `R067` routes an otherwise-acceptable
    #: match to a human when any field the match *depends on* came back under
    #: this bar — a number the reader itself is unsure of is not the same kind
    #: of evidence as one it read cleanly, and the aggregate score cannot say so
    #: because the score is about agreement, not about legibility.
    #:
    #: **What the extractor can actually emit, which bounds this knob.**
    #: `extraction/service._normalise` maps confidence *bands*, not scores:
    #: `high -> 1.0`, `low -> 0.5`, and `none` reports no key at all, which
    #: `PaymentClaim.confidence_for` reads as the fully-confident default of
    #: 1.0. The only value below 1.0 that exists today is therefore exactly
    #: 0.5, so every setting in the half-open interval (0.5, 1.0] behaves
    #: identically and every setting at or below 0.5 can never fire. 0.75 is
    #: the midpoint of the live band: it keeps meaning something the day the
    #: extractor learns to report a continuous score, and it does not pretend
    #: to be tuned against a distribution that does not exist yet.
    min_field_confidence: float = 0.75

    # -- tamper ------------------------------------------------------------
    #: Image observations tolerated before a weak field match becomes
    #: suspicious. One signal alone is routinely a re-saved screenshot.
    tamper_signal_limit: int = 1

    def __post_init__(self) -> None:
        """Reject a policy that cannot mean anything, at construction time.

        A policy with `tau_reject > tau_accept` has no accept band at all and
        would silently turn every verification into review; finding that out
        from a demo is worse than finding it out from a stack trace.
        """
        if self.time_window_s < 0:
            raise ValueError("time_window_s must be >= 0")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        for name in (
            "tau_accept",
            "tau_reject",
            "tau_margin",
            "tau_ambiguous",
            "missing_evidence_penalty",
            "min_field_confidence",
            "name_strong_t",
            "name_initials_t",
            "name_pair_min_t",
            "name_common_idf_t",
            "name_idf_floor",
            "blocking_idf_floor",
            "ts_sim_tight_t",
            "ts_sim_close_t",
            "ts_sim_loose_t",
            "inflation_material_pct",
        ):
            value = getattr(self, name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be within 0.0..1.0, got {value}")
        for name in ("w_reference", "w_amount", "w_timestamp", "w_sender_name"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be >= 0")
        if not (self.ts_sim_tight_t >= self.ts_sim_close_t >= self.ts_sim_loose_t):
            # The ladder is ordered most- to least-similar and its scores are
            # non-increasing; cut-points that cross would make a lower rung
            # unreachable and the explanation a lie.
            raise ValueError(
                "timestamp cut-points must satisfy tight >= close >= loose, got "
                f"{self.ts_sim_tight_t} / {self.ts_sim_close_t} / {self.ts_sim_loose_t}"
            )
        if self.ref_min_partial_len < 1:
            raise ValueError("ref_min_partial_len must be >= 1")
        if self.tau_accept < self.tau_reject:
            raise ValueError("tau_accept must be >= tau_reject")
        if self.tau_ambiguous > self.tau_accept:
            # Otherwise a ranking too close to call could still clear
            # `tau_accept`, slip past the ambiguity rule and verify one of two
            # interchangeable payments.
            raise ValueError("tau_ambiguous must be <= tau_accept")
        if self.amount_tolerance_minor < 0:
            raise ValueError("amount_tolerance_minor must be >= 0")
        if self.inflation_material_minor < 0:
            raise ValueError("inflation_material_minor must be >= 0")
        if self.overpayment_material_minor < 0:
            raise ValueError("overpayment_material_minor must be >= 0")
        if self.overpayment_material_pct < 0.0:
            # Bounded below only. A ratio to the order total above 1.0 is the
            # useful part of this knob's range, so the unit-interval loop above
            # would reject exactly the settings a merchant would want.
            raise ValueError("overpayment_material_pct must be >= 0")
        if self.tamper_signal_limit < 0:
            raise ValueError("tamper_signal_limit must be >= 0")

    # -- derived views the comparison modules consume ----------------------
    #
    # `core.compare` declares what it needs as structural Protocols and never
    # imports this module; the dependency runs one way only. These two helpers
    # are the adapters in the other direction.

    def name_thresholds(self) -> NameThresholds:
        """The four cut-points of the name ladder."""
        return NameThresholds(
            strong=self.name_strong_t,
            initials=self.name_initials_t,
            pair_min=self.name_pair_min_t,
            common_idf=self.name_common_idf_t,
        )

    def field_weights(self) -> Mapping[str, float]:
        """How much each scored field contributes to the aggregate.

        Keyed by `Comparison.field`, which is a stable identifier on the same
        footing as a level code. `engine.aggregate_score` looks a field up here
        first and only falls back to the `Comparison`'s own declared weight for
        a field this policy has never heard of.
        """
        return MappingProxyType(
            {
                "reference": self.w_reference,
                "amount": self.w_amount,
                "timestamp": self.w_timestamp,
                "sender_name": self.w_sender_name,
            }
        )

    def timestamp_params(self) -> TimestampParams:
        """The decay parameters of the timestamp ladder."""
        return TimestampParams.from_policy(self)

    def fingerprint(self) -> str:
        """Stable 16-hex-character digest of every field in this policy.

        Sorted keys and separator-free JSON so the digest depends on the
        values alone, never on field declaration order or on Python's repr.
        Stamped onto every `Decision`; two decisions with the same fingerprint
        were taken under provably identical thresholds.
        """
        blob = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]
