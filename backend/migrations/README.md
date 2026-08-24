# ProofPay database migrations

Alembic is the only supported way to create or change the ProofPay schema.

```bash
uv run alembic upgrade head
uv run alembic check
uv run alembic current
```

The database URL comes from `PROOFPAY_DATABASE_URL`, falling back to the application default.
Do not call `Base.metadata.create_all()` from application startup. Partial indexes are reviewed and
maintained explicitly because Alembic cannot reliably detect changes to their predicates.
