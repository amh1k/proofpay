# Using the Verification Engine

Phase 1 is merged. The engine lives at `backend/proofpay/core/` and is ready to call.

This page is for the other three tracks: **how to call it, and what comes back.**
It is not a design document — that is [`phases/phase1-engine.md`](phases/phase1-engine.md).

---

## What it is

A pure library. No database, no HTTP, no image handling, no network, and it never reads the clock —
`now` is passed in. Import it from anywhere; it has no setup and no side effects.

```python
from proofpay.core.decide import decide, DecisionPolicy
```

---

## The one function

```python
decision = decide(
    claim,          # PaymentClaim  — what the screenshot says (UNTRUSTED)
    order,          # Order | None  — what is being paid for
    ledger,         # Iterable[LedgerTxn] — the merchant's real transactions (TRUTH)
    allocations,    # Iterable[Allocation] — which transactions are already spoken for
    now=...,        # datetime, timezone-aware, REQUIRED and keyword-only
    policy=DecisionPolicy(),
    observations=(),  # optional image-forensics signals; advisory only
)
```

`now` is required on purpose. A decision that reads the wall clock cannot be reproduced, and a
test of it becomes a flake generator.

---

## What comes back

```python
@dataclass(frozen=True, slots=True)
class Decision:
    status: Status                      # VERIFIED | UNMATCHED | SUSPICIOUS | DUPLICATE | NEEDS_REVIEW
    risk: Risk                          # LOW | MEDIUM | HIGH
    confidence: float                   # 0..1 confidence in THIS DECISION — not a fraud probability
    reasons: tuple[ReasonCode, ...]
    matched_txn_id: str | None          # None when nothing matched, or when it was ambiguous
    fired_rule_id: str                  # "R030" — which rule decided, for the audit trail
    evidence: tuple[FieldOutcome, ...]  # one per field == one UI row
    observations: tuple[str, ...]
    ruleset_version: str                # these four make an old decision
    policy_fingerprint: str             # reconstructable months later:
    engine_version: str                 # same inputs + same stamps == same result
    evaluated_at: datetime              # the `now` that was handed in
```

### `evidence` is the result screen

Each `FieldOutcome` is one row, already worded for a human:

```python
@dataclass(frozen=True, slots=True)
class FieldOutcome:
    field: str            # "sender_name"
    level_code: str       # "NAME_INITIALS"  — stable machine id; safe to store and switch on
    label: str            # "Match with initials expanded"  — human text; safe to display
    score: float
    agreement: Agreement  # AGREE | WEAK | CONTRADICT | MISSING
    detail: Mapping[str, Any]

    @property
    def contradicts(self) -> bool: ...
```

Use `agreement` to decide the tick, cross or warning icon — **never the score**. A field can agree
weakly (a very common name) without contradicting anything, and rendering that as a cross tells the
merchant the opposite of the truth.

`level_code` is a stable identifier: store it, compare it, key logic off it.
`label` is display text and may be reworded at any time.

---

## Rendering it

There is a ready-made merchant-facing explanation model, so the wording does not have to be
reinvented per client:

```python
from proofpay.core.explain import explain, render_text

view = explain(decision, claim=claim, order=order)   # structured, for the React client
print(render_text(view))                             # plain text, for CLI and tests
```

```text
⚠ PAYMENT DETAILS DO NOT MATCH

A transaction was found, but the details conflict.

✓ Transaction ID: Transaction ID matches exactly
✗ Amount: Amount differs by a factor of ten
✓ Timestamp: Same time as the transaction
✓ Sender name: Match with initials expanded

⚠ The claimed amount is the received amount with a digit added

Risk: HIGH

Recommended action:
Do not approve the order yet.
```

**Never render a fraud percentage.** The product's whole claim is that it shows evidence a merchant
can act on. `confidence` is confidence in the decision, not a probability that someone is lying, and
presenting it as one would be dishonest as well as unconvincing.

---

## A complete example

