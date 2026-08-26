# ProofPay threshold-tuning dataset

> **Generated file -- do not hand-edit.**
> Produced by `tools/threshold_dataset.py`. Regenerate with:
> `cd backend && uv run python ../tools/threshold_dataset.py`

Policy `proofpay-policy-1.2.0`, fingerprint `199ffd919575d72d`. Every number below
was measured against that policy; if the fingerprint above is not the one on the
decision you are looking at, this report describes different thresholds.

This is the labelled dataset issue #1 (threshold tuning) has been blocked on. It answers
one question: *if we moved a threshold, how many of the 30 cases would change verdict,
and in which direction?* It changes no threshold and recommends none.

## 1. Every threshold in `DecisionPolicy`

Source of truth is `backend/proofpay/core/decide/policy.py`, the only module in
`proofpay.core` permitted to hold float literal thresholds. This table is generated
from that dataclass, so a threshold cannot be added there and silently omitted here.

| Threshold | Value | What it controls |
|---|---|---|
| `time_window_s` | `86,400` | Half-width of the candidate time window. Bounds which rows are retrievable at all. |
| `max_candidates` | `25` | Hard cap on the candidate union, bounding work per verification. |
| `blocking_idf_floor` | `0.15` | Floor on a name token's IDF *for blocking* -- which token a name is looked up on. |
| `ts_offset_s` | `120` | Free window before a time difference costs anything. |
| `ts_scale_s` | `900` | Gaussian scale beyond the free window; similarity is ~0.5 one scale out. |
| `ts_offset_s_date_inferred` | `21600` | The free window for a receipt that printed a date but no clock time. |
| `ts_scale_s_date_inferred` | `43200` | The Gaussian scale for that same date-only receipt. |
| `hour_artifact_tol_s` | `90` | How near a whole hour a difference must be to read as a timezone artefact. |
| `ts_sim_tight_t` | `0.98` | Decay similarity at or above which a precise reading reads `TS_TIGHT`. |
| `ts_sim_close_t` | `0.8` | Cut-point for `TS_CLOSE`, and also the bar a date-only reading must clear for `TS_DATE_ONLY`. |
| `ts_sim_loose_t` | `0.4` | Below this a timestamp stops counting as loose agreement at all. |
| `name_strong_t` | `0.92` | Token similarity at which a difference is spelling, not identity. |
| `name_initials_t` | `0.8` | Token similarity at which an expanded initial counts as agreement. |
| `name_pair_min_t` | `0.7` | Below this two tokens are unrelated and must not be paired at all. |
| `name_common_idf_t` | `0.3` | IDF-weighted score below which a name match is worthless evidence (`NAME_COMMON_ONLY`). |
| `name_idf_floor` | `0.15` | Floor applied to a token's IDF when scoring. |
| `ref_min_partial_len` | `4` | Shortest shared reference tail that counts as evidence at all. |
| `tau_accept` | `0.82` | Aggregate score at or above which a candidate may be accepted (`VERIFIED`). |
| `tau_reject` | `0.45` | Below this no candidate is credible and the claim is `UNMATCHED`. |
| `tau_margin` | `0.1` | Minimum separation between best and runner-up before the two count as interchangeable. |
| `tau_ambiguous` | `0.45` | Plausibility floor above which indistinguishable candidates are reported `AMBIGUOUS_CANDIDATES`. |
| `missing_evidence_penalty` | `0.5` | Weight an unreadable field keeps in the aggregate's denominator (0.50 = half-weight absence; below `1 - this` an absent field scores better than a weak one). |
| `w_reference` | `1` | Weight of the reference-id comparison in the aggregate score. |
| `w_amount` | `1` | Weight of the amount comparison in the aggregate score. |
| `w_timestamp` | `0.8` | Weight of the timestamp comparison in the aggregate score. |
| `w_sender_name` | `0.6` | Weight of the sender-name comparison in the aggregate score. |
| `amount_tolerance_minor` | `0` | Permitted shortfall against the order total, in paisa. |
| `inflation_material_minor` | `5,000` | Absolute over-claim below which an inflated claim is OCR noise, in paisa. |
| `inflation_material_pct` | `0.01` | ...and the fraction of what actually arrived that the over-claim must also exceed. |
| `overpayment_material_minor` | `20,000` | Absolute overpayment below which more money than asked for is a customer rounding up, in paisa. |
| `overpayment_material_pct` | `1` | ...and the multiple of the ORDER TOTAL the overpayment must also reach before a human is asked (may exceed 1.0). |
| `min_field_confidence` | `0.75` | Extraction confidence below which a scored field cannot carry a verification (`R067`). Unreachable offline: the stub extractor reports no confidences at all. |
| `tamper_signal_limit` | `1` | Image observations tolerated before a weak field match becomes `SUSPICIOUS`. |

