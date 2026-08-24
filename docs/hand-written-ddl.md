# Hand-maintained database DDL

Alembic autogeneration does not reliably compare partial-index predicates. The following indexes
must therefore be reviewed manually whenever their models or migrations change:

| Index | Table and predicate | Invariant |
|---|---|---|
| `uq_allocation_active_txn` | `transaction_allocations (merchant_transaction_id) WHERE status = 'ACTIVE'` | One transaction can fund only one active order. |
| `uq_allocation_active_order` | `transaction_allocations (order_id) WHERE status = 'ACTIVE'` | One MVP order has at most one active payment allocation. |
| `uq_candidate_selected_attempt` | `match_candidates (verification_attempt_id) WHERE selected` | An attempt has at most one selected candidate. |
| `uq_review_assignment_active_attempt` | `review_assignments (verification_attempt_id) WHERE status IN ('OPEN', 'IN_PROGRESS')` | An attempt has at most one active reviewer. |

Each migration must specify both `sqlite_where` and `postgresql_where`. Downgrades remove these
indexes explicitly by name. Do not replace the allocation indexes with ordinary unique constraints:
released allocations intentionally permit a corrected allocation later.