```python
from datetime import datetime, timezone
from proofpay.core.money import Money
from proofpay.core.timex import ClaimedInstant, PKT
from proofpay.core.models import PaymentClaim, LedgerTxn, Order
from proofpay.core.decide import decide, DecisionPolicy

claim = PaymentClaim(                       # from the screenshot — untrusted
    claim_id="C1",
    amount=Money.from_major("5000"),
    sender_name="Muhammad Ali",
    reference_id="TX9001",
    occurred_at=ClaimedInstant.from_local(
        datetime(2026, 8, 20, 15, 42, tzinfo=PKT), granularity_s=60
    ),
)
order = Order(order_id="ORD-118", expected=Money.from_major("5000"))
ledger = [                                  # from the bank — the truth
    LedgerTxn(
        txn_id="TX9001",
        amount=Money.from_major("500"),     # only Rs 500 actually arrived
        occurred_at=datetime(2026, 8, 20, 10, 42, tzinfo=timezone.utc),
        sender_name="M. Ali",
    ),
]

d = decide(claim, order, ledger, [], now=datetime.now(timezone.utc), policy=DecisionPolicy())

d.status          # Status.SUSPICIOUS
d.risk            # Risk.HIGH
d.fired_rule_id   # "R030"
d.reasons         # (CLAIM_INFLATED, AMOUNT_UNDERPAID)
```

`datetime.now()` is fine **here** — in the caller. It must never appear inside `core/`.

---

## Rules that will bite you

**Money is an integer count of paisa.** `Money.from_major("5000")` is Rs 5,000. Never build a
`Money` from a float; the constructor rejects it. Use `.as_major_str` for display.

**Timestamps must be timezone-aware.** A naive `datetime` raises. Pakistan is `Asia/Karachi`,
UTC+05:00, no DST — use `PKT` from `proofpay.core.timex`.

**A field the OCR could not read is `None`.** Never a guess. A null costs one `NEEDS_REVIEW`; a
hallucinated amount that happens to match the order costs a false `VERIFIED`, and that is the
product's entire credibility.

**`matched_txn_id` can be `None` on a NEEDS_REVIEW.** That is deliberate: when two transactions
match equally well, naming one of them would hand the caller the wrong payment to allocate. Do not
fall back to "just pick the first candidate".

**`core/` is pure and must stay that way.** `tests/test_layering.py` fails the build if anything
under `core/` imports SQLAlchemy, FastAPI, httpx, requests, Pillow or dashscope, or calls
`datetime.now()`. That test is not bureaucracy — it is what keeps the engine instantly testable.

---

## The five states

| Status | Meaning | What the merchant should do |
|---|---|---|
| `VERIFIED` | A trusted transaction matches on every key field | Ship the order |
| `SUSPICIOUS` | Matched, but the details conflict — usually claim inflation | Do not ship |
| `DUPLICATE` | That transaction is already allocated to another order | Do not ship |
| `UNMATCHED` | No transaction plausibly matches | **Not fraud** — the payment may still be processing |
| `NEEDS_REVIEW` | Ambiguous, contradicted, or partially-trusted evidence | Check it manually |

`UNMATCHED` must never be presented as an accusation. A payment in flight is the common case.

---

## Tuning thresholds

Every threshold lives in `DecisionPolicy` — `tau_accept`, `tau_margin`, the timestamp decay, the
inflation materiality. There are no float thresholds anywhere else in `core/`, and all 31 fields
are covered by `policy.fingerprint()`, so changing one visibly changes every decision it touches.

Current values were set from **cost asymmetry, not data**: a false `VERIFIED` costs a merchant the
whole order, a false `NEEDS_REVIEW` costs thirty seconds. Roughly 100:1, so acceptance is
deliberately conservative and `NEEDS_REVIEW` absorbs the uncertainty.

They should be retuned against the Phase 4 fixtures once those exist. `tests/core/scenarios.yaml`
is the hand-labelled table to tune against — add rows to it rather than editing thresholds by feel.

---

## Tests

```bash
cd backend
uv run pytest -q          # 1042 tests
```

If you change anything under `core/`, these must keep passing — they are the safety net, not
decoration:

- `tests/test_layering.py` — `core/` stays pure and clock-free
- `tests/core/test_properties.py` — an empty ledger can **never** produce `VERIFIED`
- `tests/core/test_scenarios.py` — the hand-labelled scenario table
- `tests/core/test_contradiction.py` — a contradicted field blocks verification

---

## Questions

Ask Huzaifa. Do not change `core/models.py` unilaterally — those types are what the other three
tracks are built against, so a change there is a team decision.
