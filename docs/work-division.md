# ProofPay — Work Division

Four people, one repository, working at the same time.

This document exists to answer one question: **what can I work on right now without waiting for
anyone, and without colliding with anyone?**

---

## The principle

> **Divide by files, not by tasks.**

Two people assigned "the matching feature" and "the API" will still both edit the same file and
spend the evening resolving conflicts. Two people who own *different directories* never conflict at
all, no matter what they build inside them.

So each track below owns a set of directories outright. Inside your directory you need nobody's
permission. Outside it, you do not edit — you ask the owner.

The one thing that makes this work is that the **shared contracts are frozen first**. Everyone
imports the same types and codes against them. Nobody waits.

---

## The four tracks

| Track | What you build | You own | Language |
|---|---|---|---|
| **A — Engine** | The verification brain: matching, scoring, duplicates, decision rules | `backend/proofpay/core/`<br>`backend/tests/core/` | Python |
| **B — Platform** | Database, API, auth, uploads, storage | `backend/proofpay/db/`<br>`backend/proofpay/api/`<br>`backend/proofpay/storage/`<br>`backend/alembic/`<br>`backend/tests/api/` | Python |
| **C — Receipts** | Reading screenshots, and generating the demo dataset | `backend/proofpay/extraction/`<br>`backend/tests/extraction/`<br>`tools/`<br>`fixtures/` | Python |
| **D — Client** | Everything the judge actually looks at | `frontend/` (the whole directory) | React |

### Suggested assignment