## 2. The labelled dataset

All 30 manifest cases driven end to end -- committed JPEG bytes through
`OfflineStubExtractor` into `decide()` -- using the same manifest->engine adapter as
`backend/tests/test_manifest_end_to_end.py`, imported rather than reimplemented.

The engine reaches the manifest's **status on 20 of 30** cases,
and its status *and* stated reason on **11 of 30**. Those gaps are
diagnosed case by case in the harness's `KNOWN_DISAGREEMENTS`; they are not threshold
problems, and section 4 explains why moving a threshold will not close most of them.

### 2a. Labels

| Case | Category | Manifest expects | Engine returns | Rule | Reasons | Status agrees? |
|---|---|---|---|---|---|---|
| `G01` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | VERIFIED | R090 | AMOUNT_EXACT, CLAIM_CONSISTENT, STRONG_FIELD_AGREEMENT | yes |
| `G02` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | VERIFIED | R090 | AMOUNT_EXACT, CLAIM_CONSISTENT, STRONG_FIELD_AGREEMENT | yes |
| `G03` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | **no** |
| `G04` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | **no** |
| `G05` | VERIFIED | VERIFIED / AMOUNT_OVERPAID | NEEDS_REVIEW | R999 | AMOUNT_OVERPAID, CLAIM_CONSISTENT | **no** |
| `G06` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | **no** |
| `G07` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | VERIFIED | R090 | AMOUNT_EXACT, CLAIM_CONSISTENT, STRONG_FIELD_AGREEMENT | yes |
| `G08` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | **no** |
| `G09` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | **no** |
| `G10` | VERIFIED | VERIFIED / STRONG_FIELD_AGREEMENT | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | **no** |
| `U01` | UNMATCHED | UNMATCHED / NO_CANDIDATES | UNMATCHED | R010 | NO_CANDIDATES | yes |
| `U02` | UNMATCHED | UNMATCHED / NO_CANDIDATES | UNMATCHED | R010 | NO_CANDIDATES | yes |
| `U03` | UNMATCHED | UNMATCHED / TIMESTAMP_MISMATCH | UNMATCHED | R010 | NO_CANDIDATES | yes |
| `U04` | UNMATCHED | UNMATCHED / NAME_MISMATCH | UNMATCHED | R010 | NO_CANDIDATES | yes |
| `S01` | SUSPICIOUS | SUSPICIOUS / CLAIM_INFLATED | SUSPICIOUS | R030 | AMOUNT_UNDERPAID, CLAIM_INFLATED | yes |
| `S02` | SUSPICIOUS | SUSPICIOUS / REFERENCE_MISMATCH | NEEDS_REVIEW | R075 | AMOUNT_EXACT, CLAIM_CONSISTENT, FIELD_CONTRADICTS_MATCH | **no** |
| `S03` | SUSPICIOUS | SUSPICIOUS / FIELD_CONTRADICTS_MATCH | SUSPICIOUS | R030 | AMOUNT_UNDERPAID, CLAIM_INFLATED | yes |
| `S04` | SUSPICIOUS | SUSPICIOUS / FIELD_CONTRADICTS_MATCH | SUSPICIOUS | R030 | AMOUNT_UNDERPAID, CLAIM_INFLATED | yes |
| `S05` | SUSPICIOUS | SUSPICIOUS / FIELD_CONTRADICTS_MATCH | SUSPICIOUS | R030 | AMOUNT_UNDERPAID, CLAIM_INFLATED | yes |
| `S06` | SUSPICIOUS | SUSPICIOUS / FIELD_CONTRADICTS_MATCH | SUSPICIOUS | R030 | AMOUNT_UNDERPAID, CLAIM_INFLATED | yes |
| `D01` | DUPLICATE | DUPLICATE / TXN_ALREADY_ALLOCATED | DUPLICATE | R020 | AMOUNT_EXACT, CLAIM_CONSISTENT, TXN_ALREADY_ALLOCATED | yes |
| `D02` | DUPLICATE | DUPLICATE / PROOF_REUSED | VERIFIED | R090 | AMOUNT_EXACT, CLAIM_CONSISTENT, STRONG_FIELD_AGREEMENT | **no** |
| `D03` | DUPLICATE | DUPLICATE / PROOF_REUSED | VERIFIED | R090 | AMOUNT_EXACT, CLAIM_CONSISTENT, STRONG_FIELD_AGREEMENT | **no** |
| `D04` | DUPLICATE | DUPLICATE / TXN_ALREADY_ALLOCATED | DUPLICATE | R020 | AMOUNT_EXACT, CLAIM_CONSISTENT, TXN_ALREADY_ALLOCATED | yes |
| `N01` | NEEDS_REVIEW | NEEDS_REVIEW / AMOUNT_UNDERPAID | NEEDS_REVIEW | R070 | AMOUNT_UNDERPAID, CLAIM_CONSISTENT | yes |
| `N02` | NEEDS_REVIEW | NEEDS_REVIEW / AMOUNT_OVERPAID | NEEDS_REVIEW | R072 | AMOUNT_OVERPAID, AMOUNT_OVERPAID_MATERIAL, CLAIM_CONSISTENT | yes |
| `N03` | NEEDS_REVIEW | NEEDS_REVIEW / AMBIGUOUS_CANDIDATES | NEEDS_REVIEW | R050 | AMBIGUOUS_CANDIDATES, AMOUNT_EXACT, CLAIM_CONSISTENT | yes |
| `N04` | NEEDS_REVIEW | NEEDS_REVIEW / LOW_EXTRACTION_CONFIDENCE | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | yes |
| `N05` | NEEDS_REVIEW | NEEDS_REVIEW / LOW_EXTRACTION_CONFIDENCE | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | yes |
| `N06` | NEEDS_REVIEW | NEEDS_REVIEW / LOW_EXTRACTION_CONFIDENCE | NEEDS_REVIEW | R999 | AMOUNT_EXACT, CLAIM_CONSISTENT | yes |

