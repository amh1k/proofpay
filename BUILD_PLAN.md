# ProofPay — Build Plan

Implementation plan for the hackathon MVP described in
[proofpay-overview.md](proofpay-overview.md), [system_design.md](system_design.md),
and [data-model.md](data-model.md).

The design documents describe *what* ProofPay is. This document describes the
order in which it gets built, and what "done" means at each step.

---

## Guiding Constraints

The build order is driven by three facts about a hackathon:

1. **The demo is the deliverable.** Every phase must leave the project in a
   state that can be shown to a judge. Nothing is built that the four demo
   cases do not need.
2. **The verification engine is the product.** OCR and UI are replaceable;
   the reconciliation logic is the thing that is actually novel. It is built
   first, in isolation, where it can be tested without infrastructure.
3. **Nothing may block on an external dependency.** Every probabilistic or
   networked component (OCR, vision model, object storage, database) sits
   behind an interface with a working local implementation. A missing API key
   degrades quality; it never breaks the demo.

---

## Target Stack

| Layer | Choice | Note |
|---|---|---|
| Backend | Python 3.12, FastAPI | Per system_design.md §19 |
| ORM / schema | SQLAlchemy 2.x + Alembic | Models follow data-model.md |
| Database | SQLite (dev) -> PostgreSQL / ApsaraDB RDS | Same SQLAlchemy models both ways |
| Object storage | Local filesystem adapter -> Alibaba OSS | Adapter interface, per §6.9 |
| Receipt AI | Qwen-VL (DashScope) + deterministic fallback | Alibaba-native vision model |
| Frontend | React + Vite + Tailwind | Per system_design.md §19 |
| Tests | pytest | Rule and matching tests are the safety net |
| Tooling | uv (packaging + Python version) | Universal cross-platform lockfile |

**Alibaba Cloud alignment.** The design documents are deliberately
vendor-neutral. For this hackathon the neutral slots are filled with Alibaba
services — OSS for proof images, ApsaraDB RDS for relational state, and
Qwen-VL for receipt understanding — without changing any interface. This is a
configuration choice, not an architectural one, which is exactly what §4 of
the system design intends.

---

## Phase 0 — Foundation

Repository scaffolding. No domain logic.

- `backend/` and `frontend/` project layout
- Dependency manifests, `.gitignore`, `.env.example`
- Settings module reading configuration from the environment (§19)
- pytest wired up and running against an empty suite

**Done when:** `pytest` runs green and the FastAPI app serves a health check.

---

## Phase 1 — Verification Engine

The core of the product, built as pure functions with no I/O. This is the
highest-value phase and the one most worth over-testing.

- Domain types: `PaymentClaim`, `MerchantTransaction`, `EvidenceItem`
- Money as integer minor units; timezone-aware timestamps (data-model.md §2.2, §2.3)
- **Normalization** — names, amounts, reference IDs, timestamps (§10.1)
- **Candidate retrieval** — narrow the transaction feed to plausible matches (§10.2)
- **Scoring** — fuzzy sender names (`Muhammad Ali` ~ `M. Ali`), timestamp
  tolerance, amount comparison, reference-ID equality (§10.3)
- **Match outcome** — `MATCH` / `NO_MATCH` / `AMBIGUOUS`, never a final state (§6.5)
- **Duplicate detection** — transaction already allocated to another order (§11.1)
- **Decision engine** — versioned rules producing one of five states, a risk
  level, reason codes, and a merchant-facing explanation (§12)
- Amount semantics: underpayment vs. claim inflation vs. overpayment are
  distinct outcomes, not one "mismatch" (§12.4)

**Done when:** all four demo cases — genuine, edited amount, reused
transaction, ambiguous — are covered by passing unit tests, with no database,
no HTTP, and no OCR involved.

---

## Phase 2 — Persistence and API

Wrap the engine in storage and a transport boundary.

- SQLAlchemy models for the MVP subset of data-model.md: merchants, users,
  orders, payment accounts, merchant transactions, payment proofs, payment
  claims, verification attempts, match candidates, evidence items, transaction
  allocations, audit events
- Tenant isolation: `merchant_id` on every merchant-owned row (§2.5, §10.1)
- Unique constraint on accepted transaction allocations — the database, not
  application code, prevents double-spend (ADR-008, §10.3)
- Object-storage adapter interface + local filesystem implementation (§6.9)
- Merchant login, scoped authorization (§15.1)
- Endpoints: create verification, read result, list history, ingest/list
  transactions, dashboard summary (§13)
- Idempotency keys bound to a request fingerprint (§14, ADR-010)

**Done when:** a verification can be created over HTTP against a seeded
transaction feed and the persisted decision matches what the engine returns
directly. Concurrency test proves one transaction cannot be allocated twice.

---

## Phase 3 — Receipt Understanding

Turn an untrusted image into a structured claim.

- `ReceiptExtractor` interface with two implementations:
  - **Qwen-VL extractor** — image in, structured payment fields out
  - **Deterministic extractor** — reads generated fixtures, used offline and in tests
- Provider adapters for Easypaisa and JazzCash layouts, generic fallback with
  lower confidence (§6.3)
- Field-level confidence propagated into the claim
- Tamper-evidence signals returned as *observations only*, never as a verdict (§6.7)

**Done when:** uploading a receipt image produces a `PaymentClaim` whose
fields feed Phase 1 unchanged, and the pipeline still works with no API key.

---

## Phase 4 — Demo Dataset

The overview asks for roughly 30 receipts across genuine, edited, and reused
variants. Generating them beats sourcing them.

- Receipt image generator rendering Easypaisa and JazzCash style layouts
- Matched merchant transaction feed, orders, and prior allocations
- Variants: genuine, edited amount, edited reference ID, edited timestamp,
  reused transaction, unmatched, ambiguous
- One-command seed and reset

**Done when:** `seed` produces a merchant whose feed and receipt set reproduce
all five verification states on demand.

---

## Phase 5 — Merchant Client

What the judges actually watch.

- Login
- Upload / camera capture
- **Explainable result view** — the per-field evidence breakdown from §12.5,
  not a fraud percentage
- Verification history with the five states
- Transaction feed viewer
- Dashboard counts

**Done when:** the full flow runs end to end in a browser.

---

## Phase 6 — Demo Polish

- Scripted four-case walkthrough with a reset control
- Alibaba Cloud configuration: OSS bucket, RDS instance, DashScope key
- README with setup, architecture summary, and demo steps
- Latency check on the synchronous path (§20 assumes bounded processing)

**Done when:** the demo can be run cold, twice in a row, without manual repair.

---

## Sequencing Notes

Phases 1 and 2 are strictly ordered: the engine defines the contracts that the
schema and API persist. Phase 3 depends on Phase 1's claim contract but not on
Phase 2. Phase 4 can start any time after Phase 1. Phase 5 needs Phase 2's
endpoints.

If time runs short, cut in this order: tamper evidence (Phase 3), the
similarity half of duplicate detection (Phase 1), dashboard analytics (Phase
5). Do not cut allocation uniqueness, amount semantics, or the explanation
model — those are the architecture fitness criteria in §22.
