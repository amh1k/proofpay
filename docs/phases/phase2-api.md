# Phase 2 — Persistence and API — Best Practices

**Scope:** everything between the HTTP boundary and the disk. Phase 2 owns the schema, the migrations, the request lifecycle, tenant isolation, idempotency, upload handling, auth, and the API test harness. It does **not** own extraction or scoring — Phase 2's job is to make those callable, reproducible, and durably recorded.

**Version reality check (verified August 2026).** FastAPI is at `0.141.x`, Starlette at `1.6.0` (released 2026-08-08), Alembic at `1.19.x`. SQLAlchemy 2.1 is still **beta** (`2.1.0b3`, 2026-06-27, final targeted "end of summer 2026"). **Pin `sqlalchemy>=2.0,<2.1`.** Do not ship a hackathon on a beta ORM; the 2.0 style described here is forward-compatible with 2.1 anyway. FastAPI's own security tutorial has moved off `passlib` — it now uses **`pwdlib`** and **`PyJWT`**. Pin everything in `uv.lock` on day one and commit the lock file; a teammate resolving a different Starlette minor mid-hackathon is a real failure mode.

---

## 1. FastAPI structure for a modular monolith

### 1.1 The layout

```
backend/
  pyproject.toml            # uv, single project, no workspaces
  alembic.ini
  migrations/
    env.py
    versions/
  src/proofpay/
    main.py                 # app factory, middleware, exception handlers, router include
    settings.py             # pydantic-settings BaseSettings
    db/
      base.py               # DeclarativeBase, naming convention, type_annotation_map
      session.py            # engine, sessionmaker, get_session dependency
      models/               # ONE module per aggregate
        merchant.py user.py order.py transaction.py
        claim.py allocation.py decision.py idempotency.py upload.py
    api/
      deps.py               # SessionDep, CurrentUser, MerchantScope, IdempotencyDep
      errors.py             # ProofPayError -> HTTP mapping, RFC 9457 handler
      v1/
        router.py           # aggregates the routers below
        claims.py orders.py transactions.py auth.py health.py
      schemas/              # Pydantic v2 request/response models ONLY
    services/               # orchestration: use-cases, transactions, side effects
      verification.py       # submit_claim(): the one that matters
      allocation.py
      ingest.py
    repositories/           # all SQL lives here, all merchant-scoped
      base.py transactions.py orders.py allocations.py
    domain/                 # PURE. no fastapi, no sqlalchemy, no io
      decision/rules_v1.py scoring.py money.py normalize.py
    adapters/               # vision, storage — each with a local fallback
  tests/
```

Five layers, one direction of dependency: `api → services → repositories → db`, with `domain` importable by anything and importing nothing.

### 1.2 What to copy from `fastapi/full-stack-fastapi-template`, and what to skip

| Copy | Why |
|---|---|
| `app/api/deps.py` idiom: `SessionDep = Annotated[Session, Depends(get_db)]`, `CurrentUser = Annotated[User, Depends(get_current_user)]` | This is the single highest-value thing in the repo. Annotated aliases keep signatures to one line and make dependency composition trivial. |
| `core/config.py` — `pydantic-settings` with a typed `Settings` and one module-level `settings` | Free env validation, fails at import instead of at 2am during the demo. |
| `core/security.py` shape (`create_access_token`, `verify_password`, `get_password_hash`) | Small, correct, done. |
| `api/main.py` router aggregation + `settings.API_V1_STR` prefix | Versioned prefix costs nothing now, costs a rewrite later. |
| Alembic directory layout and `env.py` wiring | Saves 40 minutes of fiddling. |
| The initial-superuser bootstrap | You need a seeded merchant + user for the demo anyway. |

| Skip | Why |
|---|---|
| **SQLModel** | The template uses it; you should not. ProofPay needs composite unique constraints, a partial unique index with dialect-specific `WHERE`, `CheckConstraint`s, and `JSONB`. All are expressible in SQLModel via `__table_args__`, but you'll be reading SQLAlchemy docs to write them anyway while paying an extra abstraction's bugs. Use plain SQLAlchemy 2.0 + separate Pydantic schemas. |
| A single flat `crud.py` | Fine for 3 tables. You have ~9 and the interesting logic is cross-table. Use `repositories/` (one module per aggregate) — see §3, where the repository is also the tenant-isolation boundary. |
| Docker Compose + Traefik + the deployment stack | Zero-budget hackathon. `uv run fastapi dev` locally, a single free-tier container for the demo. |
| Email flows, password recovery, `emails/` templates | Not judged. |
| Sentry | Not judged. Structured logging to stdout with a request id is enough. |
| Frontend TS client generation | Actually **do** keep this one if the frontend member wants it — `openapi-ts` off your `/openapi.json` removes a whole class of integration bugs and costs one command. |

### 1.3 Where domain logic must NOT live

This is the commitment that protects "deterministic rules wrap probabilistic models; the decision engine is versioned and reproducible."

- **Not in routers.** A route body should be ≤ 15 lines: validate, call one service function, map result to a response schema. If a router imports `select()`, it's wrong.
- **Not in Pydantic validators.** Tempting: "validate the amount matches." No. A Pydantic validator can't return `SUSPICIOUS`; it can only 422. Schemas validate *shape*, never *truth*.
- **Not in SQLAlchemy models or ORM events.** No `@validates`, no `before_insert` hook that computes a score. Model-layer magic is invisible to the reader and untestable without a database — the exact opposite of "reproducible."
- **Not in Alembic migrations.** No data-massaging business rules in a migration.
- **Not in adapters.** The Qwen-VL adapter returns a raw extraction. It does not decide anything.

The decision engine's signature is the architectural line:

```python
# domain/decision/rules_v1.py  — imports: dataclasses, decimal, enum. Nothing else.
RULES_VERSION = "rules/2026-08-22.1"

def decide(claim: PaymentClaim, candidates: Sequence[CandidateMatch],
           policy: Policy, now: datetime) -> Decision: ...
```