### 2b. Scores -- the numbers a threshold would move

`delta tau_accept` is the winning candidate's aggregate score minus `tau_accept` (`0.82`): negative means the case fell short of acceptance, and its
magnitude is how far `tau_accept` would have to travel to change that one case.

`margin` is the winner's separation from the runner-up. **`lone` means there was no
runner-up at all** -- `CandidateRanking.margin` returns `1.0` in that case, which is a
sentinel meaning "nothing to be confused with", not a measured separation of 1.0.
Reading those as real margins is the single easiest way to misread this table.

| Case | Confidence | Best score | delta tau_accept | Margin | Cands | Dominant | Field levels |
|---|---|---|---|---|---|---|---|
| `G01` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `G02` | 0.991 | 0.9824 | +0.1624 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_STRONG, timestamp=TS_TIGHT |
| `G03` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `G04` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `G05` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `G06` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `G07` | 0.935 | 0.8706 | +0.0506 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_INITIALS, timestamp=TS_DATE_ONLY |
| `G08` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `G09` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `G10` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `U01` | 0.300 | -- | -- | lone | 0 | no | -- |
| `U02` | 0.300 | -- | -- | lone | 0 | no | -- |
| `U03` | 0.300 | -- | -- | lone | 0 | no | -- |
| `U04` | 0.300 | -- | -- | lone | 0 | no | -- |
| `S01` | 0.834 | 0.6676 | -0.1524 | lone | 1 | yes | amount=AMT_SCALED, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `S02` | 0.782 | 0.5647 | -0.2553 | lone | 1 | no | amount=AMT_EXACT, reference=REF_ELSE, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `S03` | 0.782 | 0.5647 | -0.2553 | lone | 1 | yes | amount=AMT_ELSE, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `S04` | 0.782 | 0.5647 | -0.2553 | lone | 1 | yes | amount=AMT_ELSE, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `S05` | 0.782 | 0.5647 | -0.2553 | lone | 1 | yes | amount=AMT_ELSE, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `S06` | 0.782 | 0.5647 | -0.2553 | lone | 1 | yes | amount=AMT_ELSE, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `D01` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `D02` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `D03` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `D04` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `N01` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `N02` | 0.929 | 0.8588 | +0.0388 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `N03` | 0.481 | 0.6621 | -0.1579 | 0.0000 | 2 | no | amount=AMT_EXACT, reference=REF_MISSING, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
| `N04` | 0.882 | 0.7647 | -0.0553 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
| `N05` | 0.803 | 0.7067 | -0.1133 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_MISSING |
| `N06` | 0.850 | 0.8000 | -0.0200 | lone | 1 | yes | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_MISSING, timestamp=TS_DATE_ONLY |

