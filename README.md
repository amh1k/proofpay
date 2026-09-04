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

**About to start coding?** Read [`work-division.md`](docs/work-division.md) to find your track, then [`practices.md`](docs/practices.md) — git workflow, testing
strategy, and the licence rules. Then read the guide for your phase in
[`docs/phases/`](docs/phases/) immediately before you start that phase.

---

## Get it running

```bash
git clone https://github.com/amh1k/proofpay.git
cd proofpay
```

**The merchant client** — runs on its own, no backend needed:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. The quickest way in is the row of example buttons near the bottom,
which walk three demo cases on their own: an edited amount, a reused payment, and one that has not
arrived yet.

To check a screenshot yourself, pick an order first. The picker is at the top of the screen, and
"Check this payment" stays disabled until you use it, because the app will not check a payment
against an order nobody chose. There are receipts to try in `fixtures/demo/images/`. `G01.jpg`
against ORD-G01 verifies. `S01.jpg` against ORD-S01 is the edited amount.

Add `?present=1` to raise the type size for a projector.

**The backend** — engine and API:

```bash
cd backend
uv sync
uv run pytest
uv run uvicorn proofpay.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive API. Sign in at `POST /api/v1/auth/token`
with username `owner` and any password, then click **Authorize**.

You need [uv](https://docs.astral.sh/uv/) and Node 22 — nothing else, not even Python, which uv
installs itself. No `.env`, no database server, no cloud account, no API key. Full detail in
[`setup.md`](docs/setup.md).

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
| [`build-plan.md`](docs/build-plan.md) | The seven phases, in order, with a definition of done for each |
| [`work-division.md`](docs/work-division.md) | Who owns which directories, so four people can work at once without colliding |
| [`using-the-engine.md`](docs/using-the-engine.md) | How to call the verification engine and what it returns — for tracks B, C and D |
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
| Database | SQLite for the demo; PostgreSQL-compatible models and optional driver |
| Object storage | Local filesystem adapter; Alibaba OSS is a planned adapter, not implemented |
| Receipt AI | Qwen-VL adapter via Alibaba Model Studio; deterministic offline demo path |
| Frontend | React, Vite, Tailwind |
| Packaging | uv (cross-platform lockfile) |
| Tests | pytest |

Receipt extraction sits behind an adapter with a working local implementation, so a missing model
API key degrades extraction quality but never breaks the demo. The hackathon path stores uploads on
the local filesystem; an Alibaba OSS implementation is future work.

---

## Third-party frameworks and libraries

Everything ProofPay is built on. Each licence below was read from the installed package metadata
rather than from memory. Nothing here is AGPL, which [`practices.md`](docs/practices.md) explains is
a hard stop for a demo that gets deployed.

Backend: fastapi (MIT), uvicorn (BSD-3-Clause), pydantic and pydantic-settings (MIT),
python-multipart (Apache-2.0), SQLAlchemy (MIT), alembic (MIT), bcrypt (Apache-2.0), PyJWT (MIT),
pillow (MIT-CMU), rapidfuzz (MIT), jellyfish (MIT), tzdata (Apache-2.0), dashscope (Apache-2.0),
ImageHash (BSD-2-Clause).

Backend, development only: pytest (MIT), ruff (MIT), PyYAML (MIT), hypothesis (MPL-2.0), playwright
(Apache-2.0). MPL-2.0 is file-level copyleft. Hypothesis runs at test time and ships in nothing.

Frontend: react and react-dom (MIT), vite (MIT), tailwindcss and @tailwindcss/vite (MIT),
@vitejs/plugin-react (MIT), typescript (Apache-2.0), oxlint (MIT).

Services: Alibaba Cloud Model Studio can read receipt images through the Qwen-VL adapter when it is
configured. The submitted demo defaults to the deterministic offline implementation.

No code was reused from a previous project. The receipt images are synthetic, generated by
`tools/render_receipts.py` in this repository. We never handled a real payment screenshot, so no
real customer's name, phone number or amount exists anywhere in this codebase.

---

## AI usage disclosure

We used AI assistants to build ProofPay. The rules require us to say how, and a reader deserves to
know which parts of this a person actually reviewed.

Claude (Anthropic) was used throughout as a coding assistant, for drafting implementation, writing
tests, reviewing diffs and researching approaches. GitHub Copilot was used on parts of the platform
track. OpenAI Codex was used for adversarial code review, pre-submission auditing, and targeted UI
implementation and verification. Alibaba Qoder was used by a team member as a coding assistant.
CodeRabbit provided automated pull-request feedback.

Alibaba Cloud's Qwen-VL integration is a product feature rather than a development tool. The demo
defaults to the offline extractor, as documented under Stack above.

Recent submission changes reached `main` through pull requests with CI green. The engine's behaviour
is pinned by a committed harness that drives all 30 receipt fixtures from image bytes to verdict, so
a change that moves a decision has to move a recorded expectation in the same commit. Where the
fixtures and the engine disagree, the disagreement is recorded by name with both sides stated rather
than papered over. See `KNOWN_DISAGREEMENTS` in `backend/tests/test_manifest_end_to_end.py`.

The product decisions are ours. What counts as a match, how the rule table is ordered, what the
merchant is told when we are not sure: those are judgements we made and argued about. ProofPay is
not a wrapper around a general-purpose AI tool. The decision engine is deterministic, versioned and
offline, and the demo runs end to end with no model API key set at all.

---

## Team

| | |
|---|---|
| [@amh1k](https://github.com/amh1k) | Architecture and design documents · platform, API and persistence |
| [@HuzaifaAbdulRehman](https://github.com/HuzaifaAbdulRehman) | Verification engine · merchant client · CI |
| [@SaadShakeel1](https://github.com/SaadShakeel1) | Receipt dataset · receipt understanding |
| [@MuhammadBilal64](https://github.com/MuhammadBilal64) | Demo, pitch and documentation |

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

To recreate the complete persisted demo dataset from a clean checkout:

```bash
cd backend
uv run python scripts/seed.py --reset
```

The command recreates the configured schema, loads all 30 manifest scenarios, and prints the
deterministic merchant IDs to use when exercising the persisted API path.