Pure function, no `Session`, no `datetime.now()` inside (pass `now` in — otherwise it isn't reproducible), no network. The service layer loads inputs, calls `decide`, and persists the `Decision` plus its `rules_version`. This is what lets you replay any historical claim and get a byte-identical verdict, which is a demo moment worth more than another endpoint.

---

## 2. SQLAlchemy 2.0 modern style

### 2.1 Base class with a naming convention and a type map

The naming convention is not cosmetic: **Alembic cannot autogenerate changes to anonymously-named constraints**, and SQLite's `ALTER` emulation needs named constraints to work at all. Set it before you write your first model or you will be hand-editing migrations all weekend.

```python
# db/base.py
import datetime as dt
from decimal import Decimal
from typing import Any
from sqlalchemy import JSON, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONVariant = JSON().with_variant(JSONB(), "postgresql")

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {
        str: String(255),
        dict[str, Any]: JSONVariant,
        dt.datetime: DateTime(timezone=True),
    }
```

`with_variant` is how you honour "SQLite (dev) → PostgreSQL" from a single model file: JSON on SQLite, real JSONB on Postgres, one annotation.

### 2.2 Mapped / mapped_column, and reusable annotated types

```python
# db/models/_types.py
from typing import Annotated
import uuid, datetime as dt
from sqlalchemy import Uuid, ForeignKey, BigInteger, func
from sqlalchemy.orm import mapped_column

uuid_pk    = Annotated[uuid.UUID, mapped_column(Uuid, primary_key=True, default=uuid.uuid4)]
merchant_fk = Annotated[uuid.UUID, mapped_column(
    Uuid, ForeignKey("merchant.id", ondelete="CASCADE"), nullable=False, index=True)]
created    = Annotated[dt.datetime, mapped_column(
    server_default=func.now(), nullable=False)]
money      = Annotated[int, mapped_column(BigInteger, nullable=False)]  # MINOR UNITS
```

Then models read almost like a spec:

```python
class Transaction(Base):
    __tablename__ = "transaction"
    id: Mapped[uuid_pk]
    merchant_id: Mapped[merchant_fk]
    rail: Mapped[Rail]                      # native Enum on PG, VARCHAR+CHECK on SQLite
    external_txn_id: Mapped[str | None]
    amount_minor: Mapped[money]
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    occurred_at: Mapped[dt.datetime]
    sender_name_raw: Mapped[str | None]
    sender_name_norm: Mapped[str | None] = mapped_column(index=True)
    created_at: Mapped[created]

    __table_args__ = (
        UniqueConstraint("merchant_id", "rail", "external_txn_id",
                         name="uq_transaction_merchant_rail_extid"),
        Index("ix_transaction_lookup", "merchant_id", "occurred_at"),
        CheckConstraint("amount_minor >= 0", name="amount_nonneg"),
    )
```

**Money rule, non-negotiable for this project:** store **integer minor units** (`BigInteger`, paisa). Never `Float`. `Numeric` is defensible on Postgres but round-trips as `Decimal` on PG and `float` on SQLite unless you fight it — and a dev/prod difference in *money comparison* would silently change verdicts. Integers are identical on both engines. Format to rupees only in the response schema.

**UUID PKs:** use `sqlalchemy.Uuid` (renders `UUID` on PG, `CHAR(32)` on SQLite) with `default=uuid.uuid4`. UUIDv7 would index better, but `uuid.uuid7()` is stdlib only from Python 3.14 and you're on 3.12; adding `uuid_utils` for index locality is not worth a dependency this week. Auto-increment integers are a worse choice here — enumerable IDs across tenants invite exactly the IDOR bug §3 is about.

### 2.3 Session lifecycle in FastAPI

```python
# db/session.py
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = sessionmaker(engine, expire_on_commit=False, autoflush=False)

def get_session() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session          # no commit here

SessionDep = Annotated[Session, Depends(get_session)]
```

Three deliberate choices:

- **`expire_on_commit=False`.** The single most common FastAPI+SQLAlchemy bug: you `commit()` in the route, FastAPI then serialises the ORM object, every attribute is expired, SQLAlchemy tries to refresh from a closed session → `DetachedInstanceError`. Turning this off makes the returned object usable after commit. (The alternative — convert to a Pydantic response model *before* the session closes — is also correct, and you should do that too; belt and braces.)
- **`autoflush=False`.** Prevents surprise flushes mid-read that turn a read path into a write error at a confusing stack depth. Flush explicitly when you need generated IDs.
- **No commit in the dependency.** This is contested — `fastapi-sqla` and several popular blog posts auto-commit at the end of the request. **Reject that pattern for ProofPay.** An auto-committing dependency commits on the way out of a handler that has already begun writing a response, which makes "never report success before the decision is persisted" (§9) unenforceable: the response can be serialised before the commit succeeds. Commit explicitly, inside the service function, at the one point where the unit of work is complete.

**One transaction per use case, owned by the service:**

```python
# services/verification.py
def submit_claim(session: Session, scope: MerchantScope, ...) -> Decision:
    with session.begin():                 # commit on exit, rollback on exception
        claim = repo_claims.create(session, scope, ...)
        candidates = repo_txns.find_candidates(session, scope, claim)
        decision = decide(claim, candidates, policy, now=utcnow())   # pure
        if decision.state is State.VERIFIED:
            repo_alloc.allocate(session, scope, decision.transaction_id, claim.order_id)
        repo_decisions.record(session, scope, claim, decision)
    return decision
```

The allocation insert and the decision row commit **together**. If the partial unique index rejects the allocation, the whole thing rolls back and you re-decide as `DUPLICATE` — you never end up with a `VERIFIED` decision whose allocation didn't land.

### 2.4 Loading strategies and the N+1 trap

ProofPay's list endpoints (claims with their decision and order) are exactly where N+1 bites during the demo.

- **Default every relationship to `lazy="raise_on_sql"`** on merchant-owned models. It converts a silent 200-queries-per-page into a loud test failure. Then fix each failure with an explicit option. This costs about 30 minutes total and is the single best perf/discipline lever available.
- **Collections (one-to-many, many-to-many) → `selectinload()`.** One extra `SELECT ... WHERE id IN (...)`, no row fan-out.
- **Scalar many-to-one / one-to-one → `joinedload()`.** One JOIN, no fan-out.
- **Never `joinedload` a collection alongside `LIMIT`** — the JOIN multiplies rows and your limit silently truncates parents. Use `selectinload`.

```python
stmt = (select(PaymentClaim)
        .where(PaymentClaim.merchant_id == scope.merchant_id)
        .options(joinedload(PaymentClaim.order),
                 selectinload(PaymentClaim.decisions))
        .order_by(PaymentClaim.created_at.desc()).limit(50))
```

**Traps:** don't call `.unique()`-requiring `joinedload` on collections without `.unique()` on the result; don't return ORM objects straight from a route (define `response_model` and let Pydantic v2's `from_attributes=True` do the conversion inside the request scope).

---

## 3. Multi-tenant isolation

Every merchant-owned table carries `merchant_id UUID NOT NULL` with an index. That part isn't a decision. The decision is **how you guarantee no query ever forgets it.**

| Approach | Effort | Fails how | Verdict |
|---|---|---|---|
| Manual `.where(X.merchant_id == ...)` in every query | zero | One forgotten filter = cross-merchant data leak, and it's a *silent* leak that tests with one tenant never catch | Not sufficient alone |
| **Scoped repository: `merchant_id` is a required argument, all SQL lives in `repositories/`** | ~1 hour | Only if someone writes `select()` outside a repository | **Recommended** |
| `do_orm_execute` + `with_loader_criteria` global filter | ~1 hour | Silent, invisible, and does not cover `session.get()` on an already-cached identity-map object, raw `text()`, or bulk `insert()`. Also confuses teammates who can't see why a query returns nothing | Good as a *second* net, bad as the only one |
| Postgres RLS | ~half a day + a Postgres-only dev loop | Owner bypasses RLS unless you `ALTER TABLE ... FORCE ROW LEVEL SECURITY`; if migrations run as the app role, the app role owns the tables and every policy is decoration. Doesn't work on SQLite at all | Correct long-term, **wrong for this week** |

### Recommendation: scoped repository, plus a loader-criteria net, plus a test that proves it

**The scope object is created once, from the token, and is the only source of `merchant_id`.**

```python
# api/deps.py
@dataclass(frozen=True)
class MerchantScope:
    merchant_id: uuid.UUID
    user_id: uuid.UUID
    role: Role

def get_scope(user: CurrentUser) -> MerchantScope:
    return MerchantScope(user.merchant_id, user.id, user.role)

Scope = Annotated[MerchantScope, Depends(get_scope)]
```

**Rule 1 (the one to put in `CLAUDE.md` / the README): `merchant_id` is *never* accepted from a request body, query string, or path parameter. It comes from `Scope` only.** A `merchant_id` field appearing in any Pydantic request schema is a PR blocker.

**Rule 2: every repository function takes `scope` as its second parameter and applies it.** Make the base class do the applying so a human can't skip it:

```python
# repositories/base.py
class ScopedRepo[M: Base]:
    model: type[M]

    def _base(self, scope: MerchantScope) -> Select[tuple[M]]:
        return select(self.model).where(self.model.merchant_id == scope.merchant_id)

    def get(self, s: Session, scope: MerchantScope, id_: uuid.UUID) -> M | None:
        return s.scalars(self._base(scope).where(self.model.id == id_)).one_or_none()
```

**Rule 3: ban `session.get()` for merchant-owned models.** `Session.get()` on a primary key returns straight from the identity map without emitting SQL when the object is already loaded — which means no filter of any kind, loader criteria included, gets a chance to run. `repo.get(session, scope, id)` above always emits a scoped `SELECT`. Add a grep to CI if you like; a one-line note in the README is probably enough for four people.

**Rule 4: return 404, not 403, for another merchant's row.** A 403 confirms the row exists.

The cheap second net (10 minutes, do it):

```python
@event.listens_for(SessionFactory, "do_orm_execute")
def _tenant_guard(state):
    if state.is_select and not state.is_column_load and not state.is_relationship_load:
        mid = state.session.info.get("merchant_id")
        if mid is not None:
            state.statement = state.statement.options(
                with_loader_criteria(MerchantOwned, lambda cls: cls.merchant_id == mid,
                                     include_aliases=True))
```

where `MerchantOwned` is the declarative mixin every tenant table inherits. Set `session.info["merchant_id"]` in `get_scope`. Treat this as defence in depth, **not** as the guarantee — it does nothing for `INSERT`s, raw SQL, or identity-map hits.

**The test that makes this real** (write it in the first hour of Phase 2, before the endpoints exist):

```python
def test_no_endpoint_leaks_across_merchants(client, merchant_a, merchant_b):
    order_b = make_order(merchant_b)
    for path in ("/api/v1/orders/{id}", "/api/v1/claims/{id}", "/api/v1/transactions/{id}"):
        r = client.get(path.format(id=order_b.id), headers=auth(merchant_a))
        assert r.status_code == 404, path
```

Parametrise it over every merchant-owned route. This is the isolation guarantee; the code above is just how you pass it.

**What could go wrong with the recommendation:** the guarantee is a convention, and conventions decay under deadline. The failure mode is a teammate writing an ad-hoc `session.execute(select(Transaction)...)` in a service or a router at 3am. Mitigations, in order of cost: the cross-tenant test above (do it), the loader-criteria net (do it), a lint rule banning `select(` outside `repositories/` (do it if it takes under 10 minutes), RLS (don't).

**If you later want RLS** — the two things that will burn you: (1) run migrations as a *different, owning* role than the app role, or the app role bypasses its own policies; (2) `ALTER TABLE t FORCE ROW LEVEL SECURITY` on every table, and set the tenant with `SET LOCAL app.merchant_id = ...` inside the transaction (`SET LOCAL`, not `SET`, or the value leaks into the next request through the connection pool). That connection-pool leak is the classic production incident and is another reason to skip RLS this week.

---

## 4. Idempotency keys bound to a request fingerprint

Merchants retry uploads on flaky Pakistani mobile networks. Without idempotency, one retry creates a second `PaymentClaim` and a second allocation attempt — precisely the duplicate that ProofPay is supposed to detect.

The IETF draft (`draft-ietf-httpapi-idempotency-key-header-07`) is the standard to follow: header `Idempotency-Key`, replay returns the original result, **409** when the original is still in flight, and **422** when the same key arrives with a different fingerprint. (Stripe returns 400 for the mismatch case; the draft says 422. Pick 409 for in-flight and 422 for mismatch, and document it. The important thing is that a mismatch is *loudly rejected*, never silently served from cache — for money, silently reinterpreting a request is catastrophic.)

### 4.1 Schema

```python
class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    id: Mapped[uuid_pk]
    merchant_id: Mapped[merchant_fk]
    key: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))     # sha256 hex
    state: Mapped[IdemState]                                  # IN_PROGRESS | COMPLETED
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None]              # JSON/JSONB
    resource_id: Mapped[uuid.UUID | None]                     # the created claim/decision
    created_at: Mapped[created]
    expires_at: Mapped[dt.datetime]                           # created_at + 24h

    __table_args__ = (
        UniqueConstraint("merchant_id", "key", name="uq_idem_merchant_key"),
    )
```

The unique constraint is scoped by `merchant_id` — one merchant must not be able to probe or collide with another's keys.

### 4.2 Fingerprint

Hash exactly what determines the outcome, canonically:

```python
def fingerprint(method: str, path: str, scope: MerchantScope,
                fields: Mapping[str, str], file_sha256: str | None) -> str:
    payload = {
        "m": method, "p": path, "mid": str(scope.merchant_id),
        "f": dict(sorted(fields.items())),
        "img": file_sha256,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()
```

For ProofPay's multipart claim endpoint, the file's **content hash** is the fingerprint input, not the filename and not the raw bytes — which dovetails with content-hash addressing in §7. Deliberately *exclude* headers, timestamps, and anything the client varies per attempt; including them would make every retry look like a different request and defeat the mechanism.

### 4.3 The flow, including the race

The critical detail almost everyone gets wrong: **the claim row must be committed in its own transaction, before the business work starts.** If you insert the `IN_PROGRESS` row inside the same transaction as the claim processing, it's invisible to a concurrent request until commit — so both requests do the full work and both try to allocate. Use a separate short-lived session for the bookkeeping.

```python
def begin_idempotent(scope, key, fp) -> Begun | Replay | InFlight | Mismatch:
    with SessionFactory.begin() as s:                       # own transaction
        try:
            rec = IdempotencyRecord(merchant_id=scope.merchant_id, key=key,
                                    fingerprint=fp, state=IdemState.IN_PROGRESS,
                                    expires_at=utcnow() + timedelta(hours=24))
            s.add(rec)
            s.flush()                                        # unique violation surfaces here
            return Begun(rec.id)
        except IntegrityError:
            s.rollback()

    with SessionFactory() as s:                              # loser of the race reads
        rec = s.scalars(select(IdempotencyRecord).where(
            IdempotencyRecord.merchant_id == scope.merchant_id,
            IdempotencyRecord.key == key)).one()
        if rec.fingerprint != fp:
            return Mismatch()                                # -> 422
        if rec.state is IdemState.IN_PROGRESS:
            return InFlight()                                # -> 409 + Retry-After: 1
        return Replay(rec.response_status, rec.response_body)
```

On success, in a third short transaction, set `state=COMPLETED` and store the serialised response body and status. On failure, either delete the row (so a retry can genuinely retry) or store the 4xx — but **never store a 5xx**; the client must be able to retry through a transient server fault.

Wire it as a dependency so routes stay clean:

```python
@router.post("/claims", status_code=201)
def submit(scope: Scope, session: SessionDep, idem: IdempotencyDep,
           file: UploadFile, order_id: uuid.UUID = Form(...)) -> ClaimResult:
    ...
```

Return `Idempotency-Key` and, on a replay, an `Idempotent-Replayed: true` header — a two-line change that makes the behaviour demonstrable to a judge.

**Anti-patterns:** an in-memory dict of seen keys (dies with the worker, wrong across processes); using the key alone without a fingerprint (a retry with a *different screenshot* would return the first screenshot's verdict — a live fraud vector for this exact product); caching 5xx responses; unbounded retention (add `expires_at` and a trivial cleanup, even if it never runs during the hackathon).

---

## 5. Enforcing allocation uniqueness in the database

The commitment: *transaction allocation uniqueness is enforced by a DATABASE CONSTRAINT, not application logic.* A plain `UNIQUE(transaction_id)` is wrong, because an allocation must be releasable — a merchant reverses a wrong match, and a released allocation must not block a new one. That's what a **partial unique index** is for.

### 5.1 Model

```python
class Allocation(Base):
    __tablename__ = "allocation"
    id: Mapped[uuid_pk]
    merchant_id: Mapped[merchant_fk]
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction.id", ondelete="RESTRICT"), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order.id", ondelete="RESTRICT"), nullable=False)
    state: Mapped[AllocState]           # ACTIVE | RELEASED
    claim_id: Mapped[uuid.UUID | None]
    allocated_at: Mapped[created]
    released_at: Mapped[dt.datetime | None]
    released_reason: Mapped[str | None]

    __table_args__ = (
        Index("uq_allocation_active_txn", "transaction_id", unique=True,
              sqlite_where=text("state = 'ACTIVE'"),
              postgresql_where=text("state = 'ACTIVE'")),
        Index("ix_allocation_order", "merchant_id", "order_id"),
    )
```

Both dialect kwargs are required — SQLAlchemy's `Index` has no generic `where=`; each dialect reads its own. SQLite has supported partial indexes, including partial UNIQUE indexes, since **3.8.0 (2013)**, so both engines behave identically here. SQLite's restriction (no subqueries, no other tables, no non-deterministic functions, no bound parameters in the `WHERE`) is satisfied by a literal comparison — keep the predicate that simple. Note the quoting difference if you ever use a boolean predicate: SQLite wants `0/1`, Postgres wants `false/true`; comparing an enum string sidesteps it.

Note the index is on `transaction_id` alone, not `(merchant_id, transaction_id)` — a transaction already belongs to exactly one merchant, and the narrower index is the stronger statement.

### 5.2 Alembic

**Autogenerate does not reliably detect partial indexes** (long-standing Alembic issue #750 — `postgresql_where` is not compared). Write this one by hand and record it in a short `docs/hand-written-ddl.md` so nobody "fixes" it by regenerating:

```python
def upgrade() -> None:
    op.create_index("uq_allocation_active_txn", "allocation", ["transaction_id"],
                    unique=True,
                    sqlite_where=sa.text("state = 'ACTIVE'"),
                    postgresql_where=sa.text("state = 'ACTIVE'"))

def downgrade() -> None:
    op.drop_index("uq_allocation_active_txn", table_name="allocation")
```

### 5.3 Application side: catch, don't check

```python
def allocate(session, scope, txn_id, order_id, claim_id) -> Allocation:
    alloc = Allocation(merchant_id=scope.merchant_id, transaction_id=txn_id,
                       order_id=order_id, claim_id=claim_id, state=AllocState.ACTIVE)
    session.add(alloc)
    try:
        session.flush()
    except IntegrityError as exc:
        if "uq_allocation_active_txn" not in str(exc.orig):
            raise
        raise TransactionAlreadyAllocated(txn_id) from exc
    return alloc
```

Match on the **constraint name** (this is why §2.1's naming convention matters — an anonymous index name differs between engines). `TransactionAlreadyAllocated` is a domain error that the decision layer turns into `DUPLICATE`, not a 500.

**Anti-pattern:** `if session.scalar(select(...).where(transaction_id == x)): raise`. That check-then-act is a TOCTOU race, and writing it *at all* signals to the reader that the DB constraint is optional. Keep the read only as a fast path for a friendlier message if you must, but the constraint is the enforcement.

### 5.4 Testing it under genuine concurrency

A single-threaded test proves nothing about a race. What you need is N threads hitting the same `transaction_id` from **separate connections**, released simultaneously.

```python
def test_only_one_allocation_wins(pg_engine, seeded):
    barrier = threading.Barrier(8)
    results: list[str] = []

    def worker(order_id):
        with Session(pg_engine) as s:
            barrier.wait()                      # release all threads together
            try:
                allocate(s, scope, seeded.txn_id, order_id, None); s.commit()
                results.append("ok")
            except TransactionAlreadyAllocated:
                s.rollback(); results.append("dupe")

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(worker, seeded.order_ids))

    assert results.count("ok") == 1
    assert results.count("dupe") == 7
```

`threading.Barrier` is what makes this a real race rather than eight sequential inserts; without it the test passes for the wrong reason.

**Run this one against Postgres.** SQLite has a single writer and will mostly return `OperationalError: database is locked` instead of `IntegrityError`, so the test would assert the wrong failure mode. Two options, in cost order: (a) `testcontainers[postgresql]` with a session-scoped container, marked `@pytest.mark.pg` and skipped when Docker is absent; (b) if Docker is a problem on someone's Windows machine, run it against a free-tier hosted Postgres from CI only. Do not skip this test — "enforced by a database constraint" is a claim you should be able to *demonstrate*, and eight threads with one winner is a great 20-second slide.

Also assert the release path: release the winner, then a ninth allocation must succeed. That's the case a plain `UNIQUE` would fail.

---

## 6. Alembic in a fast-moving project

**Set up on day one, before any model exists.** Retrofitting migrations onto a schema created by `create_all()` is a bad Thursday.

- `env.py`: `target_metadata = Base.metadata`, plus `render_as_batch=True` in `context.configure(...)` for SQLite (SQLite can't `ALTER` most things; batch mode rebuilds the table — and it *needs* the named constraints from §2.1).
- Turn on `compare_type=True`. Leave `compare_server_default=False`; it produces noisy false diffs.
- **Autogenerate is a first draft, always.** Verified against current docs, it detects: table add/remove, column add/remove, nullable changes, basic index and *named* unique-constraint changes, basic FK changes, named CHECK add/remove. It does **not** detect: table renames, column renames (emits drop + add — data loss if you apply it blindly), anonymously-named constraints, and it does not compare partial-index `WHERE` clauses (§5.2). **Read every generated file before committing it.** For a rename, hand-write `op.alter_column(..., new_column_name=...)`.
- **One migration per PR, with a real message:** `uv run alembic revision --autogenerate -m "add allocation partial unique index"`. Not `-m "update"`.
- **Multiple heads is the #1 collaboration failure** in a 4-person hackathon: two people branch from the same revision, both generate a migration, `alembic upgrade head` then fails with "Multiple head revisions". The fix is `alembic merge heads`, but the prevention is better: **one person owns migrations for the weekend** and the other three ask before generating. Tell your git-new teammate this explicitly — it will otherwise be their first painful merge.
- Add a CI check: `alembic upgrade head` on a blank DB, then `alembic check` (fails if the models have drifted from the migrations). Ten lines, catches the "forgot to generate a migration" bug that shows up as a demo-time crash.
- **Squashing before submission: don't.** The migration history *is* evidence of process, and judges of an engineering-focused hackathon read it. Squash only if you have a genuinely broken chain (a migration that no longer applies to a fresh DB) — in that case, delete `versions/`, generate one `0001_initial.py`, verify `upgrade head` on an empty database, and say so in the commit message. Do this on Friday, never on submission night.
- What you *should* do before submission: verify a **cold start** — clone into a clean directory, `uv sync`, `alembic upgrade head`, seed, run. That path is what a judge will execute.

---

## 7. File upload security

The screenshot is untrusted input from the internet, arriving as an image, being fed to a vision model. Treat it as hostile.

The pipeline, in order — **each step must pass before the next runs:**

**1. Cap the request before you read it.** Starlette 1.6.0 (2026-08-08) added `max_body_size` on the app, router, mount and route, plus `RequestBodyLimitMiddleware`, which rejects on `Content-Length` when present *and* counts actual bytes (so an understated header can't bypass it). If FastAPI's pin resolves to Starlette ≥1.6, use it:

```python
app = FastAPI(middleware=[Middleware(RequestBodyLimitMiddleware,
                                     max_body_size=8 * 1024 * 1024)])
```

If your pin lands on an older Starlette, the cheap fallback is a chunked read that aborts past the limit:

```python
MAX = 8 * 1024 * 1024
async def read_capped(f: UploadFile) -> bytes:
    buf, total = bytearray(), 0
    while chunk := await f.read(64 * 1024):
        total += len(chunk)
        if total > MAX:
            raise PayloadTooLarge(MAX)      # -> 413
        buf += chunk
    return bytes(buf)
```

Also pass `max_files`/`max_fields` to `request.form()` — unbounded empty fields are a cheap DoS. Never do `contents = await file.read()` unguarded; `UploadFile` spools to a `SpooledTemporaryFile`, but an unbounded `.read()` puts the whole thing in RAM.

**2. Ignore the client's `content-type` and filename entirely.** Both are attacker-controlled. `Content-Type: image/png` proves nothing, and a filename like `../../etc/passwd` or `x.png.php` is a path-traversal / double-extension attack. **Never** use `file.filename` to build a path. Keep it only as a display-only string field, truncated, in the DB.

**3. Magic-byte check.** A short prefix table is zero-dependency and enough for the three formats you accept:

```python
SIGS = {b"\xff\xd8\xff": "jpeg", b"\x89PNG\r\n\x1a\n": "png", b"RIFF": "webp"}
```

If you want a library, use **`puremagic`** — pure Python, no dependencies, works on Windows. Avoid `python-magic`: it needs a `libmagic` DLL that your Windows teammates will spend an hour on.

**4. Decompression-bomb guard, then re-encode.** This is the step that actually neutralises the payload:

```python
from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = 40_000_000          # NEVER set this to None
warnings.simplefilter("error", Image.DecompressionBombWarning)  # warning -> exception

def normalise(raw: bytes) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(raw)) as probe:
        probe.verify()                        # structural check; consumes the file
    with Image.open(io.BytesIO(raw)) as im:
        if im.format not in {"JPEG", "PNG", "WEBP"}:
            raise UnsupportedImage(im.format)
        im = ImageOps.exif_transpose(im)      # honour rotation BEFORE dropping EXIF
        im = im.convert("RGB")
        im.thumbnail((2000, 2000))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=88,
                exif=b"", icc_profile=None, optimize=True)   # strip everything
        return out.getvalue(), im.width, im.height
```

Re-encoding through a decode→pixel-buffer→encode round trip is what discards polyglot payloads, appended archives, malicious ICC profiles, and EXIF (which for a payment screenshot may carry GPS — a privacy issue as well as a security one). Do `exif_transpose` **first**, or a phone screenshot arrives sideways at the OCR model and your extraction quality drops for no visible reason. Set `ImageFile.LOAD_TRUNCATED_IMAGES = False` (the default) so truncated files fail loudly.

**5. Content-hash addressing.** Hash the **normalised** bytes:

```python
sha = hashlib.sha256(normalised).hexdigest()
path = storage_root / sha[:2] / sha[2:4] / f"{sha}.jpg"
```

Store `content_sha256` on the upload row with `UniqueConstraint("merchant_id", "content_sha256")`. Three wins at once: dedupe of storage; the same-screenshot-reused-twice signal that feeds duplicate detection; and the fingerprint input for §4's idempotency key. The two-level prefix directory keeps you off filesystems that hate 10,000-entry directories. Scope by merchant so one merchant can't probe another's hashes.

**6. Serve it back safely.** Never from a path built out of user input. Serve through an authenticated, merchant-scoped route that looks the row up by ID and streams from the hash path, with `Content-Type: image/jpeg`, `Content-Disposition: inline; filename="claim-<id>.jpg"`, `X-Content-Type-Options: nosniff`.

**Skip for the hackathon:** ClamAV / virus scanning (heavy, and the re-encode covers the realistic image threat), presigned S3 URLs (no budget), image forensics libraries. Note in the README that a production deployment would add AV scanning and object storage behind the same adapter interface — that shows judges you know where the line is.

---

## 8. Auth for a hackathon

Keep it boring, keep it small, make the *authorisation* interesting rather than the authentication.

**Hashing:** FastAPI's current docs use **`pwdlib`** (`uv add "pwdlib[argon2]"`), since `passlib` is effectively unmaintained. If the team has already specified bcrypt, `pwdlib[bcrypt]` gives you bcrypt through the same API — but Argon2id is the better default and it's one word to change. Either way: `PasswordHash.recommended()`, and never log or return a hash.

**Tokens:** `PyJWT`, HS256, secret from `Settings` (`SECRET_KEY`, generated with `secrets.token_urlsafe(32)`, never committed — commit a `.env.example` instead). Access token **30–60 minutes**, no refresh token. Refresh flows are a genuine time sink and buy you nothing in a demo; a 60-minute token that a user re-obtains by logging in is correct and complete.

**Claims — put the tenant in the token:**

```python
{"sub": str(user.id), "mid": str(user.merchant_id), "role": "OWNER",
 "scopes": ["claims:submit", "claims:read", "txn:read"],
 "iat": ..., "exp": ..., "jti": ...}
```

`mid` in the token is what makes §3's Rule 1 enforceable: there is no other place `merchant_id` can come from.

**Scoped authorisation.** Use FastAPI's built-in scopes so the OpenAPI docs show them:

```python
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token",
    scopes={"claims:submit": "Submit a payment claim",
            "claims:read": "Read claims and decisions",
            "txn:read": "Browse the merchant transaction feed",
            "txn:write": "Import transactions",
            "alloc:release": "Release an allocation"})

def require(sec: SecurityScopes, token: TokenDep, session: SessionDep) -> User:
    payload = decode(token)
    missing = set(sec.scopes) - set(payload.get("scopes", []))
    if missing:
        raise Forbidden(f"missing scopes: {sorted(missing)}")
    ...

@router.get("/transactions")
def list_txns(user: Annotated[User, Security(require, scopes=["txn:read"])], ...): ...
```

Roles → scope sets: `OWNER` gets everything; `CLERK` gets `claims:submit`, `claims:read` but **not** `txn:read` — so a clerk can submit a screenshot and see the verdict, but cannot browse the merchant's transaction ledger. That's the demonstrable scoped-authorisation story, and it takes about twenty minutes.

**Two tests worth writing:** a clerk token gets 403 on `GET /transactions`; a merchant-A token gets 404 on merchant-B's resources (the §3 parametrised test).

**Skip:** OAuth providers, refresh rotation, token revocation lists, 2FA, password reset by email, rate limiting beyond a trivial in-process counter on `/auth/token`. **Do not skip:** hashing passwords, an `exp` claim, HTTPS in the deployed demo, and keeping the secret out of git.

---

## 9. Error handling and degradation

### 9.1 One typed error base, mapped once

```python
# domain/errors.py — no FastAPI import
class ProofPayError(Exception):
    code: str = "internal_error"
    status: int = 500
    title: str = "Internal error"
    def __init__(self, detail: str = "", **ctx): ...

class NotFound(ProofPayError):              code, status = "not_found", 404
class Forbidden(ProofPayError):             code, status = "forbidden", 403
class ValidationFailed(ProofPayError):      code, status = "validation_failed", 422
class PayloadTooLarge(ProofPayError):       code, status = "payload_too_large", 413
class UnsupportedImage(ProofPayError):      code, status = "unsupported_media", 415
class IdempotencyMismatch(ProofPayError):   code, status = "idempotency_mismatch", 422
class IdempotencyInFlight(ProofPayError):   code, status = "idempotency_in_flight", 409
class TransactionAlreadyAllocated(ProofPayError): code, status = "already_allocated", 409
class UpstreamUnavailable(ProofPayError):   code, status = "upstream_unavailable", 503
```

Domain and service layers raise these; **only** `api/errors.py` knows about HTTP:

```python
@app.exception_handler(ProofPayError)
async def handle(request: Request, exc: ProofPayError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, media_type="application/problem+json",
        content={"type": f"https://proofpay.dev/errors/{exc.code}",
                 "title": exc.title, "status": exc.status, "detail": str(exc),
                 "code": exc.code, "request_id": request.state.request_id})
```

That's the **RFC 9457 Problem Details** shape (`type`/`title`/`status`/`detail`/`instance`, extensible with your own members). Writing it yourself is ~15 lines; libraries like `fastapi-problem-details` exist but aren't worth the dependency here. Also override the `RequestValidationError` handler so Pydantic 422s come back in the same envelope — a single error shape across every endpoint is the sort of polish judges notice, and it makes the frontend member's life much easier.

Attach a `request_id` (uuid4) in middleware, echo it in the `X-Request-ID` response header, and bind it to every log line.

### 9.2 Never report success before the decision is persisted

Concretely, for `POST /claims`:

1. The upload write to disk, the `PaymentClaim` row, the `Allocation` row (if any), and the `VerificationDecision` row commit in **one** transaction (§2.3).
2. Only after `session.commit()` returns does the handler construct the 201 response.
3. **No `BackgroundTasks` for the decision write.** Background tasks run *after* the response is sent — a failure there is invisible to the client, which has already been told the payment is verified. Background tasks are fine for a webhook notification or a thumbnail; never for the decision itself.
4. The response body must be built from the **persisted** decision (`decision_id`, `rules_version`), not from an in-memory object that might not have been written.
5. If the commit fails, return 5xx with the error envelope. The idempotency record must **not** be marked `COMPLETED` (§4.3), so the client's retry re-runs cleanly.

### 9.3 Degradation

Every adapter has a local fallback (the standing architectural commitment). Make the degradation **visible in the payload, never silent**:

```python
{"state": "NEEDS_REVIEW",
 "decision_id": "...", "rules_version": "rules/2026-08-22.1",
 "extraction": {"source": "local_ocr_fallback", "degraded": true,
                "reason": "dashscope_unavailable"},
 "evidence": [...]}
```

Two rules for degradation in this domain:

- **Degrade toward `NEEDS_REVIEW`, never toward `VERIFIED`.** If the extractor was the fallback and confidence is low, the deterministic rules must not be able to reach `VERIFIED`. Encode that as an explicit rule in `rules_v1`, not as an ad-hoc `if` in the service.
- A missing API key returns **200 with `degraded: true`**, not 503. The demo keeps working. A *timeout mid-request*, however, should surface as `UpstreamUnavailable` → 503 only if no fallback exists; otherwise fall back and mark it. Set an explicit `httpx` timeout (say 20s) on the vision adapter — the default is generous enough to hang your demo.

---

## 10. Testing the API with pytest

### 10.1 Client: `TestClient` for almost everything

`TestClient` (Starlette's, built on `httpx`) is synchronous, handles async endpoints correctly, and needs no `anyio` plumbing. **Use it.** Reach for `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` only for the handful of tests that must `await` something concurrently (e.g. firing two idempotent requests at once from one event loop). Both bypass the network entirely; the difference is ergonomics, not fidelity. Don't run a uvicorn server in tests.

```python
@pytest.fixture
def client(session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

Overriding `get_session` with the *test's* session is what lets a test assert on rows the request wrote, in the same transaction.

### 10.2 Transactional isolation with rollback

The current SQLAlchemy 2.0 recipe — much simpler than the 1.x version, no event handlers needed:

```python
@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_URL)
    Base.metadata.create_all(eng)      # or: alembic upgrade head
    yield eng
    eng.dispose()

@pytest.fixture
def session(engine) -> Iterator[Session]:
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint",
                expire_on_commit=False)
    yield s
    s.close()
    trans.rollback()                    # everything the test did disappears
    conn.close()
```

`join_transaction_mode="create_savepoint"` is the key: the application code under test can call `commit()` normally (it must — §2.3 commits inside the service), and those commits become SAVEPOINT releases inside the outer transaction that the fixture rolls back. Tests stay independent and the schema is built once per session.

**Build the schema with `alembic upgrade head`, not `create_all()`, at least in CI.** They diverge, and the divergence shows up as a demo-time crash on a fresh database. If `upgrade head` is slow, run `create_all()` for the fast local loop and `upgrade head` in CI — but run it *somewhere*, every push.

### 10.3 Fixtures and factories

Skip `factory_boy`. Plain keyword-defaulted helper functions are less code, are obvious to a hackathon newcomer, and don't need a session registry:

```python
# tests/factories.py
def make_merchant(s, *, name="Acme Traders") -> Merchant: ...
def make_user(s, merchant, *, role=Role.OWNER, password="pw") -> User: ...
def make_txn(s, merchant, *, amount_minor=250_000, occurred_at=None,
             sender="MUHAMMAD ALI", rail=Rail.EASYPAISA) -> Transaction: ...
def make_claim_image(*, amount="2,500", sender="Muhammad Ali", ts=...) -> bytes:
    """Render a fake Easypaisa receipt with Pillow. Deterministic."""
```

That last one earns its keep several times over: it gives you real multipart payloads for upload tests, tamper cases (re-save with an edited amount), and duplicate cases (the identical bytes twice) — without shipping a folder of binary fixtures.

Fixture layering: `merchant_a` / `merchant_b` (always two, so isolation tests are free), `auth_a` / `auth_clerk_a` returning header dicts, `client`.

**Freeze time.** `time-machine` (faster than `freezegun`), or better, pass `now` into `decide()` and never freeze at all. Timestamp-tolerance scoring tests that depend on wall-clock are flaky by construction.

### 10.4 In-memory SQLite: the fast path and its lies

```python
engine = create_engine("sqlite+pysqlite:///:memory:",
                       connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
@event.listens_for(engine, "connect")
def _fk_on(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
```

`StaticPool` is mandatory — without it every new connection gets its own empty database and your tables vanish between statements. `PRAGMA foreign_keys=ON` is mandatory too: **SQLite does not enforce foreign keys by default**, so without it your FK tests pass vacuously.

What in-memory SQLite still won't tell you:

| Lie | Consequence |
|---|---|
| Single writer, no real concurrency | The §5.4 allocation race cannot be tested here |
| No `JSONB`, no native `ENUM`, no `ARRAY` | Postgres-only column behaviour untested |
| Weak type affinity; `DateTime(timezone=True)` loses tz | Naive-vs-aware datetime bugs appear only on Postgres |
| Different `NULL` ordering, different collation/case-folding | Fuzzy-name comparison ordering may differ |
| `ALTER` emulation via batch mode | A migration can pass on SQLite and fail on Postgres |
| Different error text on constraint violations | String-matching on `exc.orig` is engine-specific |

**Recommended split:**

- **Default suite → in-memory SQLite.** Sub-second, runs on every save, covers routing, auth, scoping, validation, idempotency logic, and the pure decision rules. This is where 90% of your tests live.
- **`@pytest.mark.pg` suite → real Postgres** via `testcontainers[postgresql]`, session-scoped container, skipped if Docker is unavailable, run in CI. Put exactly the things SQLite can't prove there: the partial-index concurrency test, JSONB round-tripping, tz-aware datetimes, and `alembic upgrade head` from empty. A dozen tests, not a hundred.

Add to `pyproject.toml`: `addopts = "-q --strict-markers"`, `markers = ["pg: requires postgres"]`, and `filterwarnings = ["error::DeprecationWarning"]` so a SQLAlchemy 2.1 deprecation surfaces as a test failure rather than as a surprise on submission night.

---

## Anti-pattern quick reference

| Anti-pattern | Why it's fatal here |
|---|---|
| `merchant_id` in a request body/query/path | Trivial cross-tenant read; the whole isolation story collapses |
| `session.get(Transaction, id)` on a merchant-owned model | Identity-map hit emits no SQL, so no filter runs |
| `float` for money | Comparison drift silently changes verdicts |
| Checking allocation uniqueness with a `SELECT` before the `INSERT` | TOCTOU race; the DB constraint is the enforcement |
| `UNIQUE(transaction_id)` instead of a partial index on `state='ACTIVE'` | Releasing a bad match becomes impossible |
| Idempotency key without a request fingerprint | A retry with a *different screenshot* replays the first verdict |
| Writing the idempotency claim in the same transaction as the work | Concurrent duplicates both do the work |
| Auto-commit in the session dependency | Can't guarantee "persisted before success is reported" |
| Decision written in a `BackgroundTask` | Client told VERIFIED before anything is stored |
| Trusting `file.filename` or `content-type` | Path traversal, double extension, polyglot upload |
| `Image.MAX_IMAGE_PIXELS = None` | Decompression bomb OOMs the demo box |
| Serving the uploaded bytes back without re-encoding | Ships the payload straight to the browser |
| Domain logic in routers, Pydantic validators, or ORM events | Breaks reproducibility of the versioned decision engine |
| Applying an autogenerated rename migration unread | Drop + add = data loss |
| Everyone generating migrations | Multiple heads, and a rough first merge for the git newcomer |
| `sqlalchemy>=2.1` | It's still beta as of 2026-08-22 |

---

## Sources

- [SQLAlchemy 2.0 — Declarative Mapping Styles](https://docs.sqlalchemy.org/en/20/orm/declarative_styles.html) and [Table Configuration with Declarative](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html)
- [SQLAlchemy — Session Transaction / Joining a Session into an External Transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
- [SQLAlchemy — Session Events (`do_orm_execute`, `with_loader_criteria`)](https://docs.sqlalchemy.org/en/20/orm/session_events.html) and [ORM API Features for Querying](https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html)
- [SQLAlchemy — Relationship Loading Techniques](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)
- [SQLAlchemy 2.1.0b2 release announcement](https://www.sqlalchemy.org/blog/2026/04/16/sqlalchemy-2.1.0b2-released/) and [SQLAlchemy Download page](https://www.sqlalchemy.org/download.html)
- [Alembic — Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [Alembic issue #750 — autogenerate cannot detect partial indexes](https://github.com/sqlalchemy/alembic/issues/750)
- [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) and its [`app/api/deps.py`](https://raw.githubusercontent.com/fastapi/full-stack-fastapi-template/master/backend/app/api/deps.py)
- [FastAPI — OAuth2 with Password (and hashing), Bearer with JWT tokens](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) (now `pwdlib` + `PyJWT`)
- [FastAPI — Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)
- [Starlette release notes](https://github.com/Kludex/starlette/blob/main/docs/release-notes.md) — `max_body_size` / `RequestBodyLimitMiddleware` in 1.6.0
- [Starlette — Requests](https://starlette.dev/requests/) (`request.form(max_files, max_fields, max_part_size)`)
- [draft-ietf-httpapi-idempotency-key-header-07](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header-07)
- [RFC 9457 — Problem Details for HTTP APIs](https://datatracker.ietf.org/doc/html/rfc9457)
- [SQLite — Partial Indexes](https://www.sqlite.org/partialindex.html)
- [PostgreSQL — Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) and [Postgres RLS footguns](https://www.bytebase.com/blog/postgres-row-level-security-footguns/)
- [Pillow — Security](https://pillow.readthedocs.io/en/stable/handbook/security.html)
- [puremagic](https://github.com/cdgriffith/puremagic)
- [Testcontainers for Python](https://testcontainers.com/guides/getting-started-with-testcontainers-for-python/)
- [FastAPI discussion #8017 — SQLAlchemy dependency vs middleware vs scoped_session](https://github.com/fastapi/fastapi/discussions/8017)

---

## Definition of done

**Schema and migrations**
- [ ] `Base` defines a naming convention and `type_annotation_map`; every constraint and index in the schema has an explicit name.
- [ ] Every merchant-owned table has `merchant_id UUID NOT NULL` with an index and an FK to `merchant`.
- [ ] All money columns are `BigInteger` minor units; no `Float` anywhere in the schema.
- [ ] `Allocation` carries the partial unique index `uq_allocation_active_txn` on `transaction_id WHERE state='ACTIVE'`, with both `sqlite_where` and `postgresql_where`.
- [ ] `Transaction` has `UNIQUE(merchant_id, rail, external_txn_id)`; `Upload` has `UNIQUE(merchant_id, content_sha256)`; `IdempotencyRecord` has `UNIQUE(merchant_id, key)`.
- [ ] `alembic upgrade head` succeeds on an empty SQLite **and** an empty Postgres; `alembic check` reports no drift; there is exactly one head.
- [ ] Every migration file has been read by a human; the partial index is hand-written and listed in `docs/hand-written-ddl.md`.

**API and layering**
- [ ] `domain/` imports neither `fastapi` nor `sqlalchemy` (enforced by a test that asserts it).
- [ ] No `select(` or `session.` appears outside `repositories/`.
- [ ] `decide()` is a pure function taking `now` as a parameter and returning a `rules_version`.
- [ ] Every route body is ≤ 15 lines and has a `response_model`.
- [ ] `/health` returns 200 without touching the database; `/health/ready` checks the DB.
- [ ] OpenAPI at `/docs` renders every endpoint with scopes and error responses.

**Tenant isolation**
- [ ] `merchant_id` appears in zero request schemas; it is derived only from the token via `MerchantScope`.
- [ ] A parametrised test asserts **404** for merchant A on every merchant-owned resource belonging to merchant B.
- [ ] `session.get()` is not used for any merchant-owned model.

**Idempotency**
- [ ] `POST /claims` accepts `Idempotency-Key`; the record is committed in its own transaction before work begins.
- [ ] Tests cover: replay returns the original body + `Idempotent-Replayed: true`; same key + different fingerprint → **422**; concurrent identical requests → exactly one 201 and one **409**; a 5xx does not poison the key.

**Allocation uniqueness**
- [ ] A concurrency test with `threading.Barrier` and ≥8 threads on real Postgres asserts exactly one success and N−1 `TransactionAlreadyAllocated`.
- [ ] Releasing an allocation permits a subsequent allocation of the same transaction.
- [ ] The `IntegrityError` handler matches on the constraint **name**, not on message substrings.

**Uploads**
- [ ] Request body is capped (413 above 8 MB) and the cap is tested.
- [ ] Magic-byte check, `Image.verify()`, `MAX_IMAGE_PIXELS` set (never `None`), `DecompressionBombWarning` promoted to an error.
- [ ] Every stored image is a re-encoded JPEG with `exif=b""` and `icc_profile=None`; a test asserts EXIF is absent from the stored bytes and that `exif_transpose` was applied.
- [ ] `file.filename` never reaches a filesystem path; storage is `sha256[:2]/sha256[2:4]/sha256.jpg`.
- [ ] Uploading the same image twice returns the same `content_sha256` and creates one stored file.

**Auth**
- [ ] Passwords hashed with `pwdlib`; `SECRET_KEY` from env, absent from git, `.env.example` committed.
- [ ] JWT carries `sub`, `mid`, `role`, `scopes`, `iat`, `exp`; lifetime 30–60 min.
- [ ] A `CLERK` token receives **403** on `GET /transactions`; an expired token receives **401**.

**Errors and durability**
- [ ] One `ProofPayError` hierarchy; a single handler emits `application/problem+json` with `code` and `request_id`; Pydantic 422s use the same envelope.
- [ ] `X-Request-ID` is present on every response and appears in logs.
- [ ] No decision is ever written in a `BackgroundTask`; the 201 body is built from the committed decision row.
- [ ] With `DASHSCOPE_API_KEY` unset, `POST /claims` still returns 200/201 with `degraded: true` and cannot return `VERIFIED`; a test asserts this.

**Testing**
- [ ] `pytest` runs green in under ~20 seconds on the default in-memory SQLite path, with `StaticPool` and `PRAGMA foreign_keys=ON`.
- [ ] Test sessions use `join_transaction_mode="create_savepoint"`; tests pass in any order and under `-p no:randomly` reversal.
- [ ] `@pytest.mark.pg` suite runs against a real Postgres in CI and covers the allocation race, JSONB, tz-aware datetimes, and `alembic upgrade head`.
- [ ] `--strict-markers` and `filterwarnings = ["error::DeprecationWarning"]` are on.
- [ ] CI runs lint, type-check, migrations, and both suites on every push.

**Handover**
- [ ] A cold start works from a clean clone: `uv sync && alembic upgrade head && python -m proofpay.seed && uv run fastapi dev` — verified by someone other than the author.
- [ ] `uv.lock` is committed; one named person owns migrations for the rest of the build.