## 3. Sensitivity: what actually moves a verdict

Each threshold is swept across its grid **with every other threshold held at its
shipped value**, and all 30 cases are re-decided at each step. Reported below is the
nearest swept value on each side of the default that changes at least one case's
status, and exactly which cases change.

Two limits on how precisely this can be read, both structural:

- Fractional thresholds are swept at a resolution of `0.01`. A flip that truly happens
  at 0.7648 is reported at the grid point that first shows it, never more finely.
- This is **one-at-a-time** analysis. It finds thresholds that move a verdict alone. It
  cannot find a pair that only matters jointly, and several cases below sit behind two
  weak fields at once, so joint effects here are real rather than hypothetical.

A threshold that moves no verdict is checked a second time for whether it changes the
fired rule or the reason codes with the verdict left standing. That is a weaker but
real effect -- it changes what the merchant is told -- and it is tracked separately so
that neither kind gets filed as the other.

| Threshold | Default | Verdict flip below | Verdict flip above | Cases moved | Explanation-only |
|---|---|---|---|---|---|
| `time_window_s` | `86,400` | none | none | -- | -- |
| `max_candidates` | `25` | none | none | -- | `N03` |
| `blocking_idf_floor` | `0.15` | none | none | -- | -- |
| `ts_offset_s` | `120` | none | none | -- | -- |
| `ts_scale_s` | `900` | none | none | -- | -- |
| `ts_offset_s_date_inferred` | `21600` | none | none | -- | -- |
| `ts_scale_s_date_inferred` | `43200` | none | none | -- | -- |
| `hour_artifact_tol_s` | `90` | none | none | -- | -- |
| `ts_sim_tight_t` | `0.98` | none | none | -- | -- |
| `ts_sim_close_t` | `0.8` | none | none | -- | -- |
| `ts_sim_loose_t` | `0.4` | none | none | -- | -- |
| `name_strong_t` | `0.92` | none | none | -- | -- |
| `name_initials_t` | `0.8` | none | none | -- | -- |
| `name_pair_min_t` | `0.7` | none | none | -- | -- |
| `name_common_idf_t` | `0.3` | `0.15` | none | `G03`, `G04`, `G05`, `G06`, `G08`, `G09`, `G10`, `N04`, `N05` | -- |
| `name_idf_floor` | `0.15` | none | `0.3` | `G03`, `G04`, `G05`, `G06`, `G08`, `G09`, `G10`, `N04`, `N05` | -- |
| `ref_min_partial_len` | `4` | none | none | -- | -- |
| `tau_accept` | `0.82` | `0.8` | `0.86` | `D02`, `D03`, `G01`, `N06` | `N01`, `N02` |
| `tau_reject` | `0.45` | none | `0.57` | `S02`, `S03`, `S04`, `S05`, `S06` | `N03` |
| `tau_margin` | `0.1` | none | none | -- | `N03` |
| `tau_ambiguous` | `0.45` | none | none | -- | `N03` |
| `missing_evidence_penalty` | `0.5` | `0.37` | none | `N06` | -- |
| `w_reference` | `1` | `0.2` | `1.4` | `D02`, `D03`, `G01`, `N06`, `S03`, `S04`, `S05`, `S06` | `N01`, `N02` |
| `w_amount` | `1` | `0.2` | `1.4` | `D02`, `D03`, `G01`, `N06`, `S02` | `N01`, `N02` |
| `w_timestamp` | `0.8` | `0.5` | `1.6` | `G07`, `N06` | `N01`, `N02` |
| `w_sender_name` | `0.6` | `0.4` | `0.9` | `D02`, `D03`, `G01`, `N06` | `N01`, `N02` |
| `amount_tolerance_minor` | `0` | none | `50,000` | `N01` | -- |
| `inflation_material_minor` | `5,000` | none | `500,000` | `S01`, `S03`, `S04`, `S05`, `S06` | -- |
| `inflation_material_pct` | `0.01` | none | none | -- | -- |
| `overpayment_material_minor` | `20,000` | none | `500,000` | `N02` | -- |
| `overpayment_material_pct` | `1` | none | `3` | `N02` | `G05` |
| `min_field_confidence` | `0.75` | none | none | -- | -- |
| `tamper_signal_limit` | `1` | none | none | -- | -- |

