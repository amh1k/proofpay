# Hackathon Strategy — Best Practices

Scope: how ProofPay's four-person team should *run the event*, not how to build the reconciliation engine. Written against a 48–72h format with a judged demo; adjust the clock arithmetic if your Alibaba Cloud track differs, but keep the ratios.

Everything below is anchored to sources, listed at the end. Where evidence is thin or practice is contested, that is stated rather than smoothed over.

---

## 0. The five facts that should shape every decision

1. **Judges see your project for about 4 minutes, three times.** MLH's reference judging plan is science-fair style: judges rotate to tables, ~3 minutes per team (2 min presenting + 1 min Q&A), with a recommended 3 rounds at 4 min/project, and a **2-minute demo video** submitted beforehand used mainly during final deliberation. Scoring is often **stack-ranked** (each judge picks a top 3, awarding 3/2/1) rather than absolute, explicitly to normalise between harsh and generous judges. ([MLH judging plan](https://guide.mlh.com/general-information/judging-and-submissions/judging-plan))
   → **Consequence:** stack ranking rewards being *memorable within a judge's small assigned set*, not being globally excellent. A clean, working, well-narrated 2-minute story beats a broader system that stumbles. Your artifact-under-judgement is the demo, not the repo.

2. **Hackathon repos are mostly not written at the hackathon — and that is normal and legitimate when disclosed.** A large-scale study of hackathon repositories found only **9.14% of code blobs and ~8% of lines** in those repos were created during the hackathon itself; roughly a third of hackathon-created code is later reused elsewhere. ([Imam & Zimmermann et al., arXiv:2207.01015](https://arxiv.org/abs/2207.01015))
   → **Consequence:** the winning teams are not out-typing you. They are out-*scaffolding* you, and they declare the scaffolding. Pre-written design docs (which you have) are an asset, not a liability — see §8.

3. **Rules on prior work and AI are explicit and enforced.** MLH's model rules: *"You may not work on your project before the event… you should not be reusing code from previous projects"*, *"You may use publicly available frameworks, but you need to list said frameworks in a readme"*, and *"You may use LLM/ChatGPT/AI, but must state how you did so in your submission"* — projects must not be *"a reskin of an existing AI tool"*, and failure to credit AI usage is a disqualification offence. Organisers do check git history for work started before the event; open-source code is fine *"as long as we respect the license."* ([MLH rules](https://guide.mlh.com/general-information/judging-and-submissions/rules-for-your-hackathon), [MLH cheating check](https://guide.mlh.com/general-information/judging-and-submissions/cheating-check))
   → **Consequence for ProofPay:** your architecture documents are *planning*, not *code* — that distinction is what keeps you clean. Read §8 before you commit anything.

4. **Sleep loss degrades exactly the hours you need most.** After **17–19 hours without sleep**, performance on some tasks is *"equivalent or worse than that at a BAC of 0.05%"*, with response times up to **50% slower**; longer deprivation reaches the equivalent of 0.1% BAC. ([Williamson & Feyer 2000, *Occup Environ Med*](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=TITLE%3A%22Moderate%20sleep%20deprivation%20produces%20impairments%20in%20cognitive%20and%20motor%20performance%22)) Worse, self-assessment fails: under chronic restriction, *"subjective sleepiness ratings… did not significantly differentiate the 6 h and 4 h conditions"* while objective deficits kept accumulating. ([Van Dongen et al. 2003, *Sleep*](https://academic.oup.com/sleep/article/26/2/117/2709164))
   → **Consequence:** you will not feel how impaired you are during demo prep. This is a scheduling problem, not a willpower problem. §6.

5. **AI assistants are not a guaranteed speedup.** In METR's RCT with 16 experienced OSS developers on 246 real issues, AI-allowed tasks took **19% longer**, while developers *expected* a 24% speedup and *still believed* afterwards they had been sped up by 20%. Caveat honestly: these were experts on mature, familiar codebases — closer to the opposite of your situation. ([METR, July 2025](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)) Meanwhile a study of 31 undergraduates across 9 teams at a 9-hour "vibe coding" hackathon found rapid prototyping *and* **premature ideation convergence, code quality requiring rework, and shallow engagement with engineering practices**. ([arXiv:2512.02750](https://arxiv.org/abs/2512.02750))
   → **Consequence:** the danger is not that AI slows you down; it is that it produces plausible code fast in a domain (payment reconciliation) where plausible-but-wrong is indistinguishable from correct without tests. §7.

---

## 1. What distinguishes winning teams from good ideas that lose

Ranked by how much leverage each gives you, most first:

| Differentiator | What losing teams do | What to do instead |
|---|---|---|
| **A working end-to-end path** | Deep in one layer (beautiful OCR prompt, no reconciliation) | One thin path from screenshot upload to rendered verdict, working by end of day 1 |
| **A demo that survives contact** | Live API call to DashScope at the judge's table | Fixture-backed deterministic path; live call as an *optional upgrade* you switch on if the network holds |
| **A crisp problem statement** | "AI for payments" | "A Karachi shopkeeper gets a JazzCash screenshot. Is it real, is it enough, and has it already been used?" |
| **Showing the hard case** | Demoing only the happy path | Demo VERIFIED, then DUPLICATE, then SUSPICIOUS — three orders, 90 seconds |
| **Explaining the design decision** | "We used a fraud model" | "We deliberately refuse to output a fraud percentage; here is the per-field evidence and the rule version that produced this verdict" |
| **Being reachable in Q&A** | One person knows the whole system | Every member can answer for their module in one sentence |

Two evidence-based points worth internalising:

- **Winners think in explicit divergent→convergent phases even without design training.** The study of hackathon winners' methods found they follow *"a sequence of phases that involve divergent and convergent thinking to explore the problem space and propose alternatives in a solution space"* — the distinguishing behaviour is *structured* exploration, then deliberate narrowing, not one long undifferentiated build. ([arXiv:2206.04744](https://arxiv.org/abs/2206.04744)) You have already converged (architecture is decided). Your risk is therefore not premature convergence but **failing to re-diverge on the demo narrative** — treat "what story do we tell" as its own divergent exercise on day 1, not an afterthought on day 3.
- **Stack ranking means the marginal feature is worth less than the marginal minute of demo polish.** Under 3/2/1 top-3 scoring, a project that is 20% more capable but 20% less legible loses. This is the single most common way strong engineering teams lose.

**The specific trap for ProofPay:** your architecture is genuinely sophisticated (versioned deterministic rules wrapping probabilistic models, DB-level allocation uniqueness, adapters with local fallbacks). Sophistication that isn't *visible in 2 minutes* scores zero. Plan how each commitment becomes a visible demo beat:

| Architectural commitment | Its demo beat (≤10s) |
|---|---|
| No screenshot signal alone proves payment | Upload a *perfect-looking* screenshot with no matching merchant txn → `UNMATCHED`, not VERIFIED |
| DB constraint enforces allocation uniqueness | Re-submit the same screenshot on a second order → `DUPLICATE`, and show the `IntegrityError` path in the log |
| Versioned decision rules | The verdict card prints `rules_version: v1.0.3` and the same input replays identically |
| Adapter with local fallback | Kill the network mid-demo on purpose (once, rehearsed) → still returns a verdict, banner says "extraction: stub adapter" |
| Amount semantics | Show underpayment vs claim inflation as *different* verdicts, not both "mismatch" |

That table is your pitch outline. Write it before you write code.

---

## 2. Scope selection

### Why teams over-scope
Three mechanical reasons, not moral failings:

1. **Estimation is done on the happy path.** The 20% of work that is glue, env setup, and data seeding is invisible when planning.
2. **Integration cost is non-linear.** Fowler: *"If there's twice as much code to integrate, it's more likely to be four times as long."* Doubling scope more than doubles the endgame. ([Fowler, Continuous Integration](https://martinfowler.com/articles/continuousIntegration.html))
3. **Four people feel like four times the throughput.** They are not, for a 72h shared codebase; they are closer to 2.5× with 1.5× coordination overhead.

### The smallest demo that proves ProofPay

Write this sentence and pin it in your channel:

> *Given one screenshot and one merchant transaction feed, ProofPay returns one of five states with a per-field evidence breakdown, and it refuses to say VERIFIED on screenshot evidence alone.*

Everything that is not required for that sentence is Tier 2 or Tier 3.

| Tier | Contents | Rule |
|---|---|---|
| **T0 — the spine** | Upload endpoint → extraction adapter (stub) → normalized `PaymentClaim` → candidate retrieval → scoring → rules v1 → verdict JSON → one React page rendering it | Must be green end-to-end by **hour 12**. If not, cut T1 immediately. |
| **T1 — the differentiators** | Real Qwen-VL adapter; DUPLICATE via DB unique constraint; amount semantics (under/inflated/over); evidence breakdown UI | Only after T0 is green. Each is independently cuttable. |
| **T2 — nice** | Tamper-evidence signals; multi-provider screenshot templates; merchant CSV import UI; auth | Build only if T1 done by hour 36 |
| **T3 — never** | Multi-tenancy, Postgres migration, rate limiting, Docker Compose prod stack, user accounts, i18n, dark mode | Cut now. Mention as "next steps" in the README instead — that costs 40 seconds and scores the same. |

### Vertical slice on day one — the rule and its justification

Build a **walking skeleton**: a tiny end-to-end implementation of the real system that performs a small real function and exercises every architectural connection, with near-trivial logic in each box. Then thicken it.

The layer-by-layer alternative ("get extraction perfect, then matching, then the API") fails predictably because *the integration risk is concentrated at the end*, when you have the least time and the least sleep. The vertical slice front-loads the discovery that your `PaymentClaim` schema is missing a field, that PKR amounts arrive as `"Rs 12,500.00"`, and that your timestamps are naive.

Concretely, the hour-12 acceptance test — write this test *first*, before the modules it calls exist:

```python
# tests/test_spine.py
def test_walking_skeleton(client, seeded_merchant_feed):
    """The whole pipeline, thin. Must stay green from hour 12 to submission."""
    with open("tests/fixtures/screenshots/easypaisa_ok.png", "rb") as f:
        r = client.post("/api/orders/ORD-1001/verify", files={"screenshot": f})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] in {
        "VERIFIED", "UNMATCHED", "SUSPICIOUS", "DUPLICATE", "NEEDS_REVIEW"
    }
    assert body["rules_version"]                      # versioned engine is wired
    assert {e["field"] for e in body["evidence"]} >= { # every scorer is wired
        "amount", "sender_name", "timestamp", "reference_id"
    }
    assert "fraud_score" not in body                   # architectural commitment, tested
```

That last assertion is not a joke. It is the cheapest possible guard on a commitment you have made, and under fatigue at hour 60 someone *will* add a percentage because it "looks better in the UI".

**Anti-pattern specific to this domain:** starting with the vision model. Qwen-VL extraction is the most interesting part and the *worst* place to start — it has an external dependency, non-deterministic output, and quota risk. Start with `FixtureExtractionAdapter` that returns a hand-written `PaymentClaim` for each fixture image. The real adapter is a drop-in later, and if DashScope is down at demo time you still have a product.

```python
# app/extraction/adapter.py  — write this in hour 1, freeze the interface
class ExtractionAdapter(Protocol):
    def extract(self, image_bytes: bytes) -> PaymentClaim: ...

# app/extraction/fixture_stub.py — the fallback that makes the demo unkillable
class FixtureExtractionAdapter:
    """Keyed by sha256 of the image; falls back to a generic claim."""
    def extract(self, image_bytes: bytes) -> PaymentClaim:
        return _FIXTURES.get(sha256(image_bytes).hexdigest(), _GENERIC)
```

---

## 3. Time allocation

There is no rigorous study of optimal hackathon time allocation; what follows is the consensus of organiser guidance plus the arithmetic of §0.1. Treat the *reasoning* as the durable part.

**Budget for a 72h event (adjust proportionally):**

| Block | Hours | % | Reasoning |
|---|---:|---:|---|
| Kickoff, scope lock, contract freeze, repo skeleton | 4 | 6% | Interfaces frozen early is what lets four people work without blocking |
| Walking skeleton to green | 8 | 11% | Hour 12 checkpoint |
| Thickening T1 | 30 | 42% | The actual build |
| Integration + hardening + demo-data seeding | 10 | 14% | Non-negotiable, scheduled, not "what's left" |
| Demo script, rehearsal, backup video | 8 | 11% | See below |
| README + submission form + AI disclosure | 4 | 6% | Judges read it during deliberation |
| Slack/buffer (things will break) | 8 | 11% | If you don't budget it, it eats demo prep |

**Roughly 25–30% of total time on demo, video, README and rehearsal.** Teams find this shocking. The justification is direct: judges spend ~4 minutes per round on you and a 2-minute video is what represents you in final deliberation. Cutting demo prep to buy two more build hours trades a large scoring input for a small one.

**Hard rule: freeze code at T-4h.** Last 4 hours are rehearsal, README, submission, and sleep. Every experienced team has the story of a last-hour "tiny fix" that broke the demo. Enforce with a branch protection you set yourselves: after T-4h, `main` accepts only changes to `README.md`, `docs/`, and `tests/fixtures/`.

**The 2-minute video:** record it at **T-8h, not T-1h**, from a working build, then re-record only if something materially improves. A recorded video is also your disaster recovery if the live demo dies. Record it with OBS (free), 1080p, in a screen area you have already zoomed so text is legible on a projector.

**The README is a judged artifact.** MLH's own rules require you to list frameworks used and disclose AI usage there or in the submission. Structure it as: one-sentence problem → 4-line "what it does" → the 30-second quickstart → the five states table → architecture diagram → **what we deliberately did not do and why** (this section wins Q&A) → frameworks list → AI usage disclosure.

---

## 4. Working as four people

### Split by files, not just by tasks

Task-splitting still produces merge conflicts, because two tasks touch one file. Assign **directory and file ownership**, and make the shared files small and frozen early.

Proposed ownership for the ProofPay monolith:

```
proofpay/
  app/
    main.py                  ██ SHARED — frozen after hour 4
    config.py                ██ SHARED — frozen after hour 4
    schemas.py               ██ SHARED — the contract; changes only in a "contract window"
    db/
      models.py              ██ SHARED — frozen after hour 6 (migrations follow)
      session.py             ██ SHARED
      seed.py                ── D
    extraction/              ── A   (adapter.py, qwen_vl.py, fixture_stub.py, normalize.py)
    tamper/                  ── A   (signals.py)
    matching/                ── B   (candidates.py, scoring.py, duplicates.py)
    decision/                ── C   (rules_v1.py, evidence.py, states.py)
    api/
      routes_verify.py       ── C
      routes_orders.py       ── D
  web/src/                   ── D
  tests/
    test_extraction.py       ── A
    test_scoring.py          ── B
    test_rules_v1.py         ── C
    fixtures/                ── append-only, anyone (never edit an existing fixture)
  scripts/
    demo_reset.py            ── D
```

Rules that make this work:

1. **Shared files change only in an announced "contract window."** One person types, others watch, 15 minutes, then everyone pulls. Two contract windows total: hour 4 and hour 24. After that, additive changes only (new optional fields on `PaymentClaim`, never renames).
2. **Registries are append-only modules, not edited dicts.** Instead of everyone editing one `SCORERS = {...}` dict (guaranteed conflict), each scorer lives in its own file and self-registers:
   ```python
   # app/matching/scorers/__init__.py  — this file is the ONLY shared bit, and it's 4 lines
   from . import amount, sender_name, timestamp, reference_id  # noqa: F401
   ```
   Adding a scorer = one new file + one import line. A one-line conflict resolves in seconds; a 40-line dict conflict does not.
3. **Never format the whole repo.** Agree on `ruff format` in hour 1 and add a pre-commit hook. A day-2 "let me just format everything" commit creates a repo-wide conflict for three people at once.
4. **Windows line endings will bite you.** You are on Windows; add on hour 1:
   ```
   # .gitattributes
   * text=auto eol=lf
   *.png binary
   uv.lock -diff
   ```
5. **Lock-file conflicts are resolved by regeneration, not by hand:**
   ```bash
   git checkout --theirs uv.lock && uv lock && git add uv.lock
   ```
   Better: **one person owns dependencies.** Anyone else who needs a package asks in the channel. This alone removes the most common conflict for a Python team.

### Integration cadence

Fowler's target is *"every developer should commit to the mainline every day"*, with experienced practitioners going more frequently, and Kent Beck's *"No code sits unintegrated for more than a couple of hours."* For a 72h hackathon, compress it: **push to `main` at least every 2 hours; branches live under 4 hours.** ([Fowler](https://martinfowler.com/articles/continuousIntegration.html), [trunkbaseddevelopment.com](https://trunkbaseddevelopment.com/))

Contested point, stated honestly: some hackathon advice says "just all commit to `main`, no branches, no PRs." For a four-person team with one git novice, **use short-lived branches with self-merge (no review gate) rather than direct pushes to `main`.** The reason is not code quality — it is that a novice force-pushing or committing a broken state directly to `main` at hour 50 is a catastrophic, hard-to-undo failure, whereas an abandoned branch costs nothing. Trunk-based development explicitly permits this ("short-lived feature branches… lasting only as long as a single developer's work").

The novice's git card — print it:

```bash
# start of every work chunk
git switch main && git pull --rebase
git switch -c b/<yourname>/<thing>

# ...work...
git add -A && git commit -m "matching: score sender name with rapidfuzz"

# integrate (do this every ~2 hours, not once a day)
git switch main && git pull --rebase
git switch - && git rebase main      # fix conflicts here, small and early
uv run pytest -q                     # must be green BEFORE merging
git switch main && git merge --no-ff - && git push

# if anything goes wrong, NEVER force-push main. Ask. Your branch is safe.
```

### Preventing "everything works separately, nothing works together"

This is the failure mode the walking skeleton exists to prevent, but it needs continuous enforcement:

- **A `main`-must-be-green rule with a 60-second check.** Fowler: *"any test failing is enough to fail the build, 99.9% green is still red."*
  ```powershell
  # scripts/check.ps1  — everyone runs this before merging
  uv sync --locked
  uv run ruff check app tests
  uv run pytest -q -m "not slow"
  uv run python scripts/demo_reset.py --dry-run
  ```
  Add the same as a GitHub Actions workflow on push (free for public repos). Ten minutes to set up on day 1; catches the "works on my machine" class of failure for the whole event.
- **Scheduled integration syncs: hour 12, 24, 36, 48, 60.** 15 minutes, everyone pushes, run the spine test together, fix what's red before anyone starts anything new. Put them in a calendar with alarms. Under fatigue nobody will remember.
- **Demo-driven integration.** From hour 24 onward, at every sync one person runs *the actual demo script* start to finish. This is different from running tests; it catches "the frontend calls `/verify` but the backend renamed it to `/verifications`".

### When someone is blocked or falls behind

Have the policy decided *before* it happens, because in the moment it becomes a social problem:

| Situation | Response |
|---|---|
| Blocked >30 min on anything | Say so in the channel. Non-negotiable. A 30-minute timer is the rule; "I don't want to interrupt anyone" is how 6 hours disappear. |
| Blocked on someone else's module | Do not wait. Stub their interface locally and keep moving: `class FakeScorer: def score(self, *a): return FieldScore(1.0, "stub")`. The frozen contract in `schemas.py` is what makes this possible. |
| Behind on a T1 item at a checkpoint | Cut it, don't rescue it. Reassignment mid-flight costs the receiver context-load time they don't have. |
| The novice is behind | Most likely cause is environment/git, not capability. Fix by pairing for 30 minutes, not by taking work away — taking work away in hour 20 usually means they contribute nothing for the remaining 50. |
| Someone goes quiet for >2h | Check on them. Fatigue and embarrassment compound. |

**Give the novice ownership of a genuinely load-bearing but low-blast-radius area.** For ProofPay that is `scripts/demo_reset.py` + `db/seed.py` + fixtures + README. This is high-value (it *is* the demo), teaches git through low-conflict files, and cannot break the spine. Do not park them on "the frontend" as a euphemism for "away from the real code" — it is both demoralising and, for this project, the frontend is on the critical path.

---

## 5. Planning and testing under time pressure — an honest accounting

You have prioritised planning and testing. That is defensible, but it is a *bet*, and it can be lost. Here is where it pays and where it does not.

### Where tests genuinely pay for themselves inside 72 hours

**Pure, deterministic, high-branch-count logic that you will change repeatedly.** For ProofPay that is exactly: `matching/scoring.py`, `decision/rules_v1.py`, amount semantics, and normalization. These have three properties that make tests profitable *within days*:

- You will tune thresholds many times. Without tests, each tuning pass requires a manual end-to-end re-check (≈3 minutes each). With a table test, it is 2 seconds.
- Failures are silent. A wrong fuzzy-match threshold does not crash; it produces a confident wrong verdict. In a *payment verification* demo, a wrong verdict in front of judges is worse than a crash — it undermines the whole premise.
- The correctness is the product. Your differentiator *is* the decision table. Untested, you cannot honestly claim it.

The cheap, high-yield shape — a decision table as parametrised test:

```python
# tests/test_rules_v1.py
CASES = [
    # id,                 amt_delta, name_score, ts_delta_s, ref_match, allocated, expect
    ("exact",                   0.0,       0.98,        30,      True,     False, "VERIFIED"),
    ("underpaid",            -500.0,       0.98,        30,      True,     False, "SUSPICIOUS"),
    ("claim_inflated",       +500.0,       0.98,        30,      True,     False, "SUSPICIOUS"),
    ("overpaid_small",        +10.0,       0.98,        30,      True,     False, "VERIFIED"),
    ("no_candidate",         None,         None,      None,      None,     False, "UNMATCHED"),
    ("reused_txn",              0.0,       0.98,        30,      True,      True, "DUPLICATE"),
    ("name_fuzzy_low",          0.0,       0.55,        30,      True,     False, "NEEDS_REVIEW"),
    ("stale_timestamp",         0.0,       0.98,    172800,      True,     False, "NEEDS_REVIEW"),
]

@pytest.mark.parametrize("cid,dv,ns,ts,ref,alloc,expect", CASES, ids=[c[0] for c in CASES])
def test_rules_v1(cid, dv, ns, ts, ref, alloc, expect):
    assert decide_v1(make_evidence(dv, ns, ts, ref, alloc)).state == expect
```

That is ~25 lines, takes 20 minutes, and is simultaneously (a) your regression suite, (b) your specification, (c) a slide in your pitch, and (d) the answer to the judge who asks "how do you decide?". **Put this table in the README verbatim.** Very few hackathon teams can show a judge a decision table backed by green tests; it is disproportionately persuasive.

Second high-yield test: **the DB uniqueness constraint.** You have committed to enforcing allocation uniqueness in the database. Test it *at the database*, because that is the claim:

```python
def test_allocation_uniqueness_is_enforced_by_the_database(session):
    session.add(Allocation(txn_id="TX1", order_id="ORD-1")); session.commit()
    session.add(Allocation(txn_id="TX1", order_id="ORD-2"))
    with pytest.raises(IntegrityError):
        session.commit()
```

Three lines. It proves an architectural commitment that would otherwise be a claim in a slide. Note the SQLite/Postgres portability trap: a plain `UniqueConstraint("txn_id")` behaves the same on both; a *partial* unique index (`WHERE status='active'`) does not have identical syntax — stay with the plain constraint for the hackathon.

### Where tests do NOT pay for themselves in 72 hours

Be ruthless here. Google's own guidance is *"start with unit tests and only use larger tests when unit tests clearly are not sufficient"*, with a rough 70/20/10 unit/integration/E2E split, because E2E tests are slow, brittle, environment-dependent, and hard to debug. ([Google Testing Blog](https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html)) In a hackathon, tilt further:

| Do not write | Why | Cheap substitute |
|---|---|---|
| Browser E2E (Playwright/Selenium) | Setup + flakiness eats hours; the "test" is your rehearsal | Run the demo script manually at each sync |
| React component tests | UI churns hourly; tests are stale before they run | Eyeballs |
| Tests for the Qwen-VL adapter's real output | Non-deterministic, costs quota, tests DashScope not you | One recorded response JSON as a fixture; test only your *parsing* of it |
| FastAPI route tests for every endpoint | Mostly tests FastAPI | One spine test (§2) covering the one route that matters |
| Mocking frameworks / DI containers | Setup cost exceeds the 72h payback | Pass the adapter as a constructor argument |
| Coverage targets | Optimises the wrong thing under time pressure | Ignore coverage entirely |

### The honest tradeoff

Planning and testing are not free, and a team that over-invests loses in a specific, recognisable way: **it arrives at hour 60 with an immaculate, well-tested core and no demo.** The evidence from the code-reuse study is that hackathon output is small (≈8% of repo LOC created during the event) — you are not building much code, so the risk of under-testing is smaller than the risk of under-demoing.

Guardrails against your own bias:

- **Test budget: no more than ~15% of build time**, concentrated entirely in `scoring.py`, `rules_v1.py`, and the uniqueness constraint. If `pytest -q` takes more than 20 seconds, you have over-invested.
- **Planning budget: the architecture is already written. You get 4 hours of planning at kickoff and 0 hours after.** Any further "let's reconsider the module boundary" conversation after hour 4 is scope creep wearing a lab coat. Log it in `docs/DEFERRED.md` and move on.
- **Test the commitments, not the code.** Every test you write should map to a sentence you will say to a judge. If it doesn't, it's probably not worth 72-hour money.

---

## 6. Sleep, energy, pacing

The evidence is unusually clean here, and it points one way.

- 17–19 hours awake ≈ 0.05% BAC on some tasks; response times up to 50% slower; extended deprivation reaches 0.1% BAC equivalence (Williamson & Feyer 2000).
- Under restriction, **self-report stops tracking impairment** — subjective sleepiness did not differentiate 6h from 4h nights while objective deficits kept compounding (Van Dongen et al. 2003).

Combine those with the structural fact that **demo prep, submission, and rehearsal happen in the final hours**, and the all-nighter is straightforwardly a bad trade: you buy build hours at 60% efficiency and pay for them with demo hours at 50% efficiency, in the phase with the highest score-per-hour.

**Policy (adopt as a rule, not an aspiration):**

1. **No full all-nighters. Everyone sleeps ≥6h on the night before demo day.** Put it in the plan on day 0 so it isn't a negotiation at 2am.
2. **If you must run overnight, use a shift rota, never four people awake at 4am.** Two on, two off, 4-hour shifts. The overnight pair does *low-branching* work: fixtures, seed data, README, styling, video editing. Never overnight: touching `schemas.py`, `models.py`, migrations, or the decision rules.
3. **The novice does not take the overnight shift.** They have the least context to recover a mistake and the most to lose from a bad first experience.
4. **Institute a "no solo merges after midnight" rule.** Impairment is invisible to the impaired; a second pair of eyes is the only working check.
5. **Pacing markers:** stand up every hour; eat actual meals at fixed times (blood-sugar crashes look exactly like being stuck); caffeine before ~6 hours prior to your sleep block only. Hydration matters more than most people believe at hour 40.
6. **Schedule the crash.** Plan a mandatory 90-minute nap for everyone at roughly hour 40. Teams that plan rest recover; teams that "rest when we finish X" never rest.

Contested point: some competitive teams do run all-nighters and win. Where that works, it is typically a very short (24h) event where there is no "final hours" to protect, or a team with a dedicated non-coding demo person who slept. Neither applies to you. **Recommendation: no all-nighters.**

---

## 7. Using AI coding assistants effectively and honestly

### Disclosure — do this first, not last

MLH's model rules are explicit: AI use is permitted but *"must state how you did so"*; the project must not be *"a reskin of an existing AI tool"*; you must *"document what they created versus what was generated"*; and failure to credit is a disqualification-and-report offence. **Check your specific event's rules, but assume this is the floor.**

Create `AI_USAGE.md` in hour 1 and append as you go — writing it at hour 70 from memory produces a vague statement that reads worse than the truth:

```markdown
# AI usage disclosure

## Tools
- Claude Code (Opus) — code generation, refactoring, test scaffolding
- Qwen-VL via Alibaba Cloud Model Studio — **a product feature**, not a dev tool:
  it performs field extraction from payment screenshots at runtime.

## Where AI wrote code
- app/matching/scoring.py — RapidFuzz scorer bodies AI-drafted, thresholds
  chosen by us from tests/fixtures/, all cases in tests/test_scoring.py human-authored.
- web/src/components/EvidenceTable.tsx — AI-drafted, restyled by hand.
- app/decision/rules_v1.py — **human-authored.** The decision table is our design;
  AI was used only to convert it into code.
- Alembic migrations — generated by Alembic autogenerate, reviewed by hand.

## Where AI did NOT write code
- The architecture, the five-state model, the amount semantics, and the
  decision rules. These are specified in docs/ (authored before the event as
  design, not code — see docs/PROVENANCE.md).

## Licence diligence
- All dependencies and their licences listed in README.md.
- Copilot/assistant public-code matching filters enabled; no code copied from
  a Stack Overflow answer or GitHub repo without attribution.
```

### Where assistants help most, in this project

| High leverage | Why |
|---|---|
| Boilerplate you can verify by inspection | Pydantic schemas, Alembic scaffolds, Tailwind layout, argparse for `demo_reset.py` |
| Test *cases* from a spec you wrote | Give it the decision table; it produces the parametrised list. You check the table, not the code. |
| Unfamiliar-API glue | DashScope SDK call shape, SQLAlchemy 2.x `select()` syntax — but verify against current docs (see §9) |
| Error-message triage | Pasting a SQLAlchemy or Alembic traceback is genuinely faster than searching |
| README and pitch drafts | Then rewrite in your voice; AI-flavoured prose is recognisable and reads as low effort |

### Failure modes to watch for — specific to payment reconciliation

1. **Plausible-but-wrong numeric logic.** An assistant will happily write `if abs(claimed - actual) < 0.01: VERIFIED`, silently collapsing your underpayment / claim-inflation / overpayment distinction. **Guard: the decision table test.**
2. **Silent float money.** Assistants default to `float` for amounts. PKR amounts and tolerance comparisons need `Decimal`. Add a test: `assert isinstance(claim.amount, Decimal)`.
3. **Naive datetimes.** Pakistan is UTC+5; screenshots show local time; SQLite stores naive datetimes; an assistant will mix them and every timestamp score will be off by 5 hours, causing *every* match to fail 20 minutes before the demo. **Guard: store UTC-aware everywhere, normalize at the extraction boundary, and assert `dt.tzinfo is not None` in `PaymentClaim` validation.**
4. **Constraint enforcement drifting into application logic.** Asked to "prevent duplicate allocation", assistants overwhelmingly write a `SELECT` then an `INSERT`. That is a race and it violates a stated commitment. Insist on the DB constraint plus `IntegrityError` handling.
5. **Reintroducing a fraud score.** Ask for "a confidence display" and you get a percentage. Guarded by the spine test's `assert "fraud_score" not in body`.
6. **Large refactors offered mid-event.** Decline all of them after hour 24, regardless of how right they are.
7. **Confident wrong API surfaces.** Model IDs, SDK method names, and base URLs are exactly where model memory is stale. Verify against live docs.
8. **The perception gap.** METR found developers believed they were 20% faster while being 19% slower. **Guard: at each integration sync, ask "did the last block produce something demoable?" — measure output, not felt velocity.**

For the novice specifically, the vibe-coding study's finding is the warning: rapid output, then rework, with limited engagement in core engineering practice. The mitigation is a rule: **you may not merge code you cannot explain line by line.** Not for purity — because a judge will ask, and because at hour 60 you will have to debug it.

### Ownership of correctness and licence

- **Correctness:** the tests are yours, the thresholds are yours, the verdicts are yours. "The model wrote it" is not an answer to a judge and would not be an answer to a merchant who got a false VERIFIED.
- **Licence:** GitHub's own position on Copilot is that suggestions *"may… match code in the training set"*, that a duplication-detection filter exists and should be configured, and that *"users assume all risks associated with generated code including security vulnerabilities, bugs, and IP infringement"*, with an obligation to *"always review Copilot's suggestions before accepting them."* ([GitHub docs](https://docs.github.com/en/copilot/responsible-use-of-github-copilot-features/responsible-use-of-github-copilot-code-completion)) MLH's line is the same in the other direction: open source is fine *"as long as we respect the license."*
  **Cheap version (15 minutes, do it at T-6h):** turn on the public-code matching filter in whatever assistant you use; run a licence inventory and paste it into the README:
  ```bash
  uv run --with pip-licenses pip-licenses --format=markdown --order=license > docs/LICENSES.md
  ```
  Then scan for anything not MIT/BSD/Apache-2.0/PSF. A GPL transitive dependency in a submitted project is a real, avoidable problem.

---

## 8. Working with pre-written design documents

One of you has authored detailed architecture before the build. This is a genuine advantage and a genuine hazard.

### Handle the rules question first
MLH-style rules say you may not *work on your project* before the event and should not reuse code from previous projects, and organisers check git history for pre-event commits. Design documents, diagrams, and decision tables are conventionally treated as ideation/planning rather than "the project" — but the burden is on you to make that visible:

- **Do not backdate or squash.** Let the git history show honest timestamps.
- **Commit `docs/` in a first commit dated at the event start**, with a `docs/PROVENANCE.md` saying plainly: *"Architecture documents in this directory were written before the event as design/planning. No implementation code existed before <event start>. All code in `app/` and `web/` was written during the event."*
- **If in any doubt, ask the organisers in writing before the event and keep the reply.** Ten minutes of email removes the only category of risk that can void everything else.

### Using the docs without paralysis

The failure mode is **specification worship**: three people idling while they wait to understand the architecture, or refusing to proceed because the doc doesn't cover a case. The related paper on preparation-heavy AI-assisted hackathon work is encouraging about front-loaded context (~2 hours of preparation enabling parallel implementation, arXiv:2605.05400), but its whole point is that preparation exists to *enable* parallel action — a doc that is being read instead of acted on has inverted its purpose.

Practical protocol:

1. **The author gives a 30-minute walkthrough at kickoff, then stops being the oracle.** If every question routes through one person, they become the bottleneck and cannot build.
2. **Extract from the docs exactly three artifacts, and treat only those as binding:**
   - `app/schemas.py` — the `PaymentClaim` / `Evidence` / `Verdict` types
   - `docs/DECISION_TABLE.md` — the five states and the rules that produce them
   - `docs/MODULES.md` — one paragraph per module + who owns it
   Everything else in the docs is **advisory**. Say this out loud on day 0.
3. **Mark each document section `BINDING` or `ADVISORY` in hour 1.** Fifteen minutes; removes almost all "am I allowed to..." friction.
4. **The doc author should not also own the demo.** They will over-explain the architecture and under-show the product.

### When to deviate

| Deviate immediately | Do not deviate |
|---|---|
| The doc's approach doesn't work with the actual library API | You "would have done it differently" |
| It costs >2h more than an equivalent alternative | It is not the most elegant option |
| It requires an unavailable dependency (paid tier, missing key) | It requires you to learn something |
| It blocks the walking skeleton | It affects only code you'll never extend |
| It conflicts with a *demo beat* from §1 | It conflicts with your aesthetic preference |

**Never deviate from the five architectural commitments.** They are your differentiator and your pitch. If you drop the DB constraint or add a fraud percentage, you have built a generic OCR demo and you will be ranked against generic OCR demos.

Log every deviation in one line in `docs/DEVIATIONS.md`:
```
h27 — matching/candidates.py: doc specifies a two-stage retrieval with a time-window
      pre-filter; using a single query over the seeded feed (n<500). Reason: 2h saved,
      no observable difference at demo scale. Revisit for production.
```
That file is a *pitch asset*. "We knowingly deviated here and here is why" reads as engineering maturity; the judge who asks "does this scale?" gets an answer that already exists.

---

## 9. Demo-day technical failures and prevention

These are the failures that kill working projects. Each has a cheap, specific prevention.

| Failure | Prevention | Do it by |
|---|---|---|
| **Dependency drift** ("works on my machine") | Commit `uv.lock`; everyone runs `uv sync --locked` (errors instead of silently updating the lockfile); pin Python in `.python-version` and `requires-python` in `pyproject.toml`. `uv sync` is exact by default — it *removes* packages not in the lock. | Hour 2 |
| **Missing env vars** | `.env.example` committed with every key present and blank; `config.py` fails loudly at startup listing all missing keys, never silently defaults. 12-factor's litmus test: *"the codebase could be made open source at any moment, without compromising any credentials."* | Hour 4 |
| **DB state on one laptop only** | `scripts/demo_reset.py` recreates everything from committed fixtures and prints the demo order IDs. Never a hand-mutated SQLite file. Add `*.db` to `.gitignore` and never make an exception. | Hour 12 |
| **Alembic vs `create_all` drift** | Pick Alembic and delete every `Base.metadata.create_all` call. Two people using different schema paths is a guaranteed hour-60 mystery. | Hour 6 |
| **Expired / rate-limited API credentials** | Model Studio API keys *"remain valid until you manually delete them"* and the plaintext key is **shown only once at creation** — store it immediately. But free quota and regional endpoints do expire/vary: the env var is `DASHSCOPE_API_KEY` and the `base_url` *"differs between the two protocols and varies by region."* Have a second key on a second account. And rely on the fixture adapter for the demo path. | Hour 8 |
| **Stale model IDs** | Model Studio's model catalogue does not currently list the `qwen-vl-*` names from memory as available under those exact IDs. **Verify the live model list in the console before writing the adapter**, and put the model ID in config, never a literal. | Hour 8 |
| **Hardcoded `localhost`** | Frontend uses `import.meta.env.VITE_API_BASE ?? "/api"` with a Vite dev proxy; backend uses a `PUBLIC_BASE_URL` setting. Grep before submission: `git grep -n "localhost\|127\.0\.0\.1\|:8000" -- app web/src` | T-6h |
| **CORS at the venue** | Set `allow_origins` from config, not a literal. It will bite when the URL changes. | Hour 6 |
| **Wi-Fi dies** | Everything must run offline: fixture adapter, seeded SQLite, `vite build` served by FastAPI as static files (one origin, no CORS, no dev server). Practise the demo with the laptop in airplane mode. | T-12h |
| **Projector illegibility** | Rehearse at 1920×1080 with browser zoom at 150%. Half of hackathon demos are unreadable from row three. | T-8h |
| **Live camera / real screenshot upload** | Have the exact demo images in a folder on the desktop. Do not take a screenshot live. | T-8h |
| **Laptop sleeps / notifications** | Disable sleep, notifications, and auto-updates on the demo laptop the night before. | T-12h |
| **The "one tiny fix"** | Code freeze at T-4h. | T-4h |
| **Total demo failure** | The 2-minute video, recorded at T-8h, on the laptop and on a phone. | T-8h |

**The cold-clone test — the single highest-value 20 minutes of the whole event.** At **T-12h**, a teammate who did *not* write the backend clones the repo into a brand-new directory on a *different* laptop and runs only what the README says:

```bash
git clone <url> proofpay-cold && cd proofpay-cold
cp .env.example .env          # no secrets required for the fixture path
uv sync --locked
uv run alembic upgrade head
uv run python scripts/demo_reset.py
uv run uvicorn app.main:app --port 8000
# open http://localhost:8000  -> the demo must work end to end
```

If any step fails, that is your top-priority bug. This test catches missing migrations, uncommitted fixtures, undeclared dependencies, unstated env vars, and a wrong README simultaneously. Run it again at T-4h.

**Demo-day kit:** the demo laptop plus a fully-set-up backup laptop; the video on two devices; HDMI + USB-C adapters; a phone hotspot; the seeded DB reproducible in 30 seconds; a printed one-page architecture diagram to hand a judge while you talk.

---

## 10. Day-by-day playbook (72h)

Checkpoints are **cut gates**. At each one you answer a yes/no question, and a "no" triggers a specific pre-agreed cut. Decide the cuts now, in the calm, so you are not negotiating scope at hour 48.

### Day 0 — hours 0–4: lock everything cheap

- Read the event rules end to end, including AI and prior-work policy. If ambiguous, email organisers.
- 30-min architecture walkthrough by the doc author. Then mark docs `BINDING` / `ADVISORY`.
- Write the one-sentence scope statement (§2) and pin it.
- **Divergent 20 minutes on the demo narrative**, then converge: write the five demo beats (§1 table) into `docs/DEMO_SCRIPT.md`.
- Repo skeleton, `.gitattributes`, `.env.example`, `pyproject.toml` + `uv.lock`, `ruff`, GitHub Actions running `scripts/check.ps1`, ownership map posted in the channel.
- **Contract window #1:** `schemas.py`, `models.py`, `config.py` written together, then frozen.
- Create `AI_USAGE.md`, `docs/DEVIATIONS.md`, `docs/DEFERRED.md`, `docs/PROVENANCE.md`.
- Everyone gets `check.ps1` green on their own machine before anyone writes a feature.

### Day 1 — hours 4–24: the spine, then thickness

- Hours 4–12: **the walking skeleton**, all four working toward `tests/test_spine.py` going green. Fixture extraction adapter, trivial scorers returning constants, `rules_v1` returning `NEEDS_REVIEW`, one API route, one React page.
- **CHECKPOINT A — hour 12: "Does the spine test pass on `main`, and does the UI show a verdict?"**
  - **No →** all four people work on nothing but the spine until it passes. Cancel all T1 work. This is the single most important gate in the event.
  - **Yes →** start T1 in parallel, per ownership map.
- Hours 12–24: real scorers with the decision-table test; DB uniqueness constraint + test; real Qwen-VL adapter behind the same interface (A only); evidence-breakdown UI.
- **Contract window #2 at hour 24** — the last time `schemas.py` may change.
- **CHECKPOINT B — hour 24: "Can we demo VERIFIED and DUPLICATE from `demo_reset.py`?"**
  - **No →** cut the real Qwen-VL adapter to T2 and keep the fixture path. Extraction quality is not what you are being judged on.
  - **Yes →** proceed, and everyone sleeps.

### Day 2 — hours 24–48: differentiate, then stop adding

- Hours 24–40: amount semantics, SUSPICIOUS/UNMATCHED paths, tamper-evidence *observations*, evidence UI polish, seed data that tells a story (real-looking Pakistani names, PKR amounts, plausible timestamps — this matters more than you think for perceived quality).
- Hour 40: **mandatory 90-minute nap for everyone.**
- **CHECKPOINT C — hour 40: "Are all five states reachable in the demo?"**
  - **No →** cut whichever states aren't reachable and rewrite the demo script around three states. Three states shown confidently beats five states claimed.
  - Also cut here: everything still in T2. Move to README "next steps."
- Hours 40–48: **feature freeze on new modules.** Only wiring, bug fixes, and demo data from here.
- **CHECKPOINT D — hour 48: "Cold-clone test on a second laptop."** Fix whatever it finds before anything else.

### Day 3 — hours 48–72: it is a demo now, not a project

- Hours 48–56: fix cold-clone findings; write the README properly (decision table verbatim, frameworks list, deviations, deferred, next steps); finalise `AI_USAGE.md`; run the licence inventory.
- Hour 56–60 (**T-16h to T-12h**): full demo rehearsal, timed, all four people, each rehearsing their 20-second Q&A answer for their module. Rehearse in **airplane mode**. Rehearse the deliberate network-kill beat.
- **T-12h: second cold-clone test.** Demo laptop configured: no sleep, no notifications, browser zoom set, tabs pre-opened, fixture folder on desktop.
- **T-8h: record the 2-minute video.** Copy to phone and second laptop.
- **T-4h: CODE FREEZE.** Only `README.md`, `docs/`, `tests/fixtures/` may change.
- **T-4h to T-2h: submit.** Do not submit in the final 30 minutes — portals get slow and the deadline is not negotiable. Submit a complete entry early; edit it later if the portal allows.
- **T-2h to T-0: sleep, eat, and rehearse once more.** Do not open the editor.

### The cut heuristic, for any decision not covered above

> If it does not appear in `docs/DEMO_SCRIPT.md`, and removing it would not break `tests/test_spine.py`, it is optional. After hour 40, optional means cut.

---

## Anti-patterns, collected

- **Starting with the vision model.** Highest risk, lowest demo differentiation. Fixture adapter first, always.
- **Demoing only the happy path.** Your product's whole thesis is that the screenshot is an *untrusted claim*. Demo a rejection.
- **Adding a fraud percentage because it looks impressive.** It contradicts your stated design and invites a judge to ask how it's calibrated — a question you cannot answer.
- **Enforcing allocation uniqueness in Python.** SELECT-then-INSERT is a race and it makes your DB-constraint claim false.
- **Floats for money; naive datetimes for a UTC+5 country.** Both produce silent, total demo failure.
- **Committing a `.db` file.** It will be stale, and it will be the one someone demos from.
- **`create_all` and Alembic coexisting.**
- **A whole-repo reformat on day 2.**
- **Everyone editing one registry dict.**
- **Rescuing a behind-schedule feature by reassigning it at hour 50.**
- **Letting the architecture author be the oracle, the builder, and the demo presenter.**
- **Building for "production readiness" (Postgres, Docker, auth) at a hackathon.** Nobody scores it, and Postgres-vs-SQLite differences will bite you the night before.
- **Treating the README as paperwork.** MLH rules require the frameworks list in it, and judges read it in deliberation.
- **Writing `AI_USAGE.md` at hour 70.**
- **Sub-6-hour sleep before demo day, then trusting your own judgement about whether you're fine.**

---

## Definition of done

Phase complete when every box is checked.

**Rules and disclosure**
- [ ] Event rules read in full; any ambiguity about pre-written design docs resolved in writing with organisers.
- [ ] `docs/PROVENANCE.md` states plainly what existed before the event (docs only) and when code started.
- [ ] `AI_USAGE.md` exists, was updated continuously, and names which files were AI-drafted vs human-authored.
- [ ] README lists every framework/library used (MLH requirement) and `docs/LICENSES.md` shows no unexpected copyleft.

**Scope and plan**
- [ ] One-sentence scope statement pinned in the team channel.
- [ ] T0/T1/T2/T3 tier table agreed and visible; T3 explicitly deleted.
- [ ] `docs/DEMO_SCRIPT.md` exists with the five demo beats mapped to architectural commitments.
- [ ] Cut gates for checkpoints A–D written down **before** hour 12.

**Team mechanics**
- [ ] File-ownership map posted; shared files list is ≤5 files and frozen after hour 24.
- [ ] `.gitattributes` with `eol=lf`; one person owns `uv.lock`.
- [ ] Git card given to the novice; they own `seed.py`, `demo_reset.py`, fixtures, README.
- [ ] Integration syncs at hours 12/24/36/48/60 in everyone's calendar with alarms.
- [ ] 30-minute blocked-rule agreed out loud.

**Build integrity**
- [ ] `tests/test_spine.py` green on `main` since hour 12 and never allowed to go red.
- [ ] Decision table exists as a parametrised test **and** verbatim in the README.
- [ ] DB-level allocation uniqueness proven by an `IntegrityError` test.
- [ ] `assert "fraud_score" not in body` present in the spine test.
- [ ] `pytest -q` runs in under 20 seconds.
- [ ] CI runs `uv sync --locked`, ruff, and pytest on every push.

**Demo-day reliability**
- [ ] Cold-clone test passed on a second laptop at T-12h **and** at T-4h.
- [ ] Full demo runs end to end in airplane mode from `scripts/demo_reset.py`.
- [ ] `git grep localhost` returns nothing in `app/` or `web/src/`.
- [ ] `.env.example` complete; `config.py` fails loudly on missing keys.
- [ ] Second DashScope key on a second account, stored; model ID in config, verified against the live console.
- [ ] Demo laptop: sleep off, notifications off, zoom set, fixture images on desktop, backup laptop configured identically.
- [ ] 2-minute video recorded at T-8h, stored on two devices.

**Pacing**
- [ ] No member worked a full all-nighter.
- [ ] Everyone slept ≥6h the night before demo day.
- [ ] The hour-40 nap actually happened.

**Endgame**
- [ ] Code frozen at T-4h; only docs/fixtures changed after.
- [ ] Submission completed with ≥2h to spare, including repo link, video, description, frameworks, and AI disclosure.
- [ ] Every member can answer, in one sentence, what their module does and why it exists.
- [ ] `docs/DEVIATIONS.md` and `docs/DEFERRED.md` are populated — they are your Q&A answers.

---

## Sources

- [MLH — Judging Plan](https://guide.mlh.com/general-information/judging-and-submissions/judging-plan) — science-fair format, 3 min/team, 2-min video, stack-ranked 3/2/1 scoring, judge-count formula.
- [MLH — Rules for Your Hackathon](https://guide.mlh.com/general-information/judging-and-submissions/rules-for-your-hackathon) — no pre-event work, no reuse of prior projects, list frameworks in README, AI-use disclosure requirement.
- [MLH — Cheating Check](https://guide.mlh.com/general-information/judging-and-submissions/cheating-check) — git-history inspection, OSS permitted if licence respected.
- [Martin Fowler — Continuous Integration](https://martinfowler.com/articles/continuousIntegration.html) — daily mainline commits, non-linear integration cost, self-testing build, "99.9% green is still red".
- [Trunk Based Development](https://trunkbaseddevelopment.com/) — short-lived branches, small-team direct-to-trunk.
- [Google Testing Blog — Just Say No to More End-to-End Tests](https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html) — 70/20/10 pyramid, E2E flakiness and cost.
- [METR — Measuring the Impact of Early-2025 AI on Experienced OSS Developer Productivity](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/) — 19% slowdown vs 20% perceived speedup, with stated generalisability limits.
- [arXiv:2512.02750 — "Can you feel the vibes?" Novice programmer engagement with vibe coding](https://arxiv.org/abs/2512.02750) — 31 students, 9 teams, 9h hackathon; premature convergence, rework, shallow engineering practice.
- [arXiv:2207.01015 — One-off Events? Hackathon Code Creation and Reuse](https://arxiv.org/abs/2207.01015) — 9.14% of blobs / ~8% LOC created during hackathons; ~⅓ reused.
- [arXiv:2206.04744 — The Developers' Design Thinking Toolbox in Hackathons](https://arxiv.org/abs/2206.04744) — winners' divergent/convergent phase structure.
- [arXiv:2605.05400 — Mise en Place for Agentic Coding](https://arxiv.org/abs/2605.05400) — preparation-as-context-engineering; ~2h prep enabling parallel implementation.
- [Williamson & Feyer 2000, *Occup Environ Med* (via Europe PMC)](https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=TITLE%3A%22Moderate%20sleep%20deprivation%20produces%20impairments%20in%20cognitive%20and%20motor%20performance%22) — 17–19h awake ≈ BAC 0.05%; RT up to 50% slower.
- [Van Dongen et al. 2003, *Sleep* 26(2):117](https://academic.oup.com/sleep/article/26/2/117/2709164) — cumulative dose-dependent deficits; subjective sleepiness fails to differentiate 6h from 4h.
- [The Twelve-Factor App — Config](https://12factor.net/config) — env vars, open-source litmus test.
- [uv docs — Locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) — `uv.lock`, `uv sync --locked` / `--frozen`, exact sync semantics.
- [Alibaba Cloud Model Studio — Get an API key](https://www.alibabacloud.com/help/en/model-studio/get-api-key) — `DASHSCOPE_API_KEY`, plaintext shown once, keys valid until deleted, region-dependent `base_url`.
- [Alibaba Cloud Model Studio — Models](https://www.alibabacloud.com/help/en/model-studio/models) — model catalogue; verify current vision-model IDs here rather than assuming `qwen-vl-*`.
- [GitHub Docs — Responsible use of Copilot code completion](https://docs.github.com/en/copilot/responsible-use-of-github-copilot-features/responsible-use-of-github-copilot-code-completion) — public-code matching, duplication-detection filter, user assumes IP/bug risk.