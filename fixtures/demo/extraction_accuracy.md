# ProofPay Receipt Extraction Accuracy Report

**Mode**: `offline` | **Evaluated Cases**: 30

| Field | n | Correct | Null (Safe) | WRONG | Accuracy | Dangerous % |
|---|---|---|---|---|---|---|
| `amount` | 30 | 30 | 0 | 0 | 100.0% | **0.0%** |
| `reference_id` | 30 | 29 | 1 | 0 | 96.7% | **0.0%** |
| `sender_name` | 30 | 29 | 1 | 0 | 96.7% | **0.0%** |
| `receiver_name` | 30 | 30 | 0 | 0 | 100.0% | **0.0%** |
| `provider` | 30 | 30 | 0 | 0 | 100.0% | **0.0%** |

> [!IMPORTANT]
> **Dangerous %** measures non-null incorrect extractions.
> ProofPay target: `dangerous == 0.0%` for `amount` and `reference_id`.
> A safe abstention (null) routes to `NEEDS_REVIEW` rather than risking a false `VERIFIED`.