### 3a. Verdict changes, in detail

**`name_common_idf_t`** (default `0.3`)

- lower it to `0.15`: `G03` NEEDS_REVIEW -> VERIFIED; `G04` NEEDS_REVIEW -> VERIFIED; `G05` NEEDS_REVIEW -> VERIFIED; `G06` NEEDS_REVIEW -> VERIFIED; `G08` NEEDS_REVIEW -> VERIFIED; `G09` NEEDS_REVIEW -> VERIFIED; `G10` NEEDS_REVIEW -> VERIFIED; `N04` NEEDS_REVIEW -> VERIFIED; `N05` NEEDS_REVIEW -> VERIFIED

**`name_idf_floor`** (default `0.15`)

- raise it to `0.3`: `G03` NEEDS_REVIEW -> VERIFIED; `G04` NEEDS_REVIEW -> VERIFIED; `G05` NEEDS_REVIEW -> VERIFIED; `G06` NEEDS_REVIEW -> VERIFIED; `G08` NEEDS_REVIEW -> VERIFIED; `G09` NEEDS_REVIEW -> VERIFIED; `G10` NEEDS_REVIEW -> VERIFIED; `N04` NEEDS_REVIEW -> VERIFIED; `N05` NEEDS_REVIEW -> VERIFIED

**`tau_accept`** (default `0.82`)

- lower it to `0.8`: `N06` NEEDS_REVIEW -> VERIFIED
- raise it to `0.86`: `G01` VERIFIED -> NEEDS_REVIEW; `D02` VERIFIED -> NEEDS_REVIEW; `D03` VERIFIED -> NEEDS_REVIEW

**`tau_reject`** (default `0.45`)

- raise it to `0.57`: `S02` NEEDS_REVIEW -> UNMATCHED; `S03` SUSPICIOUS -> UNMATCHED; `S04` SUSPICIOUS -> UNMATCHED; `S05` SUSPICIOUS -> UNMATCHED; `S06` SUSPICIOUS -> UNMATCHED

