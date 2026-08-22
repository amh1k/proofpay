# ProofPay

**AI-powered payment verification and reconciliation for small merchants.**

A customer sends a payment screenshot. ProofPay reads it, matches it against the merchant's real
transaction records, and says whether the money actually arrived — catching edited amounts, reused
screenshots, and payments that never happened.

> The screenshot is only a payment **claim**.
> The merchant's transaction record is the **source of truth**.

See the [project overview](docs/overview.md) for the full concept, features and demo scenarios.

---

## Start here

**New to the project?** Read in this order:

1. [`proofpay-overview.md`](docs/overview.md) — what we're building and why
2. [`BUILD_PLAN.md`](docs/build-plan.md) — the seven phases and what "done" means for each
3. [`SETUP.md`](docs/setup.md) — get it running on your machine

**About to start coding?** Read [`PRACTICES.md`](docs/practices.md) first — git workflow, testing
strategy, and the licence rules. Then read the guide for your phase in
[`docs/phases/`](docs/phases/) immediately before you start that phase.

---

## Get it running

```bash
git clone https://github.com/amh1k/proofpay.git
cd proofpay/backend
uv sync
uv run pytest
uv run uvicorn proofpay.main:app --reload
```

Then open <http://127.0.0.1:8000/health>.

You need [uv](https://docs.astral.sh/uv/) and nothing else — not even Python, which uv installs
itself. No `.env`, no database server, no cloud account, no API key. Full detail in
[`SETUP.md`](docs/setup.md).

---

## Documentation

### Design — what we're building

| Document | Contents |
|---|---|
| [`proofpay-overview.md`](docs/overview.md) | Product concept, features, verification flow, MVP scope, demo scenarios |
| [`system_design.md`](docs/system-design.md) | Architecture, components, trust model, decision rules, security, ADRs |
| [`data-model.md`](docs/data-model.md) | Entities, relationships, constraints, invariants, indexing, retention |

### Execution — how we're building it

| Document | Contents |
|---|---|
| [`BUILD_PLAN.md`](docs/build-plan.md) | The seven phases, in order, with a definition of done for each |
| [`SETUP.md`](docs/setup.md) | Local setup, dependency rules, platform notes |
| [`PRACTICES.md`](docs/practices.md) | Environments, git workflow, testing strategy, licensing, execution discipline |
| [`REFERENCES.md`](docs/references.md) | 68 verified reference repositories, with what specifically to take from each |
| [`COST_CHECK.md`](docs/cost-check.md) | Verification that every component is free or free-tier, and how to avoid a bill |
| [`docs/phases/`](docs/phases/) | A deep best-practices guide for each build phase |

---

## Architecture

```text
        Merchant uploads a payment screenshot
                        │
                        ▼
        Receipt understanding  (Qwen-VL, with an offline fallback)
                        │
                        ▼
              Structured PaymentClaim
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
  Transaction      Duplicate        Tamper
   matching        detection       evidence
        └───────────────┼───────────────┘
                        ▼
              Decision engine  (deterministic, versioned)
                        │
                        ▼
   VERIFIED · UNMATCHED · SUSPICIOUS · DUPLICATE · NEEDS REVIEW
                        │
                        ▼
          Explained with per-field evidence
```

The screenshot is untrusted and probabilistic. The transaction record is trusted and authoritative.
**No screenshot-derived signal can establish on its own that payment occurred** — that rule is the
architecture.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic |
| Database | SQLite in development, PostgreSQL in deployment |
| Object storage | Local filesystem adapter, Alibaba OSS in deployment |
| Receipt AI | Qwen-VL via Alibaba Model Studio, with a deterministic offline extractor |
| Frontend | React, Vite, Tailwind |
| Packaging | uv (cross-platform lockfile) |
| Tests | pytest |

Every cloud service sits behind an adapter with a working local implementation, so a missing API
key degrades quality but never breaks the demo.

---

## Team

| | |
|---|---|
| [@amh1k](https://github.com/amh1k) | Architecture and design documents |
| [@HuzaifaAbdulRehman](https://github.com/HuzaifaAbdulRehman) | |
| [@SaadShakeel1](https://github.com/SaadShakeel1) | |
| [@MuhammadBilal64](https://github.com/MuhammadBilal64) | |

---

## Working on this

- Branch off `main`, keep pull requests small, and never force-push a shared branch.
- Run `uv sync --frozen` after every pull. Add dependencies with `uv add`, never bare `pip install`.
- Check a licence **before** adding a dependency. MIT / BSD / Apache-2.0 are fine;
  **AGPL is a hard stop** — its copyleft triggers on network use, which a deployed demo is.
- All demo data comes from the seed script. Never hand-insert rows — that is how a demo ends up
  working on exactly one laptop.
- Receipt images are **synthetic**. Never commit a real payment screenshot; they contain real
  names, phone numbers and amounts.