| Track | Person | Why |
|---|---|---|
| **A — Engine** | [@HuzaifaAbdulRehman](https://github.com/HuzaifaAbdulRehman) | Set up the project and planned this phase already |
| **B — Platform** | [@amh1k](https://github.com/amh1k) | Wrote `data-model.md` and `system-design.md` — knows the schema better than anyone |
| **C — Receipts** | [@SaadShakeel1](https://github.com/SaadShakeel1) | — |
| **D — Client** | [@MuhammadBilal64](https://github.com/MuhammadBilal64) | — |

**Swap C and D freely** based on who is more comfortable with React versus Python. That is the only
choice here that depends on taste. A and B are placed on the two people already in the code, and
moving them costs ramp-up time we do not have.

---

## Day 0 — freeze the contracts

This is the only step that must happen before parallel work starts. It takes about an hour.

**Track A writes `backend/proofpay/core/models.py` and `core/reasons.py` first and pushes them
immediately** — before writing any logic. These are the frozen types everyone imports:

```python
PaymentClaim        # what the screenshot claims
LedgerTxn           # what the merchant actually received
Order               # what is being paid for
Decision            # status, risk, confidence, reason codes, explanation
FieldEvidence       # one row of the per-field breakdown
VerificationStatus  # VERIFIED | UNMATCHED | SUSPICIOUS | DUPLICATE | NEEDS_REVIEW
ReasonCode          # stable codes, never reworded
```

**Track B writes the API contract second** — route paths, request and response shapes — committed
as an OpenAPI stub with hardcoded example responses. It needs no database behind it.

Once those two things exist:

- **B** builds endpoints returning fake `Decision` objects.
- **C** builds extractors producing real `PaymentClaim` objects.
- **D** builds the entire UI against the OpenAPI stub, with no backend running at all.
- **A** builds the real engine underneath.

Nobody is blocked. That is the whole point.

> **Changing a frozen contract after Day 0 is a team decision, not an individual one.** Post it in
> the group chat, get a thumbs-up, then change it in one PR that updates every caller. This is the
> single most disruptive thing anyone can do, so it is worth thirty seconds of asking.

---

## Track A — Verification Engine

**You own:** `backend/proofpay/core/`, `backend/tests/core/`
**Read first:** [`phases/phase1-engine.md`](phases/phase1-engine.md)

Pure Python. No database, no HTTP, no image handling, no `datetime.now()`. Everything arrives as an
argument, including the clock.

Build in this order:

1. `models.py`, `reasons.py` — **push these first, everyone is waiting on them**
2. `money.py`, `timex.py` — integer minor units, timezone-aware instants
3. `normalize.py` — names, amounts out of OCR text, reference IDs, timestamps
4. `compare/` — the comparison-level pattern: ordered levels per field, first match wins
5. `retrieval.py` — narrow the transaction feed to plausible candidates
6. `duplicates.py` — detect a transaction already allocated elsewhere
7. `decide/` — the ordered rule table producing the five states
8. `explain.py` — the per-field evidence model the UI renders

**Blocked by:** nobody, ever.
**Blocking:** everyone, until `models.py` exists. Push it within the first hour.

**Done when:** all four demo cases pass as unit tests, with no database, no OCR, no UI.

---

## Track B — Platform

**You own:** `backend/proofpay/db/`, `api/`, `storage/`, `alembic/`, `backend/tests/api/`
**Read first:** [`phases/phase2-api.md`](phases/phase2-api.md)

Build in this order:

1. **The OpenAPI stub** — routes with hardcoded responses. **Push this first, D is waiting on it.**
2. SQLAlchemy models from [`data-model.md`](data-model.md), MVP subset only
3. The allocation uniqueness constraint — a database constraint, not an `if` statement
4. Alembic migrations
5. Storage adapter — local filesystem now, OSS later
6. Upload handling: size limits, magic-byte validation, image re-encode, content hashing
7. Idempotency keys bound to a request fingerprint
8. Auth — the simplest JWT flow that works
9. Wire the real engine in, replacing the stub responses

**Blocked by:** `core/models.py`, and only from step 2 onward. Step 1 needs nothing.
**Blocking:** D, until the OpenAPI stub exists. Push it within the first hour.

**Done when:** a verification can be created over HTTP against seeded data, and a concurrency test
proves one transaction cannot be allocated to two orders.

---

## Track C — Receipts and Dataset

**You own:** `backend/proofpay/extraction/`, `backend/tests/extraction/`, `tools/`, `fixtures/`
**Read first:** [`phases/phase3-receipt.md`](phases/phase3-receipt.md), then
[`phases/phase4-dataset.md`](phases/phase4-dataset.md)

You have two jobs, and **the dataset comes first** — A, B and D all benefit from real fixtures to
work against, and it needs no API key.

**Job 1 — the dataset:**

1. A receipt image generator: Easypaisa-style and JazzCash-style layouts at phone dimensions
2. Genuine receipts, plus a matching merchant transaction feed and orders
3. Tampered variants: edited amount, edited reference ID, edited timestamp, edited name
4. A fixture set that deterministically produces **all five** outcomes, including the hard ones —
   AMBIGUOUS (two plausible candidates) and UNMATCHED (still processing, which must not read as fraud)
5. A seed script with `--reset`, which is the **only** way anyone gets data

**Job 2 — extraction:**

6. The `ReceiptExtractor` interface, with a deterministic offline implementation
7. Image preprocessing — downscale to ~1024px long edge before any model call
8. The Qwen-VL adapter, behind that interface
9. Provider templates for Easypaisa and JazzCash, generic fallback at lower confidence
10. Cheap tamper-evidence observations — advisory only, never a verdict

**Two rules that are not negotiable:**

- **Receipts are synthetic. Always.** Never scrape real payment screenshots and never commit one.
  They contain real names, phone numbers and amounts. On a fintech project, "we generated synthetic
  data so we never handled real customer information" is a slide in the pitch, not an apology.
- **A field you cannot read returns `None` with a reason — never a guess.** A null costs one
  `NEEDS_REVIEW`. A hallucinated amount that happens to match the order costs a false `VERIFIED`,
  and that is the project's entire credibility gone in front of a judge.

**Blocked by:** `core/models.py`, for job 2 only. Job 1 needs nothing.
**Blocking:** nobody — but everyone benefits from fixtures early, so ship them early.

---

## Track D — Merchant Client

**You own:** `frontend/` — the entire directory
**Read first:** [`phases/phase5-frontend.md`](phases/phase5-frontend.md)

You will not have a merge conflict with anyone, all week. No Python file is yours; no `frontend/`
file is theirs.

Build in this order:

1. Vite + React + Tailwind, proxying `/api` to `127.0.0.1:8000` — **not** `localhost`. On Windows
   that can resolve to IPv6 while uvicorn binds IPv4, giving a connection error that looks like a
   code bug and wastes an hour.
2. A mock API layer, so the whole app runs with no backend
3. Upload: drag-and-drop, and **paste-from-clipboard** — merchants paste screenshots
4. **The result view.** The most important screen in the product. Spend your time here.
5. History list with the five states
6. Dashboard counts
7. Login, last

**The result view is the product.** A judge remembers one screen that clearly explains *why* a
payment was rejected. They do not remember six half-finished screens. Structure it as a visual
split — **what the customer claimed** against **what we actually received** — with per-field ticks
and crosses between them.

Never show a fraud percentage. Show the evidence.

**Blocked by:** the OpenAPI stub, and only for real data. Steps 1–6 work against mocks.

---

## Shared files — the only places you can collide

Four files belong to everyone, which means they belong to no one:

| File | Rule |
|---|---|
| `backend/pyproject.toml` | Add dependencies with `uv add`, and commit `uv.lock` in the same commit. Conflicts here are one line — keep both sides. |
| `backend/proofpay/config.py` | **Append** your settings at the end of your track's section. Never reorder or reformat existing lines. |
| `backend/proofpay/main.py` | **Track B owns this.** Need a router registered? Ask B. |
| `README.md`, `docs/` | Anyone may add. Do not restructure without saying so. |

If you do hit a conflict it will be small. The fix is always:

```bash
git pull --rebase        # never --force
# open the file, keep both sides, delete the <<<<<<< markers
git add <file>
git rebase --continue
```

**Never force-push a shared branch.** If something looks unrecoverable, stop and ask — your work is
almost certainly still in `git reflog`, and a panicked command is what turns a recoverable mess into
a lost afternoon.

---

## How we integrate

- **Branch off `main`**, named `track-a/...`, `track-b/...`, and so on.
- **Merge to `main` at least once a day**, even if unfinished, as long as it runs. A branch that
  lives three days is a merge conflict with a countdown timer.
- **Small pull requests.** A 200-line PR gets reviewed in ten minutes. A 2,000-line PR gets approved
  without being read, which is worse than no review at all.
- **`main` must always run.** If `uv run pytest` fails on `main`, that is everyone's emergency,
  because everyone pulls from it.
- **After every pull:** `cd backend && uv sync --frozen`.

**Integration checkpoint, once a day:** all four pull `main`, run the app end to end together, and
confirm it still works. The classic four-person failure is that every part works alone on the day
before the deadline and nothing works together.

---

## Dependency map

```text
        Track A: models.py + reasons.py       Track B: OpenAPI stub
                      │                                 │
      ┌───────────────┼───────────────┐                 │
      ▼               ▼               ▼                 ▼
 A: engine       B: database    C: extraction      D: frontend
 (independent)   (independent)  (independent)      (independent)
      │               │               │                 │
      └───────────────┴───────┬───────┴─────────────────┘
                              ▼
                   Integration: B wires the real
                   engine and extractor into the API
```

After the first hour, **all four tracks run in parallel with no further blocking**. The only rejoin
point is B connecting the pieces, and that happens continuously rather than at the end.

---

## If someone falls behind

Say so early. It is not a failure — it is information the other three need.

Pick-up order, cheapest first:

1. **D helps C** with the receipt generator. Self-contained, needs no backend knowledge.
2. **A helps B** with repositories and tests. A finishes earliest by design.
3. **Everyone helps D** with the result view in the final stretch. It is what gets judged.

If the whole team is behind, the cut list is already written and ranked in
[`phases/README.md`](phases/README.md). Cut from the top. Do not improvise at 3am.

**Never cut:** the five decision states, the database uniqueness constraint, the per-field evidence
view, the golden-file tests, the README, or the demo video.