**`missing_evidence_penalty`** (default `0.5`)

- lower it to `0.37`: `N06` NEEDS_REVIEW -> VERIFIED

**`w_reference`** (default `1`)

- lower it to `0.2`: `G01` VERIFIED -> NEEDS_REVIEW; `S03` SUSPICIOUS -> UNMATCHED; `S04` SUSPICIOUS -> UNMATCHED; `S05` SUSPICIOUS -> UNMATCHED; `S06` SUSPICIOUS -> UNMATCHED; `D02` VERIFIED -> NEEDS_REVIEW; `D03` VERIFIED -> NEEDS_REVIEW
- raise it to `1.4`: `N06` NEEDS_REVIEW -> VERIFIED

**`w_amount`** (default `1`)

- lower it to `0.2`: `G01` VERIFIED -> NEEDS_REVIEW; `S02` NEEDS_REVIEW -> UNMATCHED; `D02` VERIFIED -> NEEDS_REVIEW; `D03` VERIFIED -> NEEDS_REVIEW
- raise it to `1.4`: `N06` NEEDS_REVIEW -> VERIFIED

**`w_timestamp`** (default `0.8`)

- lower it to `0.5`: `N06` NEEDS_REVIEW -> VERIFIED
- raise it to `1.6`: `G07` VERIFIED -> NEEDS_REVIEW

**`w_sender_name`** (default `0.6`)

- lower it to `0.4`: `N06` NEEDS_REVIEW -> VERIFIED
- raise it to `0.9`: `G01` VERIFIED -> NEEDS_REVIEW; `D02` VERIFIED -> NEEDS_REVIEW; `D03` VERIFIED -> NEEDS_REVIEW

**`amount_tolerance_minor`** (default `0`)

- raise it to `50,000`: `N01` NEEDS_REVIEW -> VERIFIED

**`inflation_material_minor`** (default `5,000`)

- raise it to `500,000`: `S01` SUSPICIOUS -> NEEDS_REVIEW; `S03` SUSPICIOUS -> NEEDS_REVIEW; `S04` SUSPICIOUS -> NEEDS_REVIEW; `S05` SUSPICIOUS -> NEEDS_REVIEW; `S06` SUSPICIOUS -> NEEDS_REVIEW

**`overpayment_material_minor`** (default `20,000`)

- raise it to `500,000`: `N02` NEEDS_REVIEW -> VERIFIED

**`overpayment_material_pct`** (default `1`)

- raise it to `3`: `N02` NEEDS_REVIEW -> VERIFIED

### 3b. Explanation-only changes

These thresholds move no verdict anywhere in their swept range, but do change which
rule fires or which reason codes come back. The status column in section 2 would not
notice; a merchant reading the result would.

**`max_candidates`** (default `25`)

- lower it to `1`: `N03` R050/[AMBIGUOUS_CANDIDATES, AMOUNT_EXACT, CLAIM_CONSISTENT] -> R999/[AMOUNT_EXACT, CLAIM_CONSISTENT]

**`tau_margin`** (default `0.1`)

- lower it to `0`: `N03` R050/[AMBIGUOUS_CANDIDATES, AMOUNT_EXACT, CLAIM_CONSISTENT] -> R999/[AMOUNT_EXACT, CLAIM_CONSISTENT]

**`tau_ambiguous`** (default `0.45`)

- raise it to `0.67`: `N03` R050/[AMBIGUOUS_CANDIDATES, AMOUNT_EXACT, CLAIM_CONSISTENT] -> R999/[AMOUNT_EXACT, CLAIM_CONSISTENT]

## 4. Coverage: what these 30 cases can and cannot tune

**Read this section before using the dataset above.** A threshold no fixture sits near
cannot be tuned with this data, and treating the table in section 2 as though it
constrains all 33 thresholds equally will waste an afternoon.

Of 33 thresholds, **13 can change a verdict**,
**3 change only the explanation**, and **17 change nothing
at all** anywhere in the swept ranges.

