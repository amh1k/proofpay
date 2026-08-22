# ProofPay — Phase Practice Guides

Seven guides, one per phase plus event strategy. Each is a decision record, not a tutorial: it states what we already committed to, what the current versions actually are (verified Aug 2026), and which mistakes to avoid.

**How to use them.** Read a phase's guide immediately *before* starting that phase — not all at once, and not while you are already mid-implementation. Reading them upfront wastes the detail; reading them late means you already made the choice the guide exists to prevent. The exception is `hackathon-strategy.md`, which is read on day zero by all four of us together.

Each guide is normative. If you disagree with a call, argue it in a PR comment — do not silently do something else. The architectural commitments listed in the project brief are settled and are not reopened.

## Phase map

| Phase | Guide | Read before |
|---|---|---|
| 0 — Event strategy | [`hackathon-strategy.md`](hackathon-strategy.md) | Day zero, before any code. All four members. |
| 1 — Verification engine | [`phase1-engine.md`](phase1-engine.md) | First line of `proofpay/core/` |
| 2 — Persistence & API | [`phase2-api.md`](phase2-api.md) | First migration or FastAPI route |
| 3 — Receipt understanding | [`phase3-receipt.md`](phase3-receipt.md) | First DashScope call or preprocessing code |
| 4 — Demo dataset | [`phase4-dataset.md`](phase4-dataset.md) | Generating the first fixture image |
| 5 — Merchant client | [`phase5-frontend.md`](phase5-frontend.md) | `npm create vite` |
| 6 — Demo, deploy, pitch | [`phase6-demo.md`](phase6-demo.md) | At **75% of remaining time**, not at the end |

## Cross-cutting principles

These were reached independently in more than one guide. That is why they rank above anything phase-local.

1. **Version and record everything that influences a decision.** `policy_version`, `rules_version`, `extractor_version`, `prompt_version`, `model_id`, `preproc_version` are stored on every claim and decision. A decision you cannot reproduce is one you cannot defend to a judge.
2. **Pass the clock in; never read it.** `datetime.now()` inside the engine makes golden tests flaky and the demo time-dependent. Phase 1 forbids it, Phase 4 pins a fixed anchor (`2026-08-20T14:05:00+05:00`). Same rule, two layers.
3. **Enforce boundaries with a test or a constraint, not a convention.** The core-layer purity test is 15 lines; the allocation uniqueness rule is a DB constraint. Both survive a tired teammate at 3am; a code-review habit does not.
4. **Abstain rather than guess.** A null field costs one `NEEDS_REVIEW`; a hallucinated field that happens to match the order costs a false `VERIFIED` and the whole thesis. Optimise extraction for abstention, and let the rule table route uncertainty to a human.
5. **Every external dependency has a working local fallback.** Missing API key, rate limit, dead conference wifi — quality degrades, the demo does not. This is checked by running the whole flow with the key unset, as a test.
6. **One dataset drives tests, the seeder, and the accuracy report.** Divergence between demo data and test data is how a system passes CI and fails on stage.
7. **Pin versions and commit the lock file on day one.** `uv.lock` and `package-lock.json`. Named traps: SQLAlchemy 2.1 beta, TypeScript 7, `@tanstack/react-table` 9, Node 18 vs Vite 8. Four laptops must resolve identically.
8. **Explain per-field; never emit a score.** The output is evidence a merchant can act on — sender name, amount semantics, timestamp window, reference — not a fraud percentage. This shapes the engine's return type *and* the UI's layout.
9. **The screenshot is a claim; the ledger is truth — and that must be visible.** Not just a backend invariant. The result view is structurally split into "what they claimed" vs "what we have", so a judge sees the architecture without being told.
10. **The judged artifact is the demo, README, and 4 minutes of talking.** Not the repo. Budget 20–25% of total time for Phase 6 and treat it as a deliverable with its own definition of done.

## The traps

Ranked by expected damage to our result.

1. **Live model call fails on stage.** No key, throttled, slow, or no network. Kills the demo outright. Mitigation is the fallback adapter plus a pre-recorded video that already exists.
2. **Phase 6 treated as wrap-up.** No video submitted, thin README, unrehearsed pitch. Costs 15–20% of the rubric directly and most of the deliberation-round memory. This is the classic strong-engineering-team failure.
3. **False `VERIFIED` from a hallucinated extraction.** A VLM completes toward the plausible receipt, and "plausible" correlates with "matches the order". If this happens once in front of a judge, the core claim is dead.
4. **Dependency drift across four machines.** Unpinned deps, a teammate on Node 18, git-LFS breaking a checkout. Burns hours at the worst possible time and blocks people who are not the cause.
5. **Git collapse with the member new to collaborative git.** Force-push over main, an unresolvable merge on demo morning, a lost branch. Fix upfront with branch protection, small PRs, and a 20-minute pairing session — not with a lecture after it happens.
6. **Wall-clock and randomness leaking into tests or fixtures.** Flaky suite, fixtures that go stale overnight, "it generated different names on Ali's laptop". Erodes trust in your own test results exactly when you need them.
7. **Tamper detection validated against re-rendered images.** If you tamper by editing HTML and re-rendering, every image is internally perfect and your detector was tested against nothing. Tamper in pixel space, post-render.
8. **Allocation uniqueness left to application logic.** Under any concurrency, the same transaction gets allocated twice and `DUPLICATE` — a headline state — silently fails.
9. **Breadth over the result view.** Six half-finished screens beat by one screen that explains a decision. Stack-ranked judging rewards being memorable, not being broad.
10. **Undeclared AI use or prior work.** Explicit disqualification offence under MLH-style rules. Cheap to avoid: a README section listing frameworks, AI usage, and pre-event design docs.

## If we are behind

Cut in this order. Stop as soon as you are back on schedule.

1. **Auth.** One seeded merchant, a hardcoded session. Nobody scores login.
2. **History and filtering.** Ship a plain list. Drop `react-table` entirely.
3. **PostgreSQL.** Stay on SQLite for the demo. Keep the migrations honest so the claim "it moves to Postgres" is true.
4. **Idempotency keys and multi-tenant scoping.** Keep the columns and the constraint; skip the middleware and the tests around them.
5. **Live DashScope calls.** Run the demo off cached extraction fixtures via the fallback adapter, and say so. This is honest and it is fast.
6. **Dataset breadth.** Six canonical fixtures — one per decision state plus one tamper case — instead of the full matrix.
7. **Tamper-evidence signals.** Reduce to one or two cheap observations, or drop the section from the UI. They are advisory by design, so removing them does not change any decision.
8. **Amount-semantics subtlety.** Collapse underpayment / inflation / overpayment to a single mismatch reason code if the rule table is fighting you.

**Never cut:** the five decision states, the DB uniqueness constraint, the per-field evidence view, the golden-file tests, the README, the video.