### 4a. Tunable with this dataset

These move at least one of the 30 verdicts, so this data constrains them.

| Threshold | Flip below | Flip above | Cases it can move |
|---|---|---|---|
| `name_common_idf_t` | `0.15` | none | 9 (`G03`, `G04`, `G05`, `G06`, `G08`, `G09`, `G10`, `N04`, `N05`) |
| `name_idf_floor` | none | `0.3` | 9 (`G03`, `G04`, `G05`, `G06`, `G08`, `G09`, `G10`, `N04`, `N05`) |
| `tau_accept` | `0.8` | `0.86` | 4 (`D02`, `D03`, `G01`, `N06`) |
| `tau_reject` | none | `0.57` | 5 (`S02`, `S03`, `S04`, `S05`, `S06`) |
| `missing_evidence_penalty` | `0.37` | none | 1 (`N06`) |
| `w_reference` | `0.2` | `1.4` | 8 (`D02`, `D03`, `G01`, `N06`, `S03`, `S04`, `S05`, `S06`) |
| `w_amount` | `0.2` | `1.4` | 5 (`D02`, `D03`, `G01`, `N06`, `S02`) |
| `w_timestamp` | `0.5` | `1.6` | 2 (`G07`, `N06`) |
| `w_sender_name` | `0.4` | `0.9` | 4 (`D02`, `D03`, `G01`, `N06`) |
| `amount_tolerance_minor` | none | `50,000` | 1 (`N01`) |
| `inflation_material_minor` | none | `500,000` | 5 (`S01`, `S03`, `S04`, `S05`, `S06`) |
| `overpayment_material_minor` | none | `500,000` | 1 (`N02`) |
| `overpayment_material_pct` | none | `3` | 1 (`N02`) |

### 4b. Changes the explanation only

No verdict moves, but the fired rule or the reason codes do. This dataset can tell you
these thresholds are live; it cannot tell you they accept or reject the wrong things.

| Threshold | Cases re-explained |
|---|---|
| `max_candidates` | `N03` |
| `tau_margin` | `N03` |
| `tau_ambiguous` | `N03` |

### 4c. Not exercised -- this dataset is silent

Moving any of these across its whole swept range changes nothing about any of the 30
cases: not a verdict, not a rule, not a reason code. That is **not** evidence that the
current value is right. It means these 30 cases contain no example that discriminates,
so tuning one of these needs **new fixtures, not new analysis of these**.

`refused` counts grid values the engine rejects as an invalid policy, so a threshold
that looks silent because most of its range was unreachable cannot be mistaken for one
that was fully tested and did nothing.

| Threshold | Swept range | Values tried | Refused |
|---|---|---|---|
| `time_window_s` | `0` .. `864,000` | 11 | 0 |
| `blocking_idf_floor` | `0` .. `1` | 100 | 0 |
| `ts_offset_s` | `0` .. `86,400` | 10 | 0 |
| `ts_scale_s` | `30` .. `86,400` | 8 | 0 |
| `ts_offset_s_date_inferred` | `0` .. `86,400` | 6 | 0 |
| `ts_scale_s_date_inferred` | `900` .. `172,800` | 6 | 0 |
| `hour_artifact_tol_s` | `0` .. `3,600` | 8 | 0 |
| `ts_sim_tight_t` | `0.8` .. `1` | 20 | 80 |
| `ts_sim_close_t` | `0.4` .. `0.98` | 58 | 42 |
| `ts_sim_loose_t` | `0` .. `0.8` | 80 | 20 |
| `name_strong_t` | `0.8` .. `1` | 20 | 80 |
| `name_initials_t` | `0.7` .. `0.92` | 22 | 78 |
| `name_pair_min_t` | `0` .. `0.8` | 80 | 20 |
| `ref_min_partial_len` | `1` .. `20` | 19 | 0 |
| `inflation_material_pct` | `0` .. `1` | 100 | 0 |
| `min_field_confidence` | `0` .. `1` | 100 | 0 |
| `tamper_signal_limit` | `0` .. `5` | 5 | 0 |

### 4d. The structural reasons, which no amount of tuning changes

- **Only 1 of 30 cases produces more than one scored candidate (`N03`).**
  Every threshold about *telling two candidates apart* -- `tau_margin`, `tau_ambiguous`
  -- is therefore evidenced by that one case and nothing else, which is why both land in
  4b rather than 4a: they visibly change how that case is explained, but one datapoint
  cannot locate a cut-point. It can only tell you which side of it you are currently on.
- **The 4 cases that retrieve nothing (`U01`, `U02`, `U03`, `U04`) are handed an empty feed, so they test no threshold whatsoever.**
  Three carry no ledger row in the manifest at all and `U02`'s only row is withheld as
  unsettled before `decide()` sees it. `R010` fires because there is nothing there, not
  because a cut-point was missed. They are the reason retrieval looks well-behaved, and
  they are evidence about none of it.
- **Every retrieval threshold is masked, which is why `time_window_s` is inert even at
  zero.** Blocking is a *union* of four strategies -- reference id, time window, amount,
  name phonetics -- and reference hits ignore the window entirely. In all 30 cases the
  true row is also found by reference or amount, so narrowing the time window to zero
  seconds removes no candidate and changes no verdict. This dataset cannot tell you
  anything about the time window; it never depends on it.
- **The 26 scored cases carry only 10 distinct evidence patterns between them.** Cases whose four field comparisons land on the same
  levels get the same aggregate score, cross every cut-point together, and constrain a
  threshold exactly as much as a single case would. For scoring thresholds the honest
  sample size is **10, not 30**. The repeated patterns:

  | Score | Cases | Field levels |
  |---|---|---|
  | `0.7647` | 8 (`G03`, `G04`, `G05`, `G06`, `G08`, `G09`, `G10`, `N04`) | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_DATE_ONLY |
  | `0.8588` | 7 (`G01`, `D01`, `D02`, `D03`, `D04`, `N01`, `N02`) | amount=AMT_EXACT, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |
  | `0.5647` | 4 (`S03`, `S04`, `S05`, `S06`) | amount=AMT_ELSE, reference=REF_EXACT, sender_name=NAME_COMMON_ONLY, timestamp=TS_TIGHT |

- **`NAME_COMMON_ONLY` here is an artefact of feed size, not of the names.** Each case is
  scored against its own ledger rows only, so `build_name_idf` sees one or two documents
  and floors nearly every token at `name_idf_floor`. Tuning `name_common_idf_t` or
  `name_idf_floor` against this dataset would be fitting to the fixtures' shape rather
  than to anything about Pakistani names. This is the trap most likely to be walked into.
- **2 of the disagreements in section 2 are unreachable by any threshold.** These cases expect a reason code that no rule in `rules_v1.py`
  carries (`REFERENCE_MISMATCH`, `TIMESTAMP_MISMATCH`):
  `U03`, `S02`. No policy value causes the engine to
  emit a reason the rule table does not contain, so these are `core/` findings rather
  than tuning targets, and they cap how well any threshold choice can ever score here.
- **`tamper_signal_limit` is measured against nothing.** `R040` counts only observations
  passed into `decide(observations=...)`, and the harness deliberately passes none
  (the extractor's tamper signals land in `claim.notes` and never reach the rule). The
  six `SUSPICIOUS` fixtures carry tamper metadata that no running code consumes, so this
  threshold's `not exercised` result above is a property of the wiring, not of the data.

### 4e. One thing this dataset is genuinely good for

The accept/review boundary. `tau_accept` is the one threshold with a real cluster of
cases sitting just under it, all in the `VERIFIED`-expected category, and section 3
gives the exact value at which each moves. That is a decision a human can now take with
numbers in front of them -- and it is a *product* decision (is a date-only receipt from
an unfamiliar name good enough to auto-verify?), not an arithmetic